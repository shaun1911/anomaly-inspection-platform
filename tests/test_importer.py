"""T0-3 验收：落地目录导入的校验、去重与确定性切分。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from aip import store
from aip.importer import import_landing


@pytest.fixture()
def conn(tmp_path):
    c = store.connect(tmp_path / "test.db")
    store.migrate(c)
    c.execute("INSERT INTO model (code) VALUES ('m1')")
    c.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    c.execute("INSERT INTO product_code (code, active) VALUES ('OLD-1', 0)")
    yield c
    c.close()


def _png(path: Path, size=(8, 8), seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    color = ((seed * 37) % 256, (seed * 91) % 256, (seed * 13) % 256)
    Image.new("RGB", size, color).save(path)
    return path


def test_imports_ok_and_ng_with_deterministic_split(conn, tmp_path):
    landing = tmp_path / "landing"
    for i in range(10):
        _png(landing / "AB-1" / "ok" / f"P1_{i}.png", seed=i)
    for i in range(4):
        _png(landing / "AB-1" / "ng" / f"P1_{i}.png", seed=100 + i)

    report = import_landing(conn, landing, model_id=1)
    assert report.total_imported == 14
    assert report.rejected == []

    rows = conn.execute("SELECT split, count(*) c FROM import_item GROUP BY split").fetchall()
    counts = {r["split"]: r["c"] for r in rows}
    assert counts["train"] + counts["frozen_val"] == 14
    # 确定性：再导一次不应新增
    again = import_landing(conn, landing, model_id=1)
    assert again.total_imported == 0
    assert again.skipped_duplicate == 14


def test_split_is_stable_for_same_file(conn, tmp_path):
    landing = tmp_path / "landing"
    _png(landing / "AB-1" / "ng" / "P1_0.png")
    import_landing(conn, landing, model_id=1)
    first = conn.execute("SELECT split, sha256 FROM import_item").fetchone()

    conn.execute("DELETE FROM import_item")
    import_landing(conn, landing, model_id=1)
    second = conn.execute("SELECT split, sha256 FROM import_item").fetchone()
    assert first["sha256"] == second["sha256"]
    assert first["split"] == second["split"]


def test_rejects_unknown_and_inactive_code(conn, tmp_path):
    landing = tmp_path / "landing"
    _png(landing / "NOPE-9" / "ok" / "P1_0.png")
    _png(landing / "OLD-1" / "ok" / "P1_0.png")

    report = import_landing(conn, landing, model_id=1)
    reasons = {reason for _, reason in report.rejected}
    assert "unknown_code" in reasons
    assert "inactive_code" in reasons
    assert report.total_imported == 0


def test_rejects_bad_files(conn, tmp_path):
    landing = tmp_path / "landing"
    _png(landing / "AB-1" / "ok" / "P1_0.png")
    (landing / "AB-1" / "ok" / "notes.txt").write_text("x", encoding="utf-8")
    broken = landing / "AB-1" / "ok" / "P1_1.png"
    broken.write_bytes(b"not an image")

    report = import_landing(conn, landing, model_id=1)
    reasons = {reason for _, reason in report.rejected}
    assert "unsupported_extension" in reasons
    assert "unreadable_image" in reasons
    assert report.total_imported == 1


def test_rejects_unknown_label_dir(conn, tmp_path):
    landing = tmp_path / "landing"
    _png(landing / "AB-1" / "maybe" / "P1_0.png")
    report = import_landing(conn, landing, model_id=1)
    assert ("unknown_label" in {reason for _, reason in report.rejected}) or report.total_imported == 0


def test_missing_landing_dir_raises(conn, tmp_path):
    with pytest.raises(FileNotFoundError):
        import_landing(conn, tmp_path / "nope", model_id=1)
