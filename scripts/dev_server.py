"""开发服务器入口：迁移 → 起 uvicorn。

    python scripts/dev_server.py [--host 127.0.0.1] [--port 8100] [--db data/aip.db]

只用于开发与演示：前台运行、Ctrl+C 停止、不注册服务。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

import uvicorn  # noqa: E402

from aip import store  # noqa: E402
from aip.api.app import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--db", default=str(ROOT / "data" / "aip.db"))
    args = parser.parse_args()

    conn = store.connect(args.db)
    version = store.migrate(conn)
    conn.close()
    print(f"db ready: {args.db} (schema v{version})")
    print(f"panel:  http://{args.host}:{args.port}/panel")
    print(f"docs:   http://{args.host}:{args.port}/docs")

    uvicorn.run(create_app(args.db), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
