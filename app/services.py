from datetime import datetime, timezone
from pathlib import Path

from app.db import (
    CATEGORIES,
    category_exists_in_tx,
    delete_shopping_item_in_tx,
    fetch_categories,
    fetch_shopping_item_in_tx,
    fetch_shopping_list_with_items,
    fetch_shopping_lists,
    insert_shopping_item,
    insert_shopping_list,
    shopping_list_exists,
    shopping_list_exists_in_tx,
    update_shopping_item_in_tx,
    update_shopping_item_purchase_in_tx,
    write_transaction,
)
from app.schemas import (
    INTEGER_ONLY_UNITS,
    CategoryResponse,
    ShoppingItemCreate,
    ShoppingItemPurchaseUpdate,
    ShoppingItemResponse,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListDetailResponse,
    ShoppingListResponse,
)


class ListNotFoundError(Exception):
    def __init__(self, list_id: int) -> None:
        self.list_id = list_id
        super().__init__(f"Список {list_id} не знайдено.")


class ItemNotFoundError(Exception):
    def __init__(self, list_id: int, item_id: int) -> None:
        self.list_id = list_id
        self.item_id = item_id
        super().__init__(f"Позицію {item_id} у списку {list_id} не знайдено.")


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


def validate_quantity_unit_pair(
    quantity_milli: int,
    unit: str,
    field: str = "body.quantity",
) -> None:
    if unit in INTEGER_ONLY_UNITS and quantity_milli % 1000 != 0:
        raise ItemValidationError(
            message="Кількість не відповідає обраній одиниці вимірювання.",
            field=field,
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


def update_shopping_item(
    db_path: str | Path,
    list_id: int,
    item_id: int,
    payload: ShoppingItemUpdate,
) -> ShoppingItemResponse:
    fields_set = payload.model_fields_set

    with write_transaction(db_path) as conn:
        if not shopping_list_exists_in_tx(conn, list_id):
            raise ListNotFoundError(list_id)

        found = fetch_shopping_item_in_tx(conn, list_id=list_id, item_id=item_id)
        if found is None:
            raise ItemNotFoundError(list_id=list_id, item_id=item_id)

        current_item, current_quantity_milli = found

        final_name = (
            payload.name if "name" in fields_set else str(current_item["name"])
        )
        final_quantity_milli = (
            payload.quantity_milli
            if "quantity" in fields_set and payload.quantity_milli is not None
            else current_quantity_milli
        )
        final_unit = (
            payload.unit if "unit" in fields_set else str(current_item["unit"])
        )
        final_category_id = (
            payload.category_id
            if "category_id" in fields_set
            else int(current_item["category_id"])
        )

        pair_error_field = (
            "body.unit"
            if "unit" in fields_set and "quantity" not in fields_set
            else "body.quantity"
        )
        validate_quantity_unit_pair(
            quantity_milli=final_quantity_milli,
            unit=final_unit,
            field=pair_error_field,
        )

        if "category_id" in fields_set and not category_exists_in_tx(
            conn, final_category_id
        ):
            raise CategoryNotFoundError(final_category_id)

        if not fields_set or (
            final_name == current_item["name"]
            and final_quantity_milli == current_quantity_milli
            and final_unit == current_item["unit"]
            and final_category_id == current_item["category_id"]
        ):
            return ShoppingItemResponse.model_validate(current_item)

        updated = update_shopping_item_in_tx(
            conn=conn,
            list_id=list_id,
            item_id=item_id,
            name=final_name,
            quantity_milli=final_quantity_milli,
            unit=final_unit,
            category_id=final_category_id,
        )

    return ShoppingItemResponse.model_validate(updated)


def delete_shopping_item(
    db_path: str | Path,
    list_id: int,
    item_id: int,
) -> None:
    with write_transaction(db_path) as conn:
        if not shopping_list_exists_in_tx(conn, list_id):
            raise ListNotFoundError(list_id)

        deleted = delete_shopping_item_in_tx(
            conn=conn,
            list_id=list_id,
            item_id=item_id,
        )
        if not deleted:
            raise ItemNotFoundError(list_id=list_id, item_id=item_id)


def update_shopping_item_purchase(
    db_path: str | Path,
    list_id: int,
    item_id: int,
    payload: ShoppingItemPurchaseUpdate,
) -> ShoppingItemResponse:
    with write_transaction(db_path) as conn:
        if not shopping_list_exists_in_tx(conn, list_id):
            raise ListNotFoundError(list_id)

        found = fetch_shopping_item_in_tx(conn, list_id=list_id, item_id=item_id)
        if found is None:
            raise ItemNotFoundError(list_id=list_id, item_id=item_id)

        current_item, _ = found
        if current_item["is_purchased"] is payload.is_purchased:
            return ShoppingItemResponse.model_validate(current_item)

        updated = update_shopping_item_purchase_in_tx(
            conn=conn,
            list_id=list_id,
            item_id=item_id,
            is_purchased=payload.is_purchased,
        )

    return ShoppingItemResponse.model_validate(updated)
