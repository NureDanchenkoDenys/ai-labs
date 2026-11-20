from datetime import datetime, timezone
from pathlib import Path

from app.db import CATEGORIES, fetch_categories, insert_shopping_list
from app.schemas import CategoryResponse, ShoppingListCreate, ShoppingListResponse


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
