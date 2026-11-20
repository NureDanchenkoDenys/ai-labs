from datetime import datetime, timezone
from pathlib import Path

from app.db import insert_shopping_list
from app.schemas import ShoppingListCreate, ShoppingListResponse


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
