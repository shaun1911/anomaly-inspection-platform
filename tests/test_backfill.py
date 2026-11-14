"""存量批次回填验收。"""

from __future__ import annotations

import pytest

from aip import backfill, store


@pytest.fixture()
def conn(tmp_path):
    c = store.connect(tmp_path / "b.db")
    store.migrate(c)
    yield c
    c.close()


def _job(conn, code: str, created: str, key: str) -> int:
    cur = conn.execute(
        "INSERT INTO inference_job (code, idempotency_key, status, created_at)"
        " VALUES (?, ?, 'done', ?)",
        (code, key, created),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_derive_batch_rules():
    assert backfill.derive_batch("2026-11-14T03:00:00.000Z", "daily") == "LEGACY-20261114"
    assert backfill.derive_batch("2026-11-14T06:59:00.000Z", "shift") == "LEGACY-20261114-N"
    assert backfill.derive_batch("2026-11-14T07:00:00.000Z", "shift") == "LEGACY-20261114-D"
    assert backfill.derive_batch("2026-11-14T19:00:00.000Z", "shift") == "LEGACY-20261114-N"


def test_dry_run_does_not_write(conn):
    _job(conn, "AB-1", "2026-11-14T03:00:00.000Z", "k1")
    out = backfill.backfill(conn, rule="daily", apply=False)
    assert out["jobs"] == 1
    assert out["applied"] is False
    row = conn.execute("SELECT batch_no FROM inference_job").fetchone()
    assert row["batch_no"] is None


def test_apply_writes_job_case_and_audit(conn):
    jid = _job(conn, "AB-1", "2026-11-14T03:00:00.000Z", "k1")
    conn.execute("INSERT INTO model (code) VALUES ('M1')")
    mid = conn.execute("SELECT id FROM model").fetchone()["id"]
    conn.execute("INSERT INTO model_version (model_id, version_no, status) VALUES (?, 1, 'assist')", (mid,))
    vid = conn.execute("SELECT id FROM model_version").fetchone()["id"]
    conn.execute(
        "INSERT INTO inference_result (job_id, score, label, model_version_id)"
        " VALUES (?, 0.9, 'ng', ?)",
        (jid, vid),
    )
    rid = conn.execute("SELECT id FROM inference_result").fetchone()["id"]
    conn.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    pid = conn.execute("SELECT id FROM product_code").fetchone()["id"]
    conn.execute(
        "INSERT INTO case_item (product_code_id, crop_path, verdict, adjudicator, result_id)"
        " VALUES (?, 'x.png', 'ng', 'z', ?)",
        (pid, rid),
    )
    conn.commit()

    out = backfill.backfill(conn, rule="daily", apply=True)
    assert out["applied"] is True
    assert out["jobs"] == 1

    job = conn.execute("SELECT batch_no, batch_source FROM inference_job").fetchone()
    assert job["batch_no"] == "LEGACY-20261114"
    assert job["batch_source"] == "backfill"

    case = conn.execute("SELECT batch_no, batch_source FROM case_item").fetchone()
    assert case["batch_no"] == "LEGACY-20261114"
    assert case["batch_source"] == "backfill"

    audit = conn.execute("SELECT action FROM audit_log").fetchone()
    assert audit["action"] == "batch.backfill"


def test_csv_mapping_takes_priority(conn):
    jid = _job(conn, "AB-1", "2026-11-14T03:00:00.000Z", "k1")
    out = backfill.backfill(conn, mapping={jid: "MES-B-77"}, apply=True)
    assert out["rule"] == "csv"
    row = conn.execute("SELECT batch_no FROM inference_job").fetchone()
    assert row["batch_no"] == "MES-B-77"


def test_orphan_case_uses_own_created_at(conn):
    conn.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    pid = conn.execute("SELECT id FROM product_code").fetchone()["id"]
    conn.execute(
        "INSERT INTO case_item (product_code_id, crop_path, verdict, adjudicator, created_at)"
        " VALUES (?, 'x.png', 'ok', 'z', '2026-11-01T10:00:00.000Z')",
        (pid,),
    )
    conn.commit()
    backfill.backfill(conn, rule="daily", apply=True)
    row = conn.execute("SELECT batch_no FROM case_item").fetchone()
    assert row["batch_no"] == "LEGACY-20261101"
