"""静态页面（T2-1 开发版）。

工位面板与管理页先以单文件形式提供，不做构建步骤：现场机器只要能开浏览器就能用。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..settings import get_value
from .deps import get_conn

import sqlite3

router = APIRouter(tags=["web"])

WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def _page(name: str) -> FileResponse:
    return FileResponse(WEB_DIR / name, media_type="text/html; charset=utf-8")


@router.get("/panel", include_in_schema=False)
def panel(conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    if not get_value(conn, "ui.panel_enabled"):
        raise HTTPException(status_code=404, detail="工位面板已在「设置 → 接入」中关闭")
    return _page("panel.html")


@router.get("/admin", include_in_schema=False)
def admin() -> FileResponse:
    return _page("admin.html")
