"""证据保留验收：判例与待复核不删，其余按保留期清理。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from aip import retention, store

DAY = 86400


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "r.db"
    conn = store.connect(db)
    store.migrate(conn)
    data_dir = tmp_path
    (data_dir / "crops").mkdir()
    (data_dir / "smoke").mkdir()
    (data_dir / "cases").mkdir()
    yield conn, data_dir
    conn.close()


def _file(path, age_days: float) -> None:
    path.write_bytes(b"x" * 100)
    ts = time.time() - age_days * DAY
    os.utime(path, (ts, ts))


def _seed_result(conn, crop: str, status="done", confirmed=None) -> int:
    conn.execute("INSERT OR IGNORE INTO product_code (code) VALUES ('AB-1')")
    conn.execute("INSERT OR IGNORE INTO model (code) VALUES ('M1')")
    mid = conn.execute("SELECT id FROM model").fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO model_version (model_id, version_no, status) VALUES (?, 1, 'assist')",
        (mid,),
    )
    vid = conn.execute("SELECT id FROM model_version").fetchone()["id"]
    job = conn.execute(
        "INSERT INTO inference_job (code, idempotency_key, status) VALUES ('AB-1', ?, 'done')",
        (f"k{time.time_ns()}",),
    )
    conn.execute(
        "INSERT INTO inference_result (job_id, score, label, model_version_id, crop_path,"
        " review_status, confirmed_at) VALUES (?, 0.9, 'ng', ?, ?, ?, ?)",
        (job.lastrowid, vid, crop, status, confirmed),
    )
    conn.commit()
    return int(job.lastrowid)


def test_plan_keeps_case_and_pending_evidence(env):
    conn, data_dir = env
    case_img = data_dir / "crops" / "case.png"
    pend_img = data_dir / "crops" / "pending.png"
    old_img = data_dir / "crops" / "old.png"
    smoke = data_dir / "smoke" / "s.png"
    for p, age in ((case_img, 90), (pend_img, 90), (old_img, 90), (smoke, 30)):
        _file(p, age)

    _seed_result(conn, str(case_img), status="done", confirmed="2026-01-01T00:00:00Z")
    _seed_result(conn, str(pend_img), status="pending", confirmed=None)
    _seed_result(conn, str(old_img), status="done", confirmed="2026-01-01T00:00:00Z")

    conn.execute("INSERT INTO product_code (code) VALUES ('AB-2')")
    pid = conn.execute("SELECT id FROM product_code WHERE code='AB-2'").fetchone()["id"]
    conn.execute(
        "INSERT INTO case_item (product_code_id, crop_path, verdict, adjudicator)"
        " VALUES (?, ?, 'ok', 'z')",
        (pid, str(case_img)),
    )
    conn.commit()

    plan = retention.plan(conn, data_dir, crop_days=30, smoke_days=7)
    paths = {Path(d["path"]).name for d in plan["deletable"]}
    assert "case.png" not in paths      # 判例引用
    assert "pending.png" not in paths   # 待复核
    assert "old.png" in paths           # 旧且已确认
    assert "s.png" in paths             # 旧冒烟图


def test_fresh_files_are_kept(env):
    conn, data_dir = env
    fresh = data_dir / "crops" / "fresh.png"
    _file(fresh, 1)
    _seed_result(conn, str(fresh), status="done", confirmed="2026-01-01T00:00:00Z")
    plan = retention.plan(conn, data_dir, crop_days=30, smoke_days=7)
    assert plan["count"] == 0


def test_apply_deletes_and_audits(env):
    conn, data_dir = env
    old = data_dir / "crops" / "old.png"
    _file(old, 90)
    _seed_result(conn, str(old), status="done", confirmed="2026-01-01T00:00:00Z")

    out = retention.apply(conn, data_dir, crop_days=30, smoke_days=7)
    assert out["removed"] == 1
    assert not old.exists()
    audit = conn.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert audit["action"] == "storage.retention"

