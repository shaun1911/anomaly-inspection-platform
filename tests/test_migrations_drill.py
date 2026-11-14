"""迁移演练：升到最新 → 全量降级 → 再升，结构必须一致。

这是"可迁移"的最低保证：任何一版迁移写坏 down，演练就会红。
"""

from __future__ import annotations

import pytest

from aip import store


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "drill.db"


def _tables(conn) -> set[str]:
    return store.table_names(conn)


def test_full_up_down_up_drill(db):
    conn = store.connect(db)

    top = store.migrate(conn)
    assert top >= 1
    up_tables = _tables(conn)
    assert "product_code" in up_tables
    assert "dataset_item" in up_tables
    assert "blind_batch" in up_tables

    assert store.rollback(conn, target=0) == 0
    assert store.current_version(conn) == 0
    left = _tables(conn)
    assert left <= {"schema_version", "sqlite_sequence"} or not left, f"降级后仍有表: {left}"

    again = store.migrate(conn)
    assert again == top
    assert _tables(conn) == up_tables
    conn.close()


def test_down_then_up_midway(db):
    """只降一级再升回来：模拟回补丁而不是全量重建。"""
    conn = store.connect(db)
    top = store.migrate(conn)
    conn.close()

    conn = store.connect(db)
    assert store.rollback(conn, target=top - 1) == top - 1
    assert store.current_version(conn) == top - 1
    assert store.migrate(conn) == top
    assert "dataset_item" in _tables(conn)
    conn.close()
