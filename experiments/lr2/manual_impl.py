def matches_item_filter(
    item: dict,
    *,
    category_id: int | None = None,
    is_purchased: bool | None = None,
) -> bool:
    if category_id is not None:
        if type(category_id) is not int or not 1 <= category_id <= 10:
            raise ValueError("Invalid category_id")

    if is_purchased is not None:
        if type(is_purchased) is not bool:
            raise ValueError("Invalid is_purchased")

    category_matches = category_id is None or (
        type(item["category_id"]) is int
        and item["category_id"] == category_id
    )

    purchase_matches = is_purchased is None or (
        type(item["is_purchased"]) is bool
        and item["is_purchased"] is is_purchased
    )

    return category_matches and purchase_matches