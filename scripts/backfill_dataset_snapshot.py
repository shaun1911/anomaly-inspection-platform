"""给已冻结但缺快照的数据集补快照（功能上线前冻结的存量）。

    python scripts/backfill_dataset_snapshot.py            # 预览
    python scripts/backfill_dataset_snapshot.py --apply
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402
from aip.dataset_audit import snapshot  # noqa: E402


def main(apply: bool) -> int:
    conn = store.connect(ROOT / "data" / "aip.db")
    rows = conn.execute(
        "SELECT d.id, d.name, count(i.id) missing FROM dataset d"
        " JOIN dataset_item i ON i.dataset_id = d.id"
        " WHERE d.status = 'frozen' AND i.verdict_at_freeze IS NULL"
        " GROUP BY d.id"
    ).fetchall()
    print(f"缺快照的数据集：{len(rows)}")
    for r in rows:
        print(f"  #{r['id']} {r['name']} · {r['missing']} 条")
    if apply:
        with conn:
            for r in rows:
                snapshot(conn, r["id"])
        print("已补快照")
    else:
        print("预览。确认后加 --apply")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
