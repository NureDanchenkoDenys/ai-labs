import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import services
from app.db import get_connection
from app.main import create_app

EXPECTED_LIST_KEYS = {"id", "name", "created_at", "items"}
EXPECTED_ITEM_KEYS = {
    "id",
    "list_id",
    "name",
    "quantity",
    "unit",
    "category_id",
    "is_purchased",
    "created_at",
}


def _assert_error_fields(
    detail: dict[str, Any],
    expected_fields: list[str],
) -> None:
    assert isinstance(detail["message"], str)
    assert detail["message"]
    assert isinstance(detail["fields"], list)
    assert [item["field"] for item in detail["fields"]] == expected_fields
    for item in detail["fields"]:
        assert set(item.keys()) == {"field", "message"}
        assert isinstance(item["message"], str)
        assert item["message"]


def _seed_lists_and_items(db_path: Path) -> None:
    with closing(get_connection(db_path)) as conn:
        with conn:
            conn.executemany(
                "INSERT INTO shopping_lists (id, name, created_at) VALUES (?, ?, ?)",
                [
                    (10, "На тиждень", "2026-11-19T16:00:00Z"),
                    (20, "На вихідні", "2026-11-19T17:00:00Z"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO shopping_items (
                    id, list_id, name, quantity_milli, unit, category_id, is_purchased, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (101, 10, "Молоко", 2000, "л", 1, 0, "2026-11-19T16:01:00Z"),
                    (102, 10, "Яблука", 1500, "кг", 3, 1, "2026-11-19T16:02:00Z"),
                    (103, 10, "Сир", 250, "г", 1, 1, "2026-11-19T16:03:00Z"),
                    (104, 10, "Кефір", 1000, "л", 1, 0, "2026-11-19T16:04:00Z"),
                    (105, 10, "Хліб", 1000, "шт", 5, 0, "2026-11-19T16:05:00Z"),
                    (201, 20, "Йогурт", 500, "мл", 1, 0, "2026-11-19T17:01:00Z"),
                    (202, 20, "Масло", 200, "г", 1, 1, "2026-11-19T17:02:00Z"),
                ],
            )


def _assert_list_detail_shape(body: dict[str, Any]) -> None:
    assert set(body.keys()) == EXPECTED_LIST_KEYS
    for item in body["items"]:
        assert set(item.keys()) == EXPECTED_ITEM_KEYS
        assert "quantity_milli" not in item
        assert type(item["id"]) is int
        assert type(item["list_id"]) is int
        assert type(item["category_id"]) is int
        assert type(item["is_purchased"]) is bool
        assert isinstance(item["name"], str)
        assert isinstance(item["unit"], str)
        assert isinstance(item["created_at"], str)


def test_filter_category_purchase_and(client: TestClient, db_path: Path) -> None:
    _seed_lists_and_items(db_path)

    expected_meta = {
        "id": 10,
        "name": "На тиждень",
        "created_at": "2026-11-19T16:00:00Z",
    }

    unfiltered = client.get("/lists/10")
    assert unfiltered.status_code == 200
    assert unfiltered.headers["content-type"].startswith("application/json")
    unfiltered_body = unfiltered.json()
    _assert_list_detail_shape(unfiltered_body)
    assert [item["id"] for item in unfiltered_body["items"]] == [
        101,
        102,
        103,
        104,
        105,
    ]

    by_category = client.get("/lists/10?category_id=1")
    assert by_category.status_code == 200
    assert by_category.headers["content-type"].startswith("application/json")
    by_category_body = by_category.json()
    _assert_list_detail_shape(by_category_body)
    assert {k: by_category_body[k] for k in expected_meta} == expected_meta
    assert [item["id"] for item in by_category_body["items"]] == [101, 103, 104]
    assert all(item["category_id"] == 1 for item in by_category_body["items"])

    leading_zero_category = client.get("/lists/10?category_id=01")
    assert leading_zero_category.status_code == 200
    assert leading_zero_category.json() == by_category_body

    by_unpurchased = client.get("/lists/10?is_purchased=false")
    assert by_unpurchased.status_code == 200
    assert by_unpurchased.headers["content-type"].startswith("application/json")
    by_unpurchased_body = by_unpurchased.json()
    _assert_list_detail_shape(by_unpurchased_body)
    assert {k: by_unpurchased_body[k] for k in expected_meta} == expected_meta
    assert [item["id"] for item in by_unpurchased_body["items"]] == [101, 104, 105]
    assert all(item["is_purchased"] is False for item in by_unpurchased_body["items"])

    by_purchased = client.get("/lists/10?is_purchased=true")
    assert by_purchased.status_code == 200
    assert by_purchased.headers["content-type"].startswith("application/json")
    by_purchased_body = by_purchased.json()
    _assert_list_detail_shape(by_purchased_body)
    assert {k: by_purchased_body[k] for k in expected_meta} == expected_meta
    assert [item["id"] for item in by_purchased_body["items"]] == [102, 103]
    assert all(item["is_purchased"] is True for item in by_purchased_body["items"])

    and_unpurchased = client.get("/lists/10?category_id=1&is_purchased=false")
    assert and_unpurchased.status_code == 200
    assert and_unpurchased.headers["content-type"].startswith("application/json")
    and_unpurchased_body = and_unpurchased.json()
    _assert_list_detail_shape(and_unpurchased_body)
    assert and_unpurchased_body == {
        **expected_meta,
        "items": [
            {
                "id": 101,
                "list_id": 10,
                "name": "Молоко",
                "quantity": 2,
                "unit": "л",
                "category_id": 1,
                "is_purchased": False,
                "created_at": "2026-11-19T16:01:00Z",
            },
            {
                "id": 104,
                "list_id": 10,
                "name": "Кефір",
                "quantity": 1,
                "unit": "л",
                "category_id": 1,
                "is_purchased": False,
                "created_at": "2026-11-19T16:04:00Z",
            },
        ],
    }

    and_purchased = client.get("/lists/10?category_id=1&is_purchased=true")
    assert and_purchased.status_code == 200
    and_purchased_body = and_purchased.json()
    _assert_list_detail_shape(and_purchased_body)
    assert and_purchased_body == {
        **expected_meta,
        "items": [
            {
                "id": 103,
                "list_id": 10,
                "name": "Сир",
                "quantity": 0.25,
                "unit": "г",
                "category_id": 1,
                "is_purchased": True,
                "created_at": "2026-11-19T16:03:00Z",
            }
        ],
    }


def test_filter_no_matches(client: TestClient, db_path: Path) -> None:
    _seed_lists_and_items(db_path)

    expected_meta = {
        "id": 10,
        "name": "На тиждень",
        "created_at": "2026-11-19T16:00:00Z",
    }

    for query in (
        "category_id=2",
        "category_id=3&is_purchased=false",
        "category_id=5&is_purchased=true",
    ):
        response = client.get(f"/lists/10?{query}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {**expected_meta, "items": []}

    empty_list_res = client.post("/lists", json={"name": "Порожній список"})
    assert empty_list_res.status_code == 201
    empty_list = empty_list_res.json()

    for query in (
        "category_id=1",
        "is_purchased=false",
        "is_purchased=true",
        "category_id=1&is_purchased=false",
    ):
        response = client.get(f"/lists/{empty_list['id']}?{query}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {**empty_list, "items": []}


@pytest.mark.parametrize("unknown_category_id", ["11", "99", "2147483647", "0011"])
def test_filter_invalid_and_repeated_query_unknown_category(
    client: TestClient,
    unknown_category_id: str,
) -> None:
    created = client.post("/lists", json={"name": "На тиждень"})
    assert created.status_code == 201
    list_id = created.json()["id"]

    response = client.get(
        f"/lists/{list_id}?category_id={unknown_category_id}&is_purchased=false"
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    detail = response.json()["detail"]
    assert detail["code"] == "category_not_found"
    _assert_error_fields(detail, ["query.category_id"])


def test_filter_invalid_and_repeated_query(client: TestClient) -> None:
    created = client.post("/lists", json={"name": "На тиждень"})
    assert created.status_code == 201
    list_id = created.json()["id"]

    unknown_category = client.get(f"/lists/{list_id}?category_id=99")
    assert unknown_category.status_code == 422
    assert unknown_category.headers["content-type"].startswith("application/json")
    unknown_category_detail = unknown_category.json()["detail"]
    assert unknown_category_detail["code"] == "category_not_found"
    _assert_error_fields(unknown_category_detail, ["query.category_id"])

    invalid_is_purchased_queries = [
        "is_purchased=unknown",
        "is_purchased=True",
        "is_purchased=False",
        "is_purchased=TRUE",
        "is_purchased=FALSE",
        "is_purchased=1",
        "is_purchased=0",
        "is_purchased=yes",
        "is_purchased=no",
        "is_purchased=null",
        "is_purchased=",
        "is_purchased",
        "is_purchased=%20true%20",
    ]
    for query in invalid_is_purchased_queries:
        response = client.get(f"/lists/{list_id}?{query}")
        assert response.status_code == 422, f"Query={query}, body={response.text}"
        detail = response.json()["detail"]
        assert detail["code"] == "validation_error"
        _assert_error_fields(detail, ["query.is_purchased"])

    invalid_category_queries = [
        "category_id=0",
        "category_id=00",
        "category_id=-1",
        "category_id=%2B1",
        "category_id=1_0",
        "category_id=2147483648",
        "category_id=99999999999999999999",
        "category_id=abc",
        "category_id=1.5",
        "category_id=true",
        "category_id=null",
        "category_id=",
        "category_id",
        "category_id=%201%20",
        "category_id=%D9%A1",
    ]
    for query in invalid_category_queries:
        response = client.get(f"/lists/{list_id}?{query}")
        assert response.status_code == 422, f"Query={query}, body={response.text}"
        detail = response.json()["detail"]
        assert detail["code"] == "validation_error"
        _assert_error_fields(detail, ["query.category_id"])

    repeated_cases = [
        ("category_id=1&category_id=2", ["query.category_id"]),
        ("category_id=1&category_id=1", ["query.category_id"]),
        ("is_purchased=true&is_purchased=false", ["query.is_purchased"]),
        ("is_purchased=false&is_purchased=false", ["query.is_purchased"]),
        (
            "category_id=1&category_id=1&is_purchased=true&is_purchased=true",
            ["query.category_id", "query.is_purchased"],
        ),
    ]
    for query, expected_fields in repeated_cases:
        response = client.get(f"/lists/{list_id}?{query}")
        assert response.status_code == 422, f"Query={query}, body={response.text}"
        detail = response.json()["detail"]
        assert detail["code"] == "validation_error"
        _assert_error_fields(detail, expected_fields)

    unknown_param_cases = [
        ("extra=1", ["query.extra"]),
        ("Category_id=1", ["query.Category_id"]),
        ("IS_PURCHASED=false", ["query.IS_PURCHASED"]),
        ("category_id=1&extra=2", ["query.extra"]),
        ("is_purchased=false&foo=bar", ["query.foo"]),
    ]
    for query, expected_fields in unknown_param_cases:
        response = client.get(f"/lists/{list_id}?{query}")
        assert response.status_code == 422, f"Query={query}, body={response.text}"
        detail = response.json()["detail"]
        assert detail["code"] == "validation_error"
        _assert_error_fields(detail, expected_fields)

    both_invalid = client.get(f"/lists/{list_id}?category_id=abc&is_purchased=1")
    assert both_invalid.status_code == 422
    both_invalid_detail = both_invalid.json()["detail"]
    assert both_invalid_detail["code"] == "validation_error"
    _assert_error_fields(
        both_invalid_detail,
        ["query.category_id", "query.is_purchased"],
    )


def test_filter_preserves_order_and_list_isolation(
    client: TestClient,
    db_path: Path,
) -> None:
    with closing(get_connection(db_path)) as conn:
        with conn:
            conn.executemany(
                "INSERT INTO shopping_lists (id, name, created_at) VALUES (?, ?, ?)",
                [
                    (10, "Основний", "2026-11-19T16:00:00Z"),
                    (20, "Інший", "2026-11-19T16:00:00Z"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO shopping_items (
                    id, list_id, name, quantity_milli, unit, category_id, is_purchased, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (105, 10, "Йогурт", 500, "мл", 1, 0, "2026-11-19T16:05:00Z"),
                    (103, 10, "Сметана", 300, "г", 1, 0, "2026-11-19T16:02:00Z"),
                    (102, 10, "Молоко", 1000, "л", 1, 0, "2026-11-19T16:02:00Z"),
                    (104, 10, "Кефір", 1000, "л", 1, 0, "2026-11-19T16:01:00Z"),
                    (106, 10, "Сир", 200, "г", 1, 1, "2026-11-19T16:00:30Z"),
                    (201, 20, "Чуже молоко", 1000, "л", 1, 0, "2026-11-19T16:00:10Z"),
                ],
            )

    list_10 = client.get("/lists/10?category_id=1&is_purchased=false")
    assert list_10.status_code == 200
    body_10 = list_10.json()
    _assert_list_detail_shape(body_10)
    assert [item["id"] for item in body_10["items"]] == [104, 102, 103, 105]
    assert all(item["list_id"] == 10 for item in body_10["items"])

    list_20 = client.get("/lists/20?category_id=1&is_purchased=false")
    assert list_20.status_code == 200
    body_20 = list_20.json()
    _assert_list_detail_shape(body_20)
    assert [item["id"] for item in body_20["items"]] == [201]
    assert all(item["list_id"] == 20 for item in body_20["items"])


def test_filter_missing_list_and_br06_priority(client: TestClient) -> None:
    for query in (
        "category_id=1",
        "is_purchased=false",
        "category_id=1&is_purchased=true",
        "category_id=99",
        "category_id=2147483647&is_purchased=false",
    ):
        response = client.get(f"/lists/999?{query}")
        assert response.status_code == 404, f"Query={query}, body={response.text}"
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["detail"] == {
            "code": "list_not_found",
            "message": "Список 999 не знайдено.",
            "fields": [],
        }

    invalid_missing_list_cases = [
        ("/lists/999?is_purchased=True", ["query.is_purchased"]),
        ("/lists/999?category_id=0", ["query.category_id"]),
        ("/lists/999?category_id=1&category_id=1", ["query.category_id"]),
        ("/lists/999?extra=1", ["query.extra"]),
        ("/lists/abc?category_id=1", ["path.list_id"]),
    ]
    for url, expected_fields in invalid_missing_list_cases:
        response = client.get(url)
        assert response.status_code == 422, f"URL={url}, body={response.text}"
        detail = response.json()["detail"]
        assert detail["code"] == "validation_error"
        _assert_error_fields(detail, expected_fields)

    missing_with_valid_query_and_body = client.request(
        "GET",
        "/lists/999?category_id=1&is_purchased=false",
        content=b'{"x": 1}',
        headers={"Content-Type": "application/json"},
    )
    assert missing_with_valid_query_and_body.status_code == 422
    detail = missing_with_valid_query_and_body.json()["detail"]
    assert detail["code"] == "validation_error"
    _assert_error_fields(detail, ["body"])


def test_filter_rejects_get_body_and_keeps_other_routes_strict(
    client: TestClient,
) -> None:
    created = client.post("/lists", json={"name": "На тиждень"})
    assert created.status_code == 201
    list_id = created.json()["id"]

    item_res = client.post(
        f"/lists/{list_id}/items",
        json={"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 1},
    )
    assert item_res.status_code == 201
    item_id = item_res.json()["id"]

    get_with_valid_filters_and_body = client.request(
        "GET",
        f"/lists/{list_id}?category_id=1&is_purchased=false",
        content=b'{"unexpected": true}',
        headers={"Content-Type": "application/json"},
    )
    assert get_with_valid_filters_and_body.status_code == 422
    detail = get_with_valid_filters_and_body.json()["detail"]
    assert detail["code"] == "validation_error"
    _assert_error_fields(detail, ["body"])

    for route in ("/health", "/categories", "/lists"):
        for query, expected_field in (
            ("category_id=1", "query.category_id"),
            ("is_purchased=false", "query.is_purchased"),
        ):
            res = client.get(f"{route}?{query}")
            assert res.status_code == 422, f"{route}?{query} -> {res.status_code}"
            res_detail = res.json()["detail"]
            assert res_detail["code"] == "validation_error"
            _assert_error_fields(res_detail, [expected_field])

    delete_with_query = client.delete(
        f"/lists/{list_id}/items/{item_id}?category_id=1"
    )
    assert delete_with_query.status_code == 422
    delete_detail = delete_with_query.json()["detail"]
    assert delete_detail["code"] == "validation_error"
    _assert_error_fields(delete_detail, ["query.category_id"])

    still_present = client.get(f"/lists/{list_id}")
    assert still_present.status_code == 200
    assert [item["id"] for item in still_present.json()["items"]] == [item_id]


def test_filter_returns_500_internal_error_on_db_failure(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken_fetch(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        raise sqlite3.OperationalError("simulated_filter_db_error")

    monkeypatch.setattr(services, "fetch_shopping_list_with_items", _broken_fetch)

    application = create_app(db_path)
    with TestClient(application, raise_server_exceptions=False) as no_raise_client:
        response = no_raise_client.get("/lists/1?category_id=1&is_purchased=false")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    detail = response.json()["detail"]
    assert detail["code"] == "internal_error"
    assert isinstance(detail["message"], str)
    assert detail["message"]
    assert detail["fields"] == []
    assert "simulated_filter_db_error" not in response.text


def test_filter_openapi_documents_optional_query_params(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200

    params = response.json()["paths"]["/lists/{list_id}"]["get"]["parameters"]
    by_name = {param["name"]: param for param in params}
    assert set(by_name.keys()) == {"list_id", "category_id", "is_purchased"}
    assert by_name["list_id"]["in"] == "path"
    assert by_name["list_id"]["required"] is True
    assert by_name["category_id"]["in"] == "query"
    assert by_name["category_id"]["required"] is False
    assert by_name["is_purchased"]["in"] == "query"
    assert by_name["is_purchased"]["required"] is False
