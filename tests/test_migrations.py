"""T0-1 验收：迁移可升可降、约束生效、重复执行幂等。"""

from __future__ import annotations

import sqlite3

import pytest

from aip import store

EXPECTED_TABLES = {
    "product_code",
    "model",
    "model_version",
    "binding",
    "config_rev",
    "threshold_rev",
    "station",
    "inference_job",
    "inference_result",
    "feedback",
    "case_item",
    "dataset_item",
    "train_job",
    "blind_batch",
    "blind_item",
    "audit_log",
    "setting",
}


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = store.connect(db)
    yield c
    c.close()


LATEST = max(
    int(path.name[:4]) for path in store.MIGRATIONS_DIR.glob("*.sql") if "_down" not in path.name
)


def test_migrate_creates_all_tables(conn):
    assert store.migrate(conn) == LATEST
    assert store.current_version(conn) == LATEST
    assert EXPECTED_TABLES <= store.table_names(conn)


def test_migrate_is_idempotent(conn):
    store.migrate(conn)
    assert store.migrate(conn) == LATEST
    assert store.current_version(conn) == LATEST


def test_rollback_removes_tables(conn):
    store.migrate(conn)
    assert store.rollback(conn) == 0
    assert store.current_version(conn) == 0
    remaining = store.table_names(conn)
    assert not (EXPECTED_TABLES & remaining)


def test_foreign_keys_enforced(conn):
    store.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO model_version (model_id, version_no) VALUES (999, 1)"
        )


def test_idempotency_key_unique(conn):
    store.migrate(conn)
    conn.execute(
        "INSERT INTO inference_job (code, idempotency_key) VALUES ('A-1', 'k1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO inference_job (code, idempotency_key) VALUES ('A-1', 'k1')"
        )


def test_threshold_check_allows_overkill_mode_only_when_marked(conn):
    store.migrate(conn)
    conn.execute("INSERT INTO model (code) VALUES ('m1')")
    conn.execute(
        "INSERT INTO model_version (model_id, version_no) VALUES (1, 1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO threshold_rev (model_version_id, roi_rev, rev, th_lo, th_hi)"
            " VALUES (1, 1, 1, 0.8, 0.2)"
        )
    conn.execute(
        "INSERT INTO threshold_rev (model_version_id, roi_rev, rev, th_lo, th_hi, mode)"
        " VALUES (1, 1, 1, 0.8, 0.2, 'high_overkill')"
    )


def test_feedback_online_is_unique_but_late_is_not(conn):
    store.migrate(conn)
    conn.execute("INSERT INTO model (code) VALUES ('m1')")
    conn.execute("INSERT INTO model_version (model_id, version_no) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO inference_job (code, idempotency_key) VALUES ('A-1', 'k1')"
    )
    conn.execute(
        "INSERT INTO inference_result (job_id, model_version_id, score, label)"
        " VALUES (1, 1, 0.9, 'ng')"
    )
    conn.execute(
        "INSERT INTO feedback (result_id, verdict, source) VALUES (1, 'ok', 'online')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO feedback (result_id, verdict, source) VALUES (1, 'ng', 'online')"
        )
    conn.execute(
        "INSERT INTO feedback (result_id, verdict, source) VALUES (1, 'ng', 'late')"
    )
    conn.execute(
        "INSERT INTO feedback (result_id, verdict, source) VALUES (1, 'ng', 'late')"
    )
