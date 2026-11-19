from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.db import DEFAULT_DB_PATH, init_db


def error_response(
    status_code: int,
    code: str,
    message: str,
    fields: list[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": code,
                "message": message,
                "fields": fields or [],
            }
        },
    )


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    resolved_db_path = Path(db_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        init_db(resolved_db_path)
        yield

    application = FastAPI(
        title="Інтелектуальна система керування списком покупок",
        lifespan=lifespan,
    )
    application.state.db_path = resolved_db_path

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ())),
                "message": str(err.get("msg", "Некоректне значення.")),
            }
            for err in exc.errors()
        ]
        return error_response(
            status_code=422,
            code="validation_error",
            message="Некоректні вхідні дані.",
            fields=fields,
        )

    @application.exception_handler(Exception)
    async def handle_internal_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return error_response(
            status_code=500,
            code="internal_error",
            message="Внутрішня помилка сервера.",
        )

    @application.get("/health")
    async def health(request: Request) -> JSONResponse:
        fields: list[dict[str, str]] = []
        for key in request.query_params.keys():
            fields.append(
                {
                    "field": f"query.{key}",
                    "message": "Маршрут не приймає query-параметрів.",
                }
            )
        if await request.body():
            fields.append(
                {
                    "field": "body",
                    "message": "GET-запит не приймає тіло.",
                }
            )
        if fields:
            return error_response(
                status_code=422,
                code="validation_error",
                message="Зайві вхідні дані для GET /health.",
                fields=fields,
            )
        return JSONResponse(status_code=200, content={"status": "ok"})

    return application


app = create_app()
