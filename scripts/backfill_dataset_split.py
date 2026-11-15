"""给已冻结但未划分 train/val 的数据集补划分。

    python scripts/backfill_dataset_split.py            # 预览
    python scripts/backfill_dataset_split.py --apply
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import datasets, store  # noqa: E402


def main(apply: bool) -> int:
    conn = store.connect(ROOT / "data" / "aip.db")
    rows = conn.execute(
        "SELECT d.id, d.name FROM dataset d WHERE d.status = 'frozen' AND NOT EXISTS ("
        " SELECT 1 FROM dataset_item i WHERE i.dataset_id = d.id AND i.split = 'frozen_val')"
    ).fetchall()
    print(f"待补划分的数据集：{len(rows)}")
    for r in rows:
        print(f"  #{r['id']} {r['name']}")
    if apply:
        with conn:
            for r in rows:
                out = datasets.assign_splits(conn, r["id"])
                print(f"  #{r['id']} → train {out['train']} / val {out['val']}")
        print("已补划分")
    else:
        print("预览。确认后加 --apply")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
