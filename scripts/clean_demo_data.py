"""演示数据清理：只保留指定编码链路，其余一并清掉。

默认保留 AB-1234-01（含其模型/判例/数据集/版本），用来继续演示向导。
试跑（预览）与执行分开，执行前会打印将删除的行数与文件数。

    python scripts/clean_demo_data.py                 # 预览
    python scripts/clean_demo_data.py --apply         # 执行
    python scripts/clean_demo_data.py --keep AB-1 --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402
from aip.store import tx  # noqa: E402


def collect(conn, keep: set[str]) -> dict:
    codes = [r["code"] for r in conn.execute("SELECT code FROM product_code").fetchall()]
    remove_codes = [c for c in codes if c not in keep]
    marks = ",".join("?" for _ in remove_codes) or "''"

    stats: dict[str, int] = {}
    stats["codes"] = len(remove_codes)
    if remove_codes:
        stats["jobs"] = conn.execute(
            f"SELECT count(*) c FROM inference_job WHERE code IN ({marks})", remove_codes
        ).fetchone()["c"]
        stats["results"] = conn.execute(
            f"SELECT count(*) c FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
            f" WHERE j.code IN ({marks})",
            remove_codes,
        ).fetchone()["c"]
        stats["cases"] = conn.execute(
            f"SELECT count(*) c FROM case_item c JOIN product_code p ON p.id = c.product_code_id"
            f" WHERE p.code IN ({marks})",
            remove_codes,
        ).fetchone()["c"]
        stats["bindings"] = conn.execute(
            f"SELECT count(*) c FROM binding b JOIN product_code p ON p.id = b.product_code_id"
            f" WHERE p.code IN ({marks})",
            remove_codes,
        ).fetchone()["c"]
    else:
        stats.update(jobs=0, results=0, cases=0, bindings=0)

    stats["blind_batches"] = conn.execute("SELECT count(*) c FROM blind_batch").fetchone()["c"]

    # 清理后不再被任何编码引用的模型
    orphans = conn.execute(
        "SELECT id FROM model WHERE id NOT IN (SELECT DISTINCT model_id FROM binding)"
    ).fetchall()
    stats["models"] = len(orphans)

    ds_orphans = 0
    if orphans:
        ids = [r["id"] for r in orphans]
        ms = ",".join("?" for _ in ids)
        ds_orphans = conn.execute(
            f"SELECT count(*) c FROM dataset WHERE model_id IN ({ms})", ids
        ).fetchone()["c"]
    stats["datasets"] = ds_orphans
    keep_marks = ",".join("?" for _ in keep) or "'"
    stats["families"] = conn.execute(
        f"SELECT count(*) c FROM family WHERE id NOT IN"
        f" (SELECT DISTINCT family_id FROM product_code WHERE code IN ({keep_marks}))",
        sorted(keep),
    ).fetchone()["c"]
    return {"keep": sorted(keep), "remove_codes": remove_codes, "stats": stats}


def wipe(conn, keep: set[str]) -> dict:
    info = collect(conn, keep)
    remove_codes = info["remove_codes"]
    marks = ",".join("?" for _ in remove_codes) or "''"

    with tx(conn):
        conn.execute("DELETE FROM blind_item")
        conn.execute("DELETE FROM blind_batch")

        if remove_codes:
            # 数据集成员里属于待删判例的
            conn.execute(
                "DELETE FROM dataset_item WHERE case_id IN ("
                " SELECT c.id FROM case_item c JOIN product_code p ON p.id = c.product_code_id"
                f" WHERE p.code IN ({marks}))",
                remove_codes,
            )
            conn.execute(
                "DELETE FROM case_item WHERE product_code_id IN"
                f" (SELECT id FROM product_code WHERE code IN ({marks}))",
                remove_codes,
            )
            conn.execute(
                f"DELETE FROM inference_result WHERE job_id IN"
                f" (SELECT id FROM inference_job WHERE code IN ({marks}))",
                remove_codes,
            )
            conn.execute(f"DELETE FROM inference_job WHERE code IN ({marks})", remove_codes)
            conn.execute(
                "DELETE FROM binding WHERE product_code_id IN"
                f" (SELECT id FROM product_code WHERE code IN ({marks}))",
                remove_codes,
            )
            conn.execute(f"DELETE FROM product_code WHERE code IN ({marks})", remove_codes)

        # 失去全部绑定的模型及其版本/配置/阈值/训练任务/数据集
        orphans = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM model WHERE id NOT IN (SELECT DISTINCT model_id FROM binding)"
            ).fetchall()
        ]
        for mid in orphans:
            conn.execute(
                "DELETE FROM dataset_item WHERE dataset_id IN"
                " (SELECT id FROM dataset WHERE model_id = ?)",
                (mid,),
            )
            conn.execute("DELETE FROM dataset WHERE model_id = ?", (mid,))
            conn.execute("DELETE FROM train_job WHERE model_id = ?", (mid,))
            conn.execute(
                "DELETE FROM config_rev WHERE model_version_id IN"
                " (SELECT id FROM model_version WHERE model_id = ?)",
                (mid,),
            )
            conn.execute(
                "DELETE FROM threshold_rev WHERE model_version_id IN"
                " (SELECT id FROM model_version WHERE model_id = ?)",
                (mid,),
            )
            conn.execute("DELETE FROM model_version WHERE model_id = ?", (mid,))
            conn.execute("DELETE FROM model WHERE id = ?", (mid,))

        conn.execute(
            "DELETE FROM family WHERE id NOT IN (SELECT DISTINCT family_id FROM product_code)"
        )
    return info


def clean_files(data_dir: Path, apply: bool) -> dict:
    conn = store.connect(data_dir / "aip.db")
    referenced = set()
    for table in ("case_item", "inference_result"):
        for row in conn.execute(f"SELECT crop_path FROM {table} WHERE crop_path IS NOT NULL"):
            referenced.add(str(Path(row["crop_path"]).resolve()))
    conn.close()

    removed = 0
    freed = 0
    for folder in ("crops", "smoke", "cases"):
        base = data_dir / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and str(path.resolve()) not in referenced:
                if apply:
                    try:
                        freed += path.stat().st_size
                        path.unlink()
                    except OSError:
                        continue
                else:
                    freed += path.stat().st_size
                removed += 1
    return {"files": removed, "bytes": freed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "aip.db"))
    ap.add_argument("--keep", nargs="*", default=["AB-1234-01"])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data_dir = Path(args.db).resolve().parent
    conn = store.connect(Path(args.db))
    keep = set(args.keep)

    before = collect(conn, keep)
    print(f"保留编码: {before['keep']}")
    print(f"将删除编码: {before['remove_codes'] or '（无）'}")
    for k, v in before["stats"].items():
        print(f"  {k}: {v}")

    if not args.apply:
        files = clean_files(data_dir, apply=False)
        print(f"  files: {files['files']}（约 {files['bytes'] / 1048576:.1f} MB）")
        print("\n这是预览。确认后加 --apply。")
        conn.close()
        return 0

    wipe(conn, keep)
    conn.close()
    files = clean_files(data_dir, apply=True)
    print(f"\n已清理：{before['stats']}")
    print(f"已删除文件 {files['files']} 个，释放 {files['bytes'] / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
