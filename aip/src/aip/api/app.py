"""API 装配（T1-1）。

只做最小可运行：错误体统一、``/health`` 可观测、依赖注入连接。
路由逐步挂载，不在这里写业务。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI

from .. import store
from .deps import get_conn
from .errors import install_error_handlers

VERSION = "0.1.0"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="AIP", version=VERSION)
    app.state.db_path = Path(db_path) if db_path is not None else store.default_db_path()
    install_error_handlers(app)

    @app.get("/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        db_ok = True
        queue_depth = -1
        try:
            conn.execute("SELECT 1").fetchone()
            queue_depth = conn.execute(
                "SELECT count(*) c FROM inference_job WHERE status = 'queued'"
            ).fetchone()["c"]
        except sqlite3.Error:
            db_ok = False

        return {
            "status": "ok" if db_ok else "degraded",
            "version": VERSION,
            "db": "ok" if db_ok else "error",
            "queue_depth": queue_depth,
            "pool": "not_started",
        }

    from . import (
        routes_admin,
        routes_catalog,
        routes_infer,
        routes_results,
        routes_review,
        routes_settings,
        routes_train,
        routes_families,
        routes_datasets,
        routes_station,
        routes_web,
    )

    app.include_router(routes_admin.router)
    app.include_router(routes_catalog.router)
    app.include_router(routes_station.router)
    app.include_router(routes_infer.router)
    app.include_router(routes_results.router)
    app.include_router(routes_review.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_train.router)
    app.include_router(routes_families.router)
    app.include_router(routes_datasets.router)
    app.include_router(routes_web.router)
    return app
