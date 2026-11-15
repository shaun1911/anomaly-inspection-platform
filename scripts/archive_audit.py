"""审计归档 CLI。

    python scripts/archive_audit.py            # 预演
    python scripts/archive_audit.py --apply    # 执行（按设置里的保留天数）
    python scripts/archive_audit.py --days 90 --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import audit_archive, store  # noqa: E402
from aip.settings import get_value  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data" / "aip.db"))
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = store.connect(args.db)
    try:
        days = args.days or int(get_value(conn, "audit.retention_days"))
        if not args.apply:
            plan = audit_archive.plan(conn, days)
            print(f"保留 {plan['days']} 天；可归档 {plan['count']} 条（最早 {plan['oldest']}）")
            return 0
        out = audit_archive.archive(conn, Path(args.db).parent, days=days, actor="cli")
        print(f"已归档 {out['archived']} 条 -> {out['path']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
