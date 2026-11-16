"""训练任务调度：起后台进程、回写数据库。

真实训练不占 FastAPI 工作线程：worker 是独立 Python 进程，日志落到
data/runs/<code>-vN/train.log，结果写 result.json 后由本模块回写。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import store
from ..audit import record
from ..serving.cache import cache
from ..store import tx

_WORKER = Path(__file__).resolve().parent / "anomalib_worker.py"
_ACTIVE: dict[int, subprocess.Popen] = {}


def _db_path(conn) -> Path:
    return Path(conn.execute("PRAGMA database_list").fetchone()[2])


def _run_dir(data_dir: Path, model_code: str, version_no: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in model_code)
    return data_dir / "runs" / f"{safe}-v{version_no}-{stamp}"


def launch(*, db_path: Path, job_id: int, model_id: int, model_code: str,
           version_no: int, dataset_id: int) -> None:
    """在后台线程里跑 worker；调用方已完成事务提交。"""
    thread = threading.Thread(
        target=_run,
        args=(db_path, job_id, model_id, model_code, version_no, dataset_id),
        name=f"train-{job_id}",
        daemon=True,
    )
    thread.start()


def _manifest(conn, dataset_id: int) -> tuple[list[dict], list[str]]:
    rows = conn.execute(
        "SELECT i.case_id, i.split, COALESCE(i.verdict_at_freeze, c.verdict) verdict,"
        " c.crop_path, c.part_no FROM dataset_item i JOIN case_item c ON c.id = i.case_id"
        " WHERE i.dataset_id = ? ORDER BY i.case_id",
        (dataset_id,),
    ).fetchall()
    items: list[dict] = []
    missing: list[str] = []
    for r in rows:
        path = Path(r["crop_path"] or "")
        if not path.is_file():
            missing.append(str(path))
            continue
        items.append({
            "case_id": int(r["case_id"]),
            "split": r["split"] or "train",
            "verdict": r["verdict"],
            "path": str(path),
            "part_no": r["part_no"],
        })
    return items, missing


def _run(db_path: Path, job_id: int, model_id: int, model_code: str,
         version_no: int, dataset_id: int) -> None:
    data_dir = db_path.parent
    conn = store.connect(db_path)
    try:
        items, missing = _manifest(conn, dataset_id)
        run_dir = _run_dir(data_dir, model_code, version_no)
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "train.log"
        result_path = run_dir / "result.json"
        if missing:
            raise RuntimeError(f"{len(missing)} 个判例图文件丢失，先修判例库: {missing[:3]}")
        cfg = {
            "run_dir": str(run_dir),
            "result_path": str(result_path),
            "model_code": model_code,
            "version_no": version_no,
            "items": items,
            "image_size": 256,
            "batch_size": 16,
            "backbone": "wide_resnet50_2",
            "coreset_sampling_ratio": 0.1,
            "seed": 42,
        }
        cfg_path = run_dir / "config.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["AIP_DB"] = str(db_path)
        src = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(
                [sys.executable, str(_WORKER), str(cfg_path)],
                stdout=log, stderr=subprocess.STDOUT, env=env,
            )
            _ACTIVE[job_id] = proc
            try:
                code = proc.wait(timeout=6 * 3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise RuntimeError("训练超时（6 小时）") from None
            finally:
                _ACTIVE.pop(job_id, None)

        if not result_path.is_file():
            raise RuntimeError(f"worker 未产出结果，退出码 {code}，看日志 {log_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "ok":
            raise RuntimeError(result.get("error") or result.get("traceback") or "worker 失败")

        metrics = result["metrics"]
        roi = result.get("roi_rect") or [0, 0, 512, 512]
        models_dir = data_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        final_onnx = models_dir / f"{model_code}-v{version_no}.onnx"
        shutil.copy2(result["onnx_path"], final_onnx)
        # torch ONNX 可能把权重拆成 .onnx.data 外部文件，必须一起复制
        for sidecar in Path(result["onnx_path"]).parent.glob(Path(result["onnx_path"]).name + ".*"):
            shutil.copy2(sidecar, models_dir / sidecar.name)

        with tx(conn):
            version = conn.execute(
                "SELECT id FROM model_version WHERE model_id = ? AND version_no = ?",
                (model_id, version_no),
            ).fetchone()
            if version is None:
                raise RuntimeError("版本记录已不存在")
            vid = int(version["id"])
            conn.execute(
                "UPDATE model_version SET status = 'candidate', metrics_json = ?, onnx_path = ?,"
                " onnx_input_range = ?, onnx_aggregate = ? WHERE id = ?",
                (json.dumps(metrics, ensure_ascii=False), str(final_onnx),
                 result.get("input_range", "zero_one"), result.get("aggregate", "max"), vid),
            )
            cfgrow = conn.execute(
                "SELECT rev FROM config_rev WHERE model_version_id = ? ORDER BY rev DESC LIMIT 1",
                (vid,),
            ).fetchone()
            if cfgrow is None:
                conn.execute(
                    "INSERT INTO config_rev (model_version_id, rev, roi_rect) VALUES (?, 1, ?)",
                    (vid, json.dumps(roi)),
                )
                roi_rev = 1
            else:
                roi_rev = int(cfgrow["rev"])
            th = conn.execute(
                "SELECT rev FROM threshold_rev WHERE model_version_id = ? AND roi_rev = ?",
                (vid, roi_rev),
            ).fetchone()
            if th is None:
                conn.execute(
                    "INSERT INTO threshold_rev (model_version_id, roi_rev, rev, th_lo, th_hi, reason)"
                    " VALUES (?, ?, 1, ?, ?, ?)",
                    (vid, roi_rev, float(metrics["th_lo"]), float(metrics["th_hi"]), "训练自动标定"),
                )
            conn.execute(
                "UPDATE train_job SET status = 'succeeded', metrics_json = ?,"
                " finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (json.dumps(metrics, ensure_ascii=False), job_id),
            )
            record(conn, actor="trainer", action="train.finish", entity="train_job",
                   entity_id=job_id,
                   payload={"version_no": version_no, "recall": metrics.get("recall"),
                            "overkill": metrics.get("overkill")})
        cache.unload(f"{model_id}:{version_no}", force=True)
        print(f"[trainer] job {job_id} done: {metrics}", flush=True)
    except Exception as exc:  # noqa: BLE001
        try:
            detail = str(exc)
            with tx(conn):
                conn.execute(
                    "UPDATE train_job SET status = 'failed', error_code = ?, metrics_json = ?,"
                    " finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                    ("worker_failed", json.dumps({"error": detail}, ensure_ascii=False), job_id),
                )
                conn.execute(
                    "UPDATE model_version SET status = 'disabled', metrics_json = ?"
                    " WHERE model_id = ? AND version_no = ?",
                    (json.dumps({"error": detail}, ensure_ascii=False), model_id, version_no),
                )
                record(conn, actor="trainer", action="train.fail", entity="train_job",
                       entity_id=job_id, payload={"error": detail[:500]})
        except Exception:  # noqa: BLE001
            pass
        print(f"[trainer] job {job_id} failed: {exc}", flush=True)
    finally:
        conn.close()
