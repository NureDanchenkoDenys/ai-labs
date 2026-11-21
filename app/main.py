import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.db import DEFAULT_DB_PATH, init_db
from app.schemas import (
    CategoryResponse,
    ShoppingItemCreate,
    ShoppingItemFilterQuery,
    ShoppingItemPurchaseUpdate,
    ShoppingItemResponse,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListDetailResponse,
    ShoppingListResponse,
    ShoppingListStatisticsResponse,
)
from app.services import (
    CategoryNotFoundError,
    ItemNotFoundError,
    ItemValidationError,
    ListNotFoundError,
    create_shopping_item,
    create_shopping_list,
    delete_shopping_item,
    get_shopping_list,
    get_shopping_list_statistics,
    list_categories,
    list_shopping_lists,
    update_shopping_item,
    update_shopping_item_purchase,
)


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


ALLOWED_LIST_FILTER_PARAMS = frozenset({"category_id", "is_purchased"})


def _unexpected_query_fields(request: Request) -> list[dict[str, str]]:
    return [
        {
            "field": f"query.{key}",
            "message": "Маршрут не приймає query-параметрів.",
        }
        for key, _ in request.query_params.multi_items()
    ]


async def _unexpected_no_body_input_response(
    request: Request,
    route_label: str,
    method: str,
) -> JSONResponse | None:
    fields = _unexpected_query_fields(request)
    if await request.body():
        fields.append(
            {
                "field": "body",
                "message": f"{method}-запит не приймає тіло.",
            }
        )
    if fields:
        return error_response(
            status_code=422,
            code="validation_error",
            message=f"Зайві вхідні дані для {route_label}.",
            fields=fields,
        )
    return None


async def _unexpected_get_input_response(
    request: Request,
    route_label: str,
) -> JSONResponse | None:
    return await _unexpected_no_body_input_response(
        request=request,
        route_label=route_label,
        method="GET",
    )


async def _parse_get_list_filters(
    request: Request,
) -> tuple[ShoppingItemFilterQuery | None, JSONResponse | None]:
    fields: list[dict[str, str]] = []
    seen_allowed: dict[str, list[str]] = {}

    for key, value in request.query_params.multi_items():
        if key not in ALLOWED_LIST_FILTER_PARAMS:
            fields.append(
                {
                    "field": f"query.{key}",
                    "message": "Невідомий query-параметр для GET /lists/{list_id}.",
                }
            )
        else:
            seen_allowed.setdefault(key, []).append(value)

    single_allowed: dict[str, str] = {}
    for key, values in seen_allowed.items():
        if len(values) > 1:
            fields.append(
                {
                    "field": f"query.{key}",
                    "message": "Повторення query-параметра не допускається.",
                }
            )
        else:
            single_allowed[key] = values[0]

    parsed: ShoppingItemFilterQuery | None = None
    try:
        parsed = ShoppingItemFilterQuery.model_validate(single_allowed)
    except ValidationError as exc:
        fields.extend(_format_validation_fields(exc.errors(), prefix=("query",)))

    if await request.body():
        fields.append(
            {
                "field": "body",
                "message": "GET-запит не приймає тіло.",
            }
        )

    if fields:
        return (
            None,
            error_response(
                status_code=422,
                code="validation_error",
                message="Некоректні вхідні дані для GET /lists/{list_id}.",
                fields=fields,
            ),
        )

    return (parsed, None)


def _format_validation_fields(
    errors: Sequence[Mapping[str, Any]],
    prefix: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for err in errors:
        loc = (*prefix, *(str(part) for part in err.get("loc", ())))
        msg = str(err.get("msg", "Некоректне значення."))
        if msg.startswith("Value error, "):
            msg = msg.removeprefix("Value error, ")
        fields.append(
            {
                "field": ".".join(loc) if loc else "body",
                "message": msg,
            }
        )
    return fields


def _reject_json_constant(constant: str) -> Any:
    raise ValueError(f"Недопустима JSON-константа: {constant}")


async def _parse_json_object_body(
    request: Request,
    route_label: str,
    empty_body_message: str,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    raw_body = await request.body()
    content_type_header = request.headers.get("content-type", "")
    media_type = content_type_header.split(";", 1)[0].strip().lower()

    if media_type != "application/json" and (
        bool(content_type_header) or bool(raw_body)
    ):
        return (
            None,
            error_response(
                status_code=415,
                code="unsupported_media_type",
                message="Очікується Content-Type: application/json.",
            ),
        )

    query_fields = _unexpected_query_fields(request)
    if query_fields:
        return (
            None,
            error_response(
                status_code=422,
                code="validation_error",
                message=f"Зайві вхідні дані для {route_label}.",
                fields=query_fields,
            ),
        )

    if not raw_body:
        return (
            None,
            error_response(
                status_code=422,
                code="validation_error",
                message="Тіло запиту є обов’язковим.",
                fields=[
                    {
                        "field": "body",
                        "message": empty_body_message,
                    }
                ],
            ),
        )

    try:
        body_data = json.loads(
            raw_body.decode("utf-8"),
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return (
            None,
            error_response(
                status_code=422,
                code="validation_error",
                message="Некоректний JSON у тілі запиту.",
                fields=[
                    {
                        "field": "body",
                        "message": "Тіло запиту має бути коректним JSON-об’єктом.",
                    }
                ],
            ),
        )

    if not isinstance(body_data, dict):
        return (
            None,
            error_response(
                status_code=422,
                code="validation_error",
                message="Тіло запиту має бути JSON-об’єктом.",
                fields=[
                    {
                        "field": "body",
                        "message": "Очікується JSON-об’єкт.",
                    }
                ],
            ),
        )

    return (body_data, None)


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
        return error_response(
            status_code=422,
            code="validation_error",
            message="Некоректні вхідні дані.",
            fields=_format_validation_fields(exc.errors()),
        )

    @application.exception_handler(ListNotFoundError)
    async def handle_list_not_found_error(
        request: Request,
        exc: ListNotFoundError,
    ) -> JSONResponse:
        return error_response(
            status_code=404,
            code="list_not_found",
            message=f"Список {exc.list_id} не знайдено.",
        )

    @application.exception_handler(ItemNotFoundError)
    async def handle_item_not_found_error(
        request: Request,
        exc: ItemNotFoundError,
    ) -> JSONResponse:
        return error_response(
            status_code=404,
            code="item_not_found",
            message=f"Позицію {exc.item_id} у списку {exc.list_id} не знайдено.",
        )

    @application.exception_handler(CategoryNotFoundError)
    async def handle_category_not_found_error(
        request: Request,
        exc: CategoryNotFoundError,
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="category_not_found",
            message=f"Категорію {exc.category_id} не знайдено у довіднику.",
            fields=[
                {
                    "field": exc.field,
                    "message": f"Категорія з id={exc.category_id} відсутня у довіднику.",
                }
            ],
        )

    @application.exception_handler(ItemValidationError)
    async def handle_item_validation_error(
        request: Request,
        exc: ItemValidationError,
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="validation_error",
            message=exc.message,
            fields=[
                {
                    "field": exc.field,
                    "message": exc.field_message,
                }
            ],
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
        invalid_input = await _unexpected_get_input_response(request, "GET /health")
        if invalid_input is not None:
            return invalid_input
        return JSONResponse(status_code=200, content={"status": "ok"})

    @application.get(
        "/categories",
        status_code=200,
        response_model=list[CategoryResponse],
    )
    async def get_categories(
        request: Request,
    ) -> list[CategoryResponse] | JSONResponse:
        invalid_input = await _unexpected_get_input_response(
            request,
            "GET /categories",
        )
        if invalid_input is not None:
            return invalid_input
        return list_categories(request.app.state.db_path)

    @application.post(
        "/lists",
        status_code=201,
        response_model=ShoppingListResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": ShoppingListCreate.model_json_schema()
                    }
                },
            }
        },
    )
    async def post_list(request: Request) -> ShoppingListResponse | JSONResponse:
        body_data, error = await _parse_json_object_body(
            request=request,
            route_label="POST /lists",
            empty_body_message="Передайте JSON-об’єкт із полем name.",
        )
        if error is not None:
            return error

        try:
            payload = ShoppingListCreate.model_validate(body_data)
        except ValidationError as exc:
            return error_response(
                status_code=422,
                code="validation_error",
                message="Некоректні вхідні дані для створення списку.",
                fields=_format_validation_fields(exc.errors(), prefix=("body",)),
            )

        return create_shopping_list(request.app.state.db_path, payload)

    @application.get(
        "/lists",
        status_code=200,
        response_model=list[ShoppingListResponse],
    )
    async def get_lists(
        request: Request,
    ) -> list[ShoppingListResponse] | JSONResponse:
        invalid_input = await _unexpected_get_input_response(
            request,
            "GET /lists",
        )
        if invalid_input is not None:
            return invalid_input
        return list_shopping_lists(request.app.state.db_path)

    @application.get(
        "/lists/{list_id}",
        status_code=200,
        response_model=ShoppingListDetailResponse,
    )
    async def get_list(
        list_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        request: Request,
        category_id: Annotated[
            str | None,
            Query(
                description=(
                    "Необов’язковий фільтр за id категорії (додатне ціле 1–10)."
                )
            ),
        ] = None,
        is_purchased: Annotated[
            str | None,
            Query(
                description=(
                    "Необов’язковий фільтр за станом придбання (рівно true або false)."
                )
            ),
        ] = None,
    ) -> ShoppingListDetailResponse | JSONResponse:
        del category_id, is_purchased
        filters, error = await _parse_get_list_filters(request)
        if error is not None:
            return error
        if filters is None or (
            filters.category_id is None and filters.is_purchased is None
        ):
            return get_shopping_list(request.app.state.db_path, list_id)
        return get_shopping_list(
            request.app.state.db_path,
            list_id,
            category_id=filters.category_id,
            is_purchased=filters.is_purchased,
        )

    @application.post(
        "/lists/{list_id}/items",
        status_code=201,
        response_model=ShoppingItemResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": ShoppingItemCreate.model_json_schema()
                    }
                },
            }
        },
    )
    async def post_list_item(
        list_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        request: Request,
    ) -> ShoppingItemResponse | JSONResponse:
        body_data, error = await _parse_json_object_body(
            request=request,
            route_label="POST /lists/{list_id}/items",
            empty_body_message=(
                "Передайте JSON-об’єкт із полями name, quantity, unit, category_id."
            ),
        )
        if error is not None:
            return error

        try:
            payload = ShoppingItemCreate.model_validate(body_data)
        except ValidationError as exc:
            return error_response(
                status_code=422,
                code="validation_error",
                message="Некоректні вхідні дані для створення позиції.",
                fields=_format_validation_fields(exc.errors(), prefix=("body",)),
            )

        return create_shopping_item(request.app.state.db_path, list_id, payload)

    @application.patch(
        "/lists/{list_id}/items/{item_id}",
        status_code=200,
        response_model=ShoppingItemResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": ShoppingItemUpdate.model_json_schema()
                    }
                },
            }
        },
    )
    async def patch_list_item(
        list_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        item_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        request: Request,
    ) -> ShoppingItemResponse | JSONResponse:
        body_data, error = await _parse_json_object_body(
            request=request,
            route_label="PATCH /lists/{list_id}/items/{item_id}",
            empty_body_message=(
                "Передайте JSON-об’єкт із полями для оновлення або порожній {}."
            ),
        )
        if error is not None:
            return error

        try:
            payload = ShoppingItemUpdate.model_validate(body_data)
        except ValidationError as exc:
            return error_response(
                status_code=422,
                code="validation_error",
                message="Оновлення відхилено без збереження змін.",
                fields=_format_validation_fields(exc.errors(), prefix=("body",)),
            )

        return update_shopping_item(
            request.app.state.db_path,
            list_id,
            item_id,
            payload,
        )

    @application.delete(
        "/lists/{list_id}/items/{item_id}",
        status_code=204,
        response_class=Response,
    )
    async def delete_list_item(
        list_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        item_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        request: Request,
    ) -> Response:
        invalid_input = await _unexpected_no_body_input_response(
            request=request,
            route_label="DELETE /lists/{list_id}/items/{item_id}",
            method="DELETE",
        )
        if invalid_input is not None:
            return invalid_input

        delete_shopping_item(
            request.app.state.db_path,
            list_id,
            item_id,
        )
        return Response(status_code=204)

    @application.patch(
        "/lists/{list_id}/items/{item_id}/purchase",
        status_code=200,
        response_model=ShoppingItemResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": ShoppingItemPurchaseUpdate.model_json_schema()
                    }
                },
            }
        },
    )
    async def patch_list_item_purchase(
        list_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        item_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        request: Request,
    ) -> ShoppingItemResponse | JSONResponse:
        body_data, error = await _parse_json_object_body(
            request=request,
            route_label="PATCH /lists/{list_id}/items/{item_id}/purchase",
            empty_body_message=(
                "Передайте JSON-об’єкт із обов’язковим boolean-полем is_purchased."
            ),
        )
        if error is not None:
            return error

        try:
            payload = ShoppingItemPurchaseUpdate.model_validate(body_data)
        except ValidationError as exc:
            return error_response(
                status_code=422,
                code="validation_error",
                message="Некоректні вхідні дані для зміни стану придбання.",
                fields=_format_validation_fields(exc.errors(), prefix=("body",)),
            )

        return update_shopping_item_purchase(
            request.app.state.db_path,
            list_id,
            item_id,
            payload,
        )

    @application.get(
        "/lists/{list_id}/statistics",
        status_code=200,
        response_model=ShoppingListStatisticsResponse,
    )
    async def get_list_statistics(
        list_id: Annotated[int, PathParam(ge=1, le=2147483647)],
        request: Request,
    ) -> ShoppingListStatisticsResponse | JSONResponse:
        invalid_input = await _unexpected_get_input_response(
            request,
            "GET /lists/{list_id}/statistics",
        )
        if invalid_input is not None:
            return invalid_input

        return get_shopping_list_statistics(request.app.state.db_path, list_id)

    return application


app = create_app()
