import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.db import CATEGORIES
from app.main import create_app


def _assert_error(
    response: Any,
    status_code: int,
    code: str,
    field: str | None = None,
) -> dict[str, Any]:
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) == {"detail"}
    detail = body["detail"]
    assert set(detail.keys()) == {"code", "message", "fields"}
    assert detail["code"] == code
    assert isinstance(detail["message"], str) and detail["message"]
    assert isinstance(detail["fields"], list)
    if field is not None:
        assert any(
            entry["field"] == field and isinstance(entry["message"], str) and entry["message"]
            for entry in detail["fields"]
        )
    return detail


def _create_list(client: TestClient, name: str = "На тиждень") -> int:
    resp = client.post("/lists", json={"name": name})
    assert resp.status_code == 201
    return int(resp.json()["id"])


def _create_item(
    client: TestClient,
    list_id: int,
    name: str,
    quantity: int | float,
    unit: str,
    category_id: int,
) -> dict[str, Any]:
    resp = client.post(
        f"/lists/{list_id}/items",
        json={
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "category_id": category_id,
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _set_purchased(
    client: TestClient,
    list_id: int,
    item_id: int,
    is_purchased: bool,
) -> dict[str, Any]:
    resp = client.patch(
        f"/lists/{list_id}/items/{item_id}/purchase",
        json={"is_purchased": is_purchased},
    )
    assert resp.status_code == 200
    return resp.json()


def _assert_statistics_response(
    response: Any,
    expected_list_id: int,
    expected_category_counts: dict[int, tuple[int, int, int]],
) -> dict[str, Any]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()

    assert set(data.keys()) == {
        "list_id",
        "total_items",
        "purchased_items",
        "unpurchased_items",
        "categories",
    }
    assert type(data["list_id"]) is int
    assert data["list_id"] == expected_list_id
    for key in ("total_items", "purchased_items", "unpurchased_items"):
        assert type(data[key]) is int
        assert data[key] >= 0

    categories = data["categories"]
    assert isinstance(categories, list)
    assert len(categories) == len(CATEGORIES) == 10

    sum_total = 0
    sum_purchased = 0
    sum_unpurchased = 0
    for cat_entry, (expected_id, expected_name, _) in zip(
        categories,
        CATEGORIES,
        strict=True,
    ):
        assert set(cat_entry.keys()) == {
            "category_id",
            "category_name",
            "total_items",
            "purchased_items",
            "unpurchased_items",
        }
        assert type(cat_entry["category_id"]) is int
        assert cat_entry["category_id"] == expected_id
        assert cat_entry["category_name"] == expected_name
        for key in ("total_items", "purchased_items", "unpurchased_items"):
            assert type(cat_entry[key]) is int
            assert cat_entry[key] >= 0

        expected_cat = expected_category_counts.get(expected_id, (0, 0, 0))
        assert (
            cat_entry["total_items"],
            cat_entry["purchased_items"],
            cat_entry["unpurchased_items"],
        ) == expected_cat
        assert (
            cat_entry["total_items"]
            == cat_entry["purchased_items"] + cat_entry["unpurchased_items"]
        )
        sum_total += cat_entry["total_items"]
        sum_purchased += cat_entry["purchased_items"]
        sum_unpurchased += cat_entry["unpurchased_items"]

    # Інваріанти BR-05.
    assert data["total_items"] == data["purchased_items"] + data["unpurchased_items"]
    assert data["total_items"] == sum_total
    assert data["purchased_items"] == sum_purchased
    assert data["unpurchased_items"] == sum_unpurchased
    return data


def test_statistics_counts_positions_per_category(client: TestClient) -> None:
    list_a = _create_list(client, name="На тиждень")
    list_b = _create_list(client, name="Інший список")

    # Позиції в іншому списку не повинні впливати на статистику list_a.
    other_item = _create_item(
        client,
        list_b,
        name="Пральний порошок",
        quantity=3,
        unit="кг",
        category_id=9,
    )
    _set_purchased(client, list_b, int(other_item["id"]), True)

    # AC-08-01 / D-01: Молоко 2 л (непридбане, кат. 1) + Яблука 1 кг (придбані, кат. 3).
    # Рахуються позиції (2), а не сума quantity (2 л + 1 кг).
    _create_item(
        client,
        list_a,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_apples = _create_item(
        client,
        list_a,
        name="Яблука",
        quantity=1,
        unit="кг",
        category_id=3,
    )
    _set_purchased(client, list_a, int(item_apples["id"]), True)

    resp_base = client.get(f"/lists/{list_a}/statistics")
    stats_base = _assert_statistics_response(
        resp_base,
        expected_list_id=list_a,
        expected_category_counts={1: (1, 0, 1), 3: (1, 1, 0)},
    )
    assert (
        stats_base["total_items"],
        stats_base["purchased_items"],
        stats_base["unpurchased_items"],
    ) == (2, 1, 1)

    # Змішані стани, кілька позицій і повторні назви в одній категорії (D-04), дробові/великі кількості.
    _create_item(
        client,
        list_a,
        name="Молоко",
        quantity=0.5,
        unit="л",
        category_id=1,
    )
    item_cheese = _create_item(
        client,
        list_a,
        name="Сир",
        quantity=10000,
        unit="г",
        category_id=1,
    )
    _set_purchased(client, list_a, int(item_cheese["id"]), True)
    _create_item(
        client,
        list_a,
        name="Хліб",
        quantity=3,
        unit="шт",
        category_id=5,
    )

    resp_mixed = client.get(f"/lists/{list_a}/statistics")
    stats_mixed = _assert_statistics_response(
        resp_mixed,
        expected_list_id=list_a,
        expected_category_counts={
            1: (3, 1, 2),
            3: (1, 1, 0),
            5: (1, 0, 1),
        },
    )
    assert (
        stats_mixed["total_items"],
        stats_mixed["purchased_items"],
        stats_mixed["unpurchased_items"],
    ) == (5, 2, 3)

    # Ізоляція: статистика іншого списку містить лише його власну позицію.
    resp_other = client.get(f"/lists/{list_b}/statistics")
    _assert_statistics_response(
        resp_other,
        expected_list_id=list_b,
        expected_category_counts={9: (1, 1, 0)},
    )

    # Крайові стани: усі позиції непридбані, а потім усі позиції придбані.
    list_edge = _create_list(client, name="Крайні стани")
    edge_item_1 = _create_item(
        client,
        list_edge,
        name="Помідори",
        quantity=0.75,
        unit="кг",
        category_id=2,
    )
    edge_item_2 = _create_item(
        client,
        list_edge,
        name="Шоколад",
        quantity=2,
        unit="шт",
        category_id=10,
    )

    resp_all_unpurchased = client.get(f"/lists/{list_edge}/statistics")
    stats_all_unpurchased = _assert_statistics_response(
        resp_all_unpurchased,
        expected_list_id=list_edge,
        expected_category_counts={2: (1, 0, 1), 10: (1, 0, 1)},
    )
    assert (
        stats_all_unpurchased["total_items"],
        stats_all_unpurchased["purchased_items"],
        stats_all_unpurchased["unpurchased_items"],
    ) == (2, 0, 2)

    _set_purchased(client, list_edge, int(edge_item_1["id"]), True)
    _set_purchased(client, list_edge, int(edge_item_2["id"]), True)

    resp_all_purchased = client.get(f"/lists/{list_edge}/statistics")
    stats_all_purchased = _assert_statistics_response(
        resp_all_purchased,
        expected_list_id=list_edge,
        expected_category_counts={2: (1, 1, 0), 10: (1, 1, 0)},
    )
    assert (
        stats_all_purchased["total_items"],
        stats_all_purchased["purchased_items"],
        stats_all_purchased["unpurchased_items"],
    ) == (2, 2, 0)

    # OpenAPI-схема API-10: GET без query/requestBody і з точною схемою відповіді 200.
    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    openapi = openapi_resp.json()
    stats_op = openapi["paths"]["/lists/{list_id}/statistics"]["get"]
    assert "requestBody" not in stats_op
    params = stats_op.get("parameters", [])
    assert [(p["in"], p["name"]) for p in params] == [("path", "list_id")]

    schemas = openapi["components"]["schemas"]
    list_stats_schema = schemas["ShoppingListStatisticsResponse"]
    assert list_stats_schema["additionalProperties"] is False
    assert set(list_stats_schema["properties"].keys()) == {
        "list_id",
        "total_items",
        "purchased_items",
        "unpurchased_items",
        "categories",
    }
    cat_stats_schema = schemas["CategoryStatisticsResponse"]
    assert cat_stats_schema["additionalProperties"] is False
    assert set(cat_stats_schema["properties"].keys()) == {
        "category_id",
        "category_name",
        "total_items",
        "purchased_items",
        "unpurchased_items",
    }


def test_statistics_empty_list_all_categories(client: TestClient) -> None:
    empty_list_id = _create_list(client, name="Порожній список")
    other_list_id = _create_list(client, name="Наповнений список")

    item_other = _create_item(
        client,
        other_list_id,
        name="Гречка",
        quantity=1,
        unit="кг",
        category_id=6,
    )
    _set_purchased(client, other_list_id, int(item_other["id"]), True)

    # Звіряємо порядок і назви категорій із API-02 GET /categories.
    resp_categories = client.get("/categories")
    assert resp_categories.status_code == 200
    catalog = resp_categories.json()
    assert len(catalog) == 10

    # AC-08-02: порожній список → 200, три нулі і 10 категорій із нулями.
    resp_stats = client.get(f"/lists/{empty_list_id}/statistics")
    stats = _assert_statistics_response(
        resp_stats,
        expected_list_id=empty_list_id,
        expected_category_counts={},
    )
    assert (
        stats["total_items"],
        stats["purchased_items"],
        stats["unpurchased_items"],
    ) == (0, 0, 0)
    assert [
        (entry["category_id"], entry["category_name"])
        for entry in stats["categories"]
    ] == [(entry["id"], entry["name"]) for entry in catalog]


def test_statistics_after_changes_and_filters(client: TestClient) -> None:
    list_id = _create_list(client, name="Динамічний список")

    # Початково порожній список.
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={},
    )

    # 1. POST нових позицій оновлює загальні й категорійні лічильники.
    item_milk = _create_item(
        client,
        list_id,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_cucumbers = _create_item(
        client,
        list_id,
        name="Огірки",
        quantity=0.5,
        unit="кг",
        category_id=2,
    )
    item_apples = _create_item(
        client,
        list_id,
        name="Яблука",
        quantity=1,
        unit="кг",
        category_id=3,
    )
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            1: (1, 0, 1),
            2: (1, 0, 1),
            3: (1, 0, 1),
        },
    )

    # 2. Фільтри API-05 (включно з порожнім збігом) не впливають на статистику (D-08 / BR-05).
    for filtered_url, expected_len in (
        (f"/lists/{list_id}?category_id=1", 1),
        (f"/lists/{list_id}?is_purchased=true", 0),
        (f"/lists/{list_id}?category_id=1&is_purchased=false", 1),
    ):
        resp_filtered = client.get(filtered_url)
        assert resp_filtered.status_code == 200
        assert len(resp_filtered.json()["items"]) == expected_len
        _assert_statistics_response(
            client.get(f"/lists/{list_id}/statistics"),
            expected_list_id=list_id,
            expected_category_counts={
                1: (1, 0, 1),
                2: (1, 0, 1),
                3: (1, 0, 1),
            },
        )

    # 3. PATCH category_id переносить позицію між категоріями зі збереженням загальних підсумків.
    resp_patch_cat = client.patch(
        f"/lists/{list_id}/items/{item_milk['id']}",
        json={"category_id": 7},
    )
    assert resp_patch_cat.status_code == 200
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 0, 1),
            7: (1, 0, 1),
        },
    )

    # PATCH quantity/name без зміни категорії не змінює лічильники позицій.
    resp_patch_qty = client.patch(
        f"/lists/{list_id}/items/{item_milk['id']}",
        json={"name": "Вівсяний напій", "quantity": 5},
    )
    assert resp_patch_qty.status_code == 200
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 0, 1),
            7: (1, 0, 1),
        },
    )

    # 4. PATCH purchase: false -> true, повторне true -> true, перенесення категорії придбаної, true -> false.
    _set_purchased(client, list_id, int(item_milk["id"]), True)
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 0, 1),
            7: (1, 1, 0),
        },
    )

    _set_purchased(client, list_id, int(item_milk["id"]), True)
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 0, 1),
            7: (1, 1, 0),
        },
    )

    resp_move_purchased = client.patch(
        f"/lists/{list_id}/items/{item_milk['id']}",
        json={"category_id": 8},
    )
    assert resp_move_purchased.status_code == 200
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 0, 1),
            8: (1, 1, 0),
        },
    )

    _set_purchased(client, list_id, int(item_milk["id"]), False)
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 0, 1),
            8: (1, 0, 1),
        },
    )

    # Позначаємо яблука придбаними й знову перевіряємо незалежність після фільтрації.
    _set_purchased(client, list_id, int(item_apples["id"]), True)
    resp_filter_after_purchase = client.get(
        f"/lists/{list_id}?category_id=3&is_purchased=true"
    )
    assert resp_filter_after_purchase.status_code == 200
    assert len(resp_filter_after_purchase.json()["items"]) == 1
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            2: (1, 0, 1),
            3: (1, 1, 0),
            8: (1, 0, 1),
        },
    )

    # 5. DELETE непридбаної, придбаної та останньої позицій оновлює статистику до нулів.
    resp_del_unpurchased = client.delete(
        f"/lists/{list_id}/items/{item_cucumbers['id']}"
    )
    assert resp_del_unpurchased.status_code == 204
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            3: (1, 1, 0),
            8: (1, 0, 1),
        },
    )

    resp_del_purchased = client.delete(f"/lists/{list_id}/items/{item_apples['id']}")
    assert resp_del_purchased.status_code == 204
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={
            8: (1, 0, 1),
        },
    )

    resp_del_last = client.delete(f"/lists/{list_id}/items/{item_milk['id']}")
    assert resp_del_last.status_code == 204
    _assert_statistics_response(
        client.get(f"/lists/{list_id}/statistics"),
        expected_list_id=list_id,
        expected_category_counts={},
    )


def test_statistics_missing_list(client: TestClient, db_path: Path) -> None:
    list_id = _create_list(client, name="Наявний список")

    # AC-08-04: неіснуючий список → 404 list_not_found, а не нульовий підсумок.
    resp_missing = client.get("/lists/999/statistics")
    detail_missing = _assert_error(resp_missing, 404, "list_not_found")
    assert detail_missing["fields"] == []
    assert "999" in detail_missing["message"]

    # BR-06 крок 1 раніше кроку 2: невалідний path.list_id → 422 validation_error.
    for bad_id in ("0", "-1", "2147483648", "abc"):
        resp_bad_path = client.get(f"/lists/{bad_id}/statistics")
        _assert_error(resp_bad_path, 422, "validation_error", field="path.list_id")

    # BR-06 крок 1 раніше кроку 2: зайві/фільтрувальні/повторені query та будь-яке тіло → 422
    # як для наявного списку, так і для відсутнього списку 999.
    for target_list_id in (list_id, 999):
        base_url = f"/lists/{target_list_id}/statistics"
        for query_suffix, expected_field in (
            ("?category_id=1", "query.category_id"),
            ("?is_purchased=false", "query.is_purchased"),
            ("?category_id=1&is_purchased=false", "query.category_id"),
            ("?extra=1", "query.extra"),
            ("?a=1&a=2", "query.a"),
        ):
            resp_query = client.get(f"{base_url}{query_suffix}")
            _assert_error(resp_query, 422, "validation_error", field=expected_field)

        for raw_body, headers in (
            (b"{}", {"Content-Type": "application/json"}),
            (b'{"category_id": 1}', {"Content-Type": "application/json"}),
            (b"stats", {"Content-Type": "text/plain"}),
            (b"raw-body", {}),
        ):
            resp_body = client.request(
                "GET",
                base_url,
                content=raw_body,
                headers=headers,
            )
            _assert_error(resp_body, 422, "validation_error", field="body")

    # Пошкоджений довідник категорій у БД → 500 internal_error без витоку деталей.
    corrupted_db_path = db_path.parent / "corrupted_categories_stats.db"
    with TestClient(
        create_app(corrupted_db_path),
        raise_server_exceptions=False,
    ) as corrupted_client:
        corrupted_list_id = _create_list(corrupted_client, name="Тест довідника")
        with closing(sqlite3.connect(corrupted_db_path)) as conn:
            with conn:
                conn.execute("DELETE FROM categories WHERE id = 10")

        resp_corrupted = corrupted_client.get(f"/lists/{corrupted_list_id}/statistics")
        detail_corrupted = _assert_error(resp_corrupted, 500, "internal_error")
        assert detail_corrupted["fields"] == []
        assert "нормативному" not in detail_corrupted["message"]

    # Аварійна помилка БД під час читання статистики → 500 internal_error без витоку деталей.
    broken_db_path = db_path.parent / "broken_stats.db"
    with TestClient(
        create_app(broken_db_path),
        raise_server_exceptions=False,
    ) as broken_client:
        broken_list_id = _create_list(broken_client, name="Тест збою БД")
        with closing(sqlite3.connect(broken_db_path)) as conn:
            with conn:
                conn.execute("DROP TABLE shopping_items")

        resp_500 = broken_client.get(f"/lists/{broken_list_id}/statistics")
        detail_500 = _assert_error(resp_500, 500, "internal_error")
        assert detail_500["fields"] == []
        assert "shopping_items" not in detail_500["message"]
        assert "no such table" not in detail_500["message"].lower()
