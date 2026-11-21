import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

UTC_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _create_list(client: TestClient, name: str = "На тиждень") -> int:
    response = client.post("/lists", json={"name": name})
    assert response.status_code == 201
    return int(response.json()["id"])


def _assert_error(
    response,
    status_code: int,
    code: str,
    field: str | None = None,
) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert set(payload.keys()) == {"detail"}
    detail = payload["detail"]
    assert set(detail.keys()) == {"code", "message", "fields"}
    assert detail["code"] == code
    assert isinstance(detail["message"], str) and detail["message"]
    assert isinstance(detail["fields"], list)
    if field is not None:
        assert any(entry["field"] == field for entry in detail["fields"])
    return detail


def _fetch_quantity_milli(db_path: Path, item_id: int) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT quantity_milli FROM shopping_items WHERE id = ?",
            (item_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_add_item_default_unpurchased(client: TestClient) -> None:
    list_id = _create_list(client)

    response = client.post(
        f"/lists/{list_id}/items",
        json={
            "name": "  Молоко 2.5%  ",
            "quantity": 2,
            "unit": "  л  ",
            "category_id": 1,
        },
    )

    assert response.status_code == 201
    item = response.json()
    assert set(item.keys()) == {
        "id",
        "list_id",
        "name",
        "quantity",
        "unit",
        "category_id",
        "is_purchased",
        "created_at",
    }
    assert isinstance(item["id"], int) and item["id"] > 0
    assert item["list_id"] == list_id
    assert item["name"] == "Молоко 2.5%"
    assert item["quantity"] == 2
    assert type(item["quantity"]) is int
    assert item["unit"] == "л"
    assert item["category_id"] == 1
    assert item["is_purchased"] is False
    assert UTC_ISO_RE.match(item["created_at"])

    # Повторні назви товарів дозволені (D-04), кожна позиція отримує окремий id.
    duplicate_response = client.post(
        f"/lists/{list_id}/items",
        json={
            "name": "Молоко 2.5%",
            "quantity": 1,
            "unit": "л",
            "category_id": 1,
        },
    )
    assert duplicate_response.status_code == 201
    duplicate_item = duplicate_response.json()
    assert duplicate_item["id"] != item["id"]
    assert duplicate_item["is_purchased"] is False

    # Граничні довжини назви (1 і 160 Unicode code points, включно з 4-байтними символами).
    for valid_name in ("А", "а" * 160, "🥛" * 160):
        name_resp = client.post(
            f"/lists/{list_id}/items",
            json={
                "name": f"  {valid_name}  ",
                "quantity": 1,
                "unit": "шт",
                "category_id": 1,
            },
        )
        assert name_resp.status_code == 201
        assert name_resp.json()["name"] == valid_name

    for invalid_name in ("", "   ", "а" * 161, "🥛" * 161):
        bad_name_resp = client.post(
            f"/lists/{list_id}/items",
            json={
                "name": invalid_name,
                "quantity": 1,
                "unit": "шт",
                "category_id": 1,
            },
        )
        _assert_error(bad_name_resp, 422, "validation_error", field="body.name")

    list_response = client.get(f"/lists/{list_id}")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 5
    assert items[0] == item
    assert items[1] == duplicate_item

    # OpenAPI-контракт: quantity має тип JSON number, а не string.
    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    post_items_spec = openapi_resp.json()["paths"]["/lists/{list_id}/items"]["post"]
    body_schema = post_items_spec["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema["properties"]["quantity"]["type"] == "number"
    assert body_schema["additionalProperties"] is False


def test_add_item_invalid_quantity_or_category(client: TestClient) -> None:
    list_id = _create_list(client)

    # Некоректні типи та значення quantity.
    for bad_quantity in (0, -1, -0.5, "2", "0.5", True, False, None):
        resp = client.post(
            f"/lists/{list_id}/items",
            json={
                "name": "Молоко",
                "quantity": bad_quantity,
                "unit": "л",
                "category_id": 1,
            },
        )
        _assert_error(resp, 422, "validation_error", field="body.quantity")

    # Нестандартні JSON-константи NaN / Infinity / -Infinity.
    for raw_quantity in ("NaN", "Infinity", "-Infinity"):
        raw_body = (
            f'{{"name": "Молоко", "quantity": {raw_quantity}, '
            f'"unit": "л", "category_id": 1}}'
        )
        resp = client.post(
            f"/lists/{list_id}/items",
            content=raw_body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        _assert_error(resp, 422, "validation_error", field="body")

    # Коректні integer category_id, відсутні у довіднику 1..10 → 422 category_not_found.
    for missing_category in (11, 99, 2147483647):
        resp = client.post(
            f"/lists/{list_id}/items",
            json={
                "name": "Молоко",
                "quantity": 2,
                "unit": "л",
                "category_id": missing_category,
            },
        )
        _assert_error(resp, 422, "category_not_found", field="body.category_id")

    # Некоректні типи та локальні межі category_id → 422 validation_error.
    for bad_category in (0, -1, 2147483648, True, False, "1", 1.0, 1.5, None):
        resp = client.post(
            f"/lists/{list_id}/items",
            json={
                "name": "Молоко",
                "quantity": 2,
                "unit": "л",
                "category_id": bad_category,
            },
        )
        _assert_error(resp, 422, "validation_error", field="body.category_id")

    # Некоректні одиниці вимірювання (включно з регістром).
    for bad_unit in ("Л", "ШТ", "УП", "kg", "мл.", "", "   ", 1, None):
        resp = client.post(
            f"/lists/{list_id}/items",
            json={
                "name": "Молоко",
                "quantity": 2,
                "unit": bad_unit,
                "category_id": 1,
            },
        )
        _assert_error(resp, 422, "validation_error", field="body.unit")

    # Відсутні обов’язкові поля.
    base_payload = {"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 1}
    for missing_field in ("name", "quantity", "unit", "category_id"):
        incomplete = {k: v for k, v in base_payload.items() if k != missing_field}
        resp = client.post(f"/lists/{list_id}/items", json=incomplete)
        _assert_error(resp, 422, "validation_error", field=f"body.{missing_field}")

    # Заборонені системні та зайві поля.
    for extra_key, extra_value in (
        ("id", 101),
        ("list_id", list_id),
        ("is_purchased", False),
        ("created_at", "2026-11-19T16:01:00Z"),
        ("unknown", "x"),
    ):
        with_extra = {**base_payload, extra_key: extra_value}
        resp = client.post(f"/lists/{list_id}/items", json=with_extra)
        _assert_error(resp, 422, "validation_error", field=f"body.{extra_key}")

    # Непідтримуваний Content-Type → 415.
    resp_415 = client.post(
        f"/lists/{list_id}/items",
        content=json.dumps(base_payload).encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    _assert_error(resp_415, 415, "unsupported_media_type")

    # Зайвий query-параметр → 422.
    resp_query = client.post(
        f"/lists/{list_id}/items?extra=1",
        json=base_payload,
    )
    _assert_error(resp_query, 422, "validation_error", field="query.extra")

    # Порожнє тіло, битий JSON і не-об’єктний JSON → 422.
    resp_empty = client.post(
        f"/lists/{list_id}/items",
        content=b"",
        headers={"Content-Type": "application/json"},
    )
    _assert_error(resp_empty, 422, "validation_error", field="body")

    resp_bad_json = client.post(
        f"/lists/{list_id}/items",
        content=b"{not-json}",
        headers={"Content-Type": "application/json"},
    )
    _assert_error(resp_bad_json, 422, "validation_error", field="body")

    resp_array = client.post(f"/lists/{list_id}/items", json=[base_payload])
    _assert_error(resp_array, 422, "validation_error", field="body")

    # Жодна некоректна позиція не була збережена.
    list_response = client.get(f"/lists/{list_id}")
    assert list_response.status_code == 200
    assert list_response.json()["items"] == []


def test_add_item_quantity_boundaries(client: TestClient, db_path: Path) -> None:
    list_id = _create_list(client)

    valid_cases = [
        ("0.001", "л", 0.001, 1),
        ("10000", "л", 10000, 10_000_000),
        ("1.230", "кг", 1.23, 1230),
        ("0.1", "кг", 0.1, 100),
        ("0.2", "г", 0.2, 200),
        ("9999.999", "мл", 9999.999, 9_999_999),
        ("1", "шт", 1, 1000),
        ("10000", "уп", 10000, 10_000_000),
    ]

    for idx, (raw_qty, unit, expected_qty, expected_milli) in enumerate(
        valid_cases, start=1
    ):
        raw_body = (
            f'{{"name": "Товар {idx}", "quantity": {raw_qty}, '
            f'"unit": "{unit}", "category_id": 1}}'
        )
        resp = client.post(
            f"/lists/{list_id}/items",
            content=raw_body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201, f"Failed for {raw_qty} {unit}: {resp.text}"
        created = resp.json()
        assert created["quantity"] == expected_qty
        assert _fetch_quantity_milli(db_path, created["id"]) == expected_milli

    invalid_cases = [
        ("0.0009", "л"),
        ("10000.001", "л"),
        ("1.2345", "л"),
        ("1.000000000000000000000000000001", "л"),
        ("10000.0000000000000001", "л"),
        ("0.5", "шт"),
        ("1.5", "уп"),
        ("0.001", "шт"),
    ]

    for raw_qty, unit in invalid_cases:
        raw_body = (
            f'{{"name": "Некоректний", "quantity": {raw_qty}, '
            f'"unit": "{unit}", "category_id": 1}}'
        )
        resp = client.post(
            f"/lists/{list_id}/items",
            content=raw_body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        _assert_error(resp, 422, "validation_error", field="body.quantity")

    list_response = client.get(f"/lists/{list_id}")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == len(valid_cases)


def test_add_item_missing_list(client: TestClient) -> None:
    # Структурно коректний запит до відсутнього списку → 404 list_not_found.
    resp_missing = client.post(
        "/lists/999/items",
        json={"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 1},
    )
    detail_missing = _assert_error(resp_missing, 404, "list_not_found")
    assert detail_missing["fields"] == []

    # BR-06: для відсутнього списку невідома категорія дає 404 (крок 2 раніше кроку 3).
    resp_missing_cat = client.post(
        "/lists/999/items",
        json={"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 99},
    )
    _assert_error(resp_missing_cat, 404, "list_not_found")

    # BR-06 (варіант A): для відсутнього списку некоректна пара quantity/unit дає 404.
    resp_missing_pair = client.post(
        "/lists/999/items",
        json={"name": "Яблука", "quantity": 0.5, "unit": "шт", "category_id": 3},
    )
    _assert_error(resp_missing_pair, 404, "list_not_found")

    resp_missing_pair_and_cat = client.post(
        "/lists/999/items",
        json={"name": "Яблука", "quantity": 0.5, "unit": "шт", "category_id": 99},
    )
    _assert_error(resp_missing_pair_and_cat, 404, "list_not_found")

    # BR-06 (крок 1 раніше кроку 2): структурні помилки дають 422 навіть для списку 999.
    for bad_payload, expected_field in (
        (
            {"name": "Молоко", "quantity": 0, "unit": "л", "category_id": 1},
            "body.quantity",
        ),
        (
            {"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 0},
            "body.category_id",
        ),
        (
            {"name": "   ", "quantity": 2, "unit": "л", "category_id": 1},
            "body.name",
        ),
        (
            {"name": "Молоко", "quantity": 2, "unit": "kg", "category_id": 1},
            "body.unit",
        ),
        (
            {
                "name": "Молоко",
                "quantity": 2,
                "unit": "л",
                "category_id": 1,
                "is_purchased": False,
            },
            "body.is_purchased",
        ),
    ):
        resp_bad = client.post("/lists/999/items", json=bad_payload)
        _assert_error(resp_bad, 422, "validation_error", field=expected_field)

    # Невалідний path list_id → 422.
    for bad_list_id in ("0", "-1", "2147483648", "abc"):
        resp_path = client.post(
            f"/lists/{bad_list_id}/items",
            json={"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 1},
        )
        _assert_error(resp_path, 422, "validation_error", field="path.list_id")

    # Непідтримуваний Content-Type для відсутнього списку → 415.
    resp_415 = client.post(
        "/lists/999/items",
        content='{"name": "Молоко", "quantity": 2, "unit": "л", "category_id": 1}'.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    _assert_error(resp_415, 415, "unsupported_media_type")
