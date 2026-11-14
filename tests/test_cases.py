"""T0-6 验收：判例库增删查、筛选与导出。"""

from __future__ import annotations

import pytest

from aip import store
from aip.cases import (
    count_cases,
    create_case,
    delete_case,
    export_for_training,
    get_case,
    list_cases,
)


@pytest.fixture()
def conn(tmp_path):
    c = store.connect(tmp_path / "test.db")
    store.migrate(c)
    c.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    c.execute("INSERT INTO product_code (code) VALUES ('CD-2')")
    yield c
    c.close()


def test_create_and_get(conn):
    cid = create_case(
        conn,
        product_code="AB-1",
        crop_path="/data/c/1.jpg",
        verdict="ng",
        adjudicator="zhoubin",
        reason="边部划痕",
    )
    case = get_case(conn, cid)
    assert case is not None
    assert case.code == "AB-1"
    assert case.verdict == "ng"
    assert case.reason == "边部划痕"


def test_create_rejects_unknown_code_and_bad_verdict(conn):
    with pytest.raises(LookupError):
        create_case(conn, product_code="NOPE", crop_path="x.jpg", verdict="ok", adjudicator="z")
    with pytest.raises(ValueError):
        create_case(conn, product_code="AB-1", crop_path="x.jpg", verdict="gray", adjudicator="z")


def test_list_filters_by_code_adjudicator_verdict(conn):
    create_case(conn, product_code="AB-1", crop_path="a.jpg", verdict="ok", adjudicator="z")
    create_case(conn, product_code="AB-1", crop_path="b.jpg", verdict="ng", adjudicator="z")
    create_case(conn, product_code="CD-2", crop_path="c.jpg", verdict="ng", adjudicator="li")

    assert len(list_cases(conn)) == 3
    assert len(list_cases(conn, code="AB-1")) == 2
    assert len(list_cases(conn, adjudicator="li")) == 1
    assert len(list_cases(conn, verdict="ng")) == 2
    assert count_cases(conn, code="AB-1") == 2


def test_list_is_newest_first(conn):
    first = create_case(conn, product_code="AB-1", crop_path="a.jpg", verdict="ok", adjudicator="z")
    second = create_case(conn, product_code="AB-1", crop_path="b.jpg", verdict="ok", adjudicator="z")
    ids = [c.id for c in list_cases(conn)]
    assert ids[0] == second and ids[1] == first


def test_delete(conn):
    cid = create_case(conn, product_code="AB-1", crop_path="a.jpg", verdict="ok", adjudicator="z")
    assert delete_case(conn, cid) is True
    assert get_case(conn, cid) is None
    assert delete_case(conn, cid) is False


def test_export_splits_normal_and_defect(conn):
    create_case(conn, product_code="AB-1", crop_path="a.jpg", verdict="ok", adjudicator="z")
    create_case(conn, product_code="AB-1", crop_path="b.jpg", verdict="ng", adjudicator="z")
    out = export_for_training(conn, code="AB-1")
    assert len(out["normal"]) == 1
    assert len(out["defect"]) == 1
