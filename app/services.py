from datetime import datetime, timezone
from pathlib import Path

from app.db import (
    CATEGORIES,
    fetch_categories,
    fetch_shopping_list_with_items,
    fetch_shopping_lists,
    insert_shopping_item,
    insert_shopping_list,
    shopping_list_exists,
)
from app.schemas import (
    INTEGER_ONLY_UNITS,
    CategoryResponse,
    ShoppingItemCreate,
    ShoppingItemResponse,
    ShoppingListCreate,
    ShoppingListDetailResponse,
    ShoppingListResponse,
)


class ListNotFoundError(Exception):
    def __init__(self, list_id: int) -> None:
        self.list_id = list_id
        super().__init__(f"Список {list_id} не знайдено.")


class CategoryNotFoundError(Exception):
    def __init__(
        self,
        category_id: int,
        field: str = "body.category_id",
    ) -> None:
        self.category_id = category_id
        self.field = field
        super().__init__(f"Категорію {category_id} не знайдено у довіднику.")


class ItemValidationError(Exception):
    def __init__(
        self,
        message: str,
        field: str,
        field_message: str,
    ) -> None:
        self.message = message
        self.field = field
        self.field_message = field_message
        super().__init__(message)


def list_categories(db_path: str | Path) -> list[CategoryResponse]:
    records = fetch_categories(db_path=db_path)
    actual_catalog = tuple(
        (record["id"], record["name"], record["description"]) for record in records
    )
    if actual_catalog != CATEGORIES:
        raise RuntimeError(
            "Довідник категорій у БД не відповідає нормативному переліку."
        )
    return [CategoryResponse.model_validate(record) for record in records]


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def create_shopping_list(
    db_path: str | Path,
    payload: ShoppingListCreate,
) -> ShoppingListResponse:
    created_at = utc_now_iso()
    record = insert_shopping_list(
        db_path=db_path,
        name=payload.name,
        created_at=created_at,
    )
    return ShoppingListResponse.model_validate(record)


def list_shopping_lists(db_path: str | Path) -> list[ShoppingListResponse]:
    records = fetch_shopping_lists(db_path=db_path)
    return [ShoppingListResponse.model_validate(record) for record in records]


def get_shopping_list(
    db_path: str | Path,
    list_id: int,
) -> ShoppingListDetailResponse:
    record = fetch_shopping_list_with_items(db_path=db_path, list_id=list_id)
    if record is None:
        raise ListNotFoundError(list_id)
    return ShoppingListDetailResponse.model_validate(record)


def validate_quantity_unit_pair(quantity_milli: int, unit: str) -> None:
    if unit in INTEGER_ONLY_UNITS and quantity_milli % 1000 != 0:
        raise ItemValidationError(
            message="Кількість не відповідає обраній одиниці вимірювання.",
            field="body.quantity",
            field_message="Для одиниць шт і уп кількість має бути цілим числом від 1 до 10000.",
        )


def create_shopping_item(
    db_path: str | Path,
    list_id: int,
    payload: ShoppingItemCreate,
) -> ShoppingItemResponse:
    if not shopping_list_exists(db_path=db_path, list_id=list_id):
        raise ListNotFoundError(list_id)

    quantity_milli = payload.quantity_milli
    validate_quantity_unit_pair(quantity_milli=quantity_milli, unit=payload.unit)

    created_at = utc_now_iso()
    status, record = insert_shopping_item(
        db_path=db_path,
        list_id=list_id,
        name=payload.name,
        quantity_milli=quantity_milli,
        unit=payload.unit,
        category_id=payload.category_id,
        created_at=created_at,
    )
    if status == "list_not_found":
        raise ListNotFoundError(list_id)
    if status == "category_not_found":
        raise CategoryNotFoundError(payload.category_id)
    if record is None:
        raise RuntimeError("Створену позицію не знайдено після збереження.")
    return ShoppingItemResponse.model_validate(record)
