"""统一错误体。

约定：所有 4xx/5xx 返回 ``{"error_code", "message", "action"}``。
``action`` 是给现场看的"可点动作"，不是给工程师看的堆栈。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


@dataclass
class ApiError(Exception):
    code: str
    message: str
    action: str
    status: int = 400

    def __str__(self) -> str:  # pragma: no cover - 仅日志用
        return f"{self.code}: {self.message}"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error_code": exc.code, "message": exc.message, "action": exc.action},
        )

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "invalid_argument",
                "message": str(exc),
                "action": "检查输入后重试",
            },
        )

    @app.exception_handler(LookupError)
    async def _lookup_error(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "not_found",
                "message": str(exc),
                "action": "返回列表确认对象是否存在",
            },
        )
