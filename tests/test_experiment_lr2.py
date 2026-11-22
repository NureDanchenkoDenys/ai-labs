import copy
import importlib
from collections.abc import Callable
from typing import Any

import pytest

PredicateFn = Callable[..., bool]


def _load_variant(variant: str) -> PredicateFn:
    module_name = f"experiments.lr2.{variant}_impl"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            pytest.skip(f"Реалізація {variant} ({module_name}) ще не створена.")
        raise

    fn = getattr(module, "matches_item_filter", None)
    if not callable(fn):
        pytest.fail(
            f"У модулі {module_name} не знайдено функцію matches_item_filter."
        )
    return fn


def _make_item(
    *,
    item_id: int = 101,
    list_id: int = 10,
    name: str = "Молоко",
    quantity: int | float = 2,
    unit: str = "л",
    category_id: int = 1,
    is_purchased: bool = False,
    created_at: str = "2026-11-19T16:01:00Z",
) -> dict[str, Any]:
    return {
        "id": item_id,
        "list_id": list_id,
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "category_id": category_id,
        "is_purchased": is_purchased,
        "created_at": created_at,
    }


@pytest.fixture(params=["manual", "ai"])
def impl(request: pytest.FixtureRequest) -> PredicateFn:
    return _load_variant(str(request.param))


def test_no_filters_returns_true(impl: PredicateFn) -> None:
    unpurchased = _make_item(category_id=1, is_purchased=False)
    purchased = _make_item(item_id=102, name="Яблука", category_id=3, is_purchased=True)

    for item in (unpurchased, purchased):
        res_default = impl(item)
        assert type(res_default) is bool
        assert res_default is True

        res_explicit_none = impl(item, category_id=None, is_purchased=None)
        assert type(res_explicit_none) is bool
        assert res_explicit_none is True


def test_category_filter_match_and_mismatch(impl: PredicateFn) -> None:
    item = _make_item(category_id=5, is_purchased=False)

    res_match = impl(item, category_id=5)
    assert type(res_match) is bool
    assert res_match is True

    res_match_explicit_none = impl(item, category_id=5, is_purchased=None)
    assert type(res_match_explicit_none) is bool
    assert res_match_explicit_none is True

    res_mismatch = impl(item, category_id=6)
    assert type(res_mismatch) is bool
    assert res_mismatch is False


def test_category_boundaries_one_and_ten(impl: PredicateFn) -> None:
    item_first = _make_item(category_id=1, is_purchased=False)
    item_last = _make_item(item_id=102, name="Шоколад", category_id=10, is_purchased=True)

    assert impl(item_first, category_id=1) is True
    assert impl(item_first, category_id=10) is False
    assert impl(item_last, category_id=10) is True
    assert impl(item_last, category_id=1) is False


def test_purchase_filter_match_and_mismatch(impl: PredicateFn) -> None:
    unpurchased = _make_item(category_id=2, is_purchased=False)
    purchased = _make_item(item_id=102, category_id=2, is_purchased=True)

    res_unpurchased_match = impl(unpurchased, is_purchased=False)
    assert type(res_unpurchased_match) is bool
    assert res_unpurchased_match is True

    res_unpurchased_mismatch = impl(unpurchased, is_purchased=True)
    assert type(res_unpurchased_mismatch) is bool
    assert res_unpurchased_mismatch is False

    res_purchased_match = impl(purchased, is_purchased=True)
    assert type(res_purchased_match) is bool
    assert res_purchased_match is True

    res_purchased_mismatch = impl(purchased, is_purchased=False)
    assert type(res_purchased_mismatch) is bool
    assert res_purchased_mismatch is False

    assert impl(purchased, category_id=None, is_purchased=True) is True


@pytest.mark.parametrize(
    ("item_cat", "item_status", "filter_cat", "filter_status", "expected"),
    [
        (1, False, 1, False, True),
        (1, False, 1, True, False),
        (1, False, 2, False, False),
        (1, False, 2, True, False),
        (1, True, 1, True, True),
        (1, True, 1, False, False),
        (1, True, 10, True, False),
        (1, True, 10, False, False),
    ],
    ids=[
        "both_match_false",
        "only_cat_match_false",
        "only_status_match_false",
        "none_match_false",
        "both_match_true",
        "only_cat_match_true",
        "only_status_match_true",
        "none_match_true",
    ],
)
def test_and_combinations(
    impl: PredicateFn,
    item_cat: int,
    item_status: bool,
    filter_cat: int,
    filter_status: bool,
    expected: bool,
) -> None:
    item = _make_item(category_id=item_cat, is_purchased=item_status)
    result = impl(item, category_id=filter_cat, is_purchased=filter_status)
    assert type(result) is bool
    assert result is expected


@pytest.mark.parametrize(
    "bad_category_id",
    [
        0,
        -1,
        11,
        999,
        True,
        False,
        "1",
        "10",
        1.0,
        1.5,
        [],
        {},
    ],
    ids=[
        "zero",
        "negative",
        "eleven",
        "large",
        "bool_true",
        "bool_false",
        "str_one",
        "str_ten",
        "float_one",
        "float_frac",
        "list_val",
        "dict_val",
    ],
)
def test_invalid_category_id_rejected(
    impl: PredicateFn,
    bad_category_id: Any,
) -> None:
    # Використовуємо category_id=1, щоб перевірити відсутність змішування True == 1.
    item = _make_item(category_id=1, is_purchased=False)
    with pytest.raises(ValueError):
        impl(item, category_id=bad_category_id)


@pytest.mark.parametrize(
    "bad_is_purchased",
    [
        0,
        1,
        -1,
        "true",
        "false",
        "True",
        "False",
        "unknown",
        1.0,
        [],
        {},
    ],
    ids=[
        "int_zero",
        "int_one",
        "int_neg",
        "str_true",
        "str_false",
        "str_cap_true",
        "str_cap_false",
        "str_unknown",
        "float_one",
        "list_val",
        "dict_val",
    ],
)
def test_invalid_is_purchased_rejected(
    impl: PredicateFn,
    bad_is_purchased: Any,
) -> None:
    # Перевіряємо на обох станах, щоб виключити змішування 0 == False і 1 == True.
    for status in (False, True):
        item = _make_item(category_id=1, is_purchased=status)
        with pytest.raises(ValueError):
            impl(item, is_purchased=bad_is_purchased)


@pytest.mark.parametrize(
    ("filter_cat", "filter_status"),
    [
        (1, "false"),
        (99, False),
        (0, 1),
        (True, False),
        (1, 0),
    ],
    ids=[
        "valid_cat_bad_status",
        "bad_cat_valid_status",
        "both_bad",
        "bool_cat_valid_status",
        "valid_cat_int_status",
    ],
)
def test_mixed_valid_and_invalid_filters_rejected(
    impl: PredicateFn,
    filter_cat: Any,
    filter_status: Any,
) -> None:
    item = _make_item(category_id=1, is_purchased=False)
    with pytest.raises(ValueError):
        impl(item, category_id=filter_cat, is_purchased=filter_status)


def test_keyword_only_filter_arguments(impl: PredicateFn) -> None:
    item = _make_item(category_id=1, is_purchased=False)
    with pytest.raises(TypeError):
        impl(item, 1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        impl(item, 1, False)  # type: ignore[misc]


def test_input_item_not_mutated(impl: PredicateFn) -> None:
    item = _make_item(category_id=4, is_purchased=True)
    snapshot = copy.deepcopy(item)

    assert impl(item) is True
    assert item == snapshot

    assert impl(item, category_id=4, is_purchased=True) is True
    assert item == snapshot

    assert impl(item, category_id=2, is_purchased=False) is False
    assert item == snapshot

    with pytest.raises(ValueError):
        impl(item, category_id=True)
    assert item == snapshot

    with pytest.raises(ValueError):
        impl(item, is_purchased=1)
    assert item == snapshot
