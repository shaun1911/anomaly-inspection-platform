"""给存量判例补 sha256（迁移前录入的条目没有该列）。

冲突处理：若补 sha 时撞唯一索引，说明存量里已有同图条目——记下来，人工裁决，不自动删。

    python scripts/backfill_case_sha.py
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402

DB = ROOT / "data" / "aip.db"


def sha_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    conn = store.connect(DB)
    rows = conn.execute(
        "SELECT id, product_code_id, crop_path FROM case_item WHERE sha256 IS NULL"
    ).fetchall()
    filled = 0
    skipped: list[tuple[int, str]] = []
    for row in rows:
        sha = sha_of(Path(row["crop_path"]))
        if sha is None:
            skipped.append((row["id"], "文件不存在"))
            continue
        try:
            with conn:
                conn.execute("UPDATE case_item SET sha256 = ? WHERE id = ?", (sha, row["id"]))
            filled += 1
        except sqlite3.IntegrityError:
            skipped.append((row["id"], "同图已存在"))
    conn.close()
    print(f"补齐 {filled} 条；跳过 {len(skipped)} 条")
    for cid, why in skipped:
        print("  -", cid, why)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
