from datetime import datetime, timezone
from pathlib import Path

from app.db import (
    CATEGORIES,
    fetch_categories,
    fetch_shopping_list_with_items,
    fetch_shopping_lists,
    insert_shopping_list,
)
from app.schemas import (
    CategoryResponse,
    ShoppingListCreate,
    ShoppingListDetailResponse,
    ShoppingListResponse,
)


class ListNotFoundError(Exception):
    def __init__(self, list_id: int) -> None:
        self.list_id = list_id
        super().__init__(f"Список {list_id} не знайдено.")


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
