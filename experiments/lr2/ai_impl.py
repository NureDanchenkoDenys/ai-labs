"""AI-generated implementation of item filtering for LR2 experiment."""

from collections.abc import Mapping
from typing import Any

MIN_CATEGORY_ID = 1
MAX_CATEGORY_ID = 10


def matches_item_filter(
    item: Mapping[str, Any],
    *,
    category_id: int | None = None,
    is_purchased: bool | None = None,
) -> bool:
    """Return True if a shopping item matches the provided filter criteria.

    Args:
        item: Valid ShoppingItem dictionary matching the contract fields.
        category_id: Optional category filter; exact int in 1..10 inclusive.
        is_purchased: Optional purchase status filter; exact bool.

    Returns:
        Exact bool indicating whether the item satisfies all provided filters.

    Raises:
        ValueError: If category_id or is_purchased has an invalid type or value.
    """
    if category_id is not None and (
        type(category_id) is not int
        or not (MIN_CATEGORY_ID <= category_id <= MAX_CATEGORY_ID)
    ):
        raise ValueError(
            f"category_id must be an int between {MIN_CATEGORY_ID} and "
            f"{MAX_CATEGORY_ID} inclusive, or None"
        )

    if is_purchased is not None and type(is_purchased) is not bool:
        raise ValueError("is_purchased must be a bool or None")

    if category_id is not None:
        item_category_id = item["category_id"]
        if (
            type(item_category_id) is not int
            or item_category_id != category_id
        ):
            return False

    if is_purchased is not None:
        item_is_purchased = item["is_purchased"]
        if (
            type(item_is_purchased) is not bool
            or item_is_purchased is not is_purchased
        ):
            return False

    return True
