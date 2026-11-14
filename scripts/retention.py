"""证据保留清理。

    python scripts/retention.py            # 预览
    python scripts/retention.py --apply    # 执行（留审计）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import retention, settings as settings_mod, store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "aip.db"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = store.connect(Path(args.db))
    data_dir = Path(args.db).resolve().parent
    crop_days = settings_mod.get_value(conn, "retention.crop_days")
    smoke_days = settings_mod.get_value(conn, "retention.smoke_days")
    out = (
        retention.apply(conn, data_dir, crop_days=crop_days, smoke_days=smoke_days)
        if args.apply
        else retention.plan(conn, data_dir, crop_days=crop_days, smoke_days=smoke_days)
    )
    conn.close()
    printable = {k: v for k, v in out.items() if k != "deletable"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if not args.apply:
        print("预览。确认后加 --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
