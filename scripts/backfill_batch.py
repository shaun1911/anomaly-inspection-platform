"""存量批次回填 CLI。

    python scripts/backfill_batch.py --rule daily            # 预览
    python scripts/backfill_batch.py --rule daily --apply    # 写入（留审计）
    python scripts/backfill_batch.py --mapping mes.csv --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import backfill, store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "aip.db"))
    ap.add_argument("--rule", choices=["daily", "shift"], default="daily")
    ap.add_argument("--mapping", help="CSV: job_id,batch_no（优先级高于 rule）")
    ap.add_argument("--apply", action="store_true", help="真正写入；缺省只预览")
    ap.add_argument("--actor", default="backfill")
    args = ap.parse_args()

    conn = store.connect(Path(args.db))
    mapping = backfill.load_mapping(args.mapping) if args.mapping else None
    out = backfill.backfill(conn, rule=args.rule, mapping=mapping, apply=args.apply, actor=args.actor)
    conn.close()

    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out["applied"]:
        print("\n这是预览。确认无误后加 --apply 写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
