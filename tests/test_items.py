import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

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


def _create_item(
    client: TestClient,
    list_id: int,
    name: str = "Молоко",
    quantity: int | float = 2,
    unit: str = "л",
    category_id: int = 1,
) -> dict:
    response = client.post(
        f"/lists/{list_id}/items",
        json={
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "category_id": category_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def _get_item(client: TestClient, list_id: int, item_id: int) -> dict:
    response = client.get(f"/lists/{list_id}")
    assert response.status_code == 200
    for item in response.json()["items"]:
        if item["id"] == item_id:
            return item
    raise AssertionError(f"Позицію {item_id} не знайдено у списку {list_id}.")


def test_patch_item_preserves_omitted_fields(
    client: TestClient,
    db_path: Path,
) -> None:
    list_id = _create_list(client)
    original = _create_item(
        client,
        list_id,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_id = int(original["id"])

    # AC-04-01: PATCH лише name (зі strip) зберігає решту полів.
    resp_name = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "  Молоко безлактозне  "},
    )
    assert resp_name.status_code == 200
    updated_name = resp_name.json()
    assert set(updated_name.keys()) == {
        "id",
        "list_id",
        "name",
        "quantity",
        "unit",
        "category_id",
        "is_purchased",
        "created_at",
    }
    assert updated_name == {
        **original,
        "name": "Молоко безлактозне",
    }
    assert type(updated_name["quantity"]) is int

    # PATCH лише quantity (з хвостовим нулем 1.230 → 1.23, quantity_milli=1230).
    resp_qty = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        content=b'{"quantity": 1.230}',
        headers={"Content-Type": "application/json"},
    )
    assert resp_qty.status_code == 200
    updated_qty = resp_qty.json()
    assert updated_qty == {
        **updated_name,
        "quantity": 1.23,
    }
    assert _fetch_quantity_milli(db_path, item_id) == 1230

    # PATCH лише unit (зі strip).
    resp_unit = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"unit": "  мл  "},
    )
    assert resp_unit.status_code == 200
    updated_unit = resp_unit.json()
    assert updated_unit == {
        **updated_qty,
        "unit": "мл",
    }

    # PATCH лише category_id.
    resp_cat = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"category_id": 7},
    )
    assert resp_cat.status_code == 200
    updated_cat = resp_cat.json()
    assert updated_cat == {
        **updated_unit,
        "category_id": 7,
    }

    # Ідемпотентний PATCH з тими самими значеннями → 200 без змін.
    resp_same = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={
            "name": "Молоко безлактозне",
            "quantity": 1.23,
            "unit": "мл",
            "category_id": 7,
        },
    )
    assert resp_same.status_code == 200
    assert resp_same.json() == updated_cat

    # Граничні довжини name (1 і 160 Unicode code points, включно з 4-байтними символами).
    current = updated_cat
    for valid_name in ("А", "а" * 160, "🥛" * 160):
        resp_valid_name = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json={"name": f"  {valid_name}  "},
        )
        assert resp_valid_name.status_code == 200
        current = resp_valid_name.json()
        assert current["name"] == valid_name

    for invalid_name in ("", "   ", "а" * 161, "🥛" * 161):
        resp_bad_name = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json={"name": invalid_name},
        )
        _assert_error(resp_bad_name, 422, "validation_error", field="body.name")
    assert _get_item(client, list_id, item_id) == current

    # Граничні значення quantity (0.001, 10000) та неприпустимі значення.
    for raw_qty, expected_qty, expected_milli in (
        ("0.001", 0.001, 1),
        ("10000", 10000, 10_000_000),
    ):
        resp_bound = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            content=f'{{"quantity": {raw_qty}}}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert resp_bound.status_code == 200
        current = resp_bound.json()
        assert current["quantity"] == expected_qty
        assert _fetch_quantity_milli(db_path, item_id) == expected_milli

    for bad_raw_qty in (
        "0.0009",
        "10000.001",
        "1.2345",
        "1.000000000000000000000000000001",
        "10000.0000000000000001",
    ):
        resp_bad_qty = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            content=f'{{"quantity": {bad_raw_qty}}}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        _assert_error(resp_bad_qty, 422, "validation_error", field="body.quantity")
    assert _get_item(client, list_id, item_id) == current

    # Редагування позиції у стані is_purchased=true дозволено (D-06/BR-02), стан зберігається.
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE shopping_items SET is_purchased = 1 WHERE id = ?",
                (item_id,),
            )

    resp_purchased_edit = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "Молоко куплене"},
    )
    assert resp_purchased_edit.status_code == 200
    edited_purchased = resp_purchased_edit.json()
    assert edited_purchased["name"] == "Молоко куплене"
    assert edited_purchased["is_purchased"] is True
    assert edited_purchased["created_at"] == original["created_at"]
    assert _get_item(client, list_id, item_id) == edited_purchased

    # OpenAPI-схема PATCH: необов’язкові поля без дозволу null, без додаткових полів.
    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    patch_spec = openapi_resp.json()["paths"]["/lists/{list_id}/items/{item_id}"]["patch"]
    body_schema = patch_spec["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema["additionalProperties"] is False
    assert not body_schema.get("required")
    props = body_schema["properties"]
    assert set(props.keys()) == {"name", "quantity", "unit", "category_id"}
    assert props["name"]["type"] == "string"
    assert props["quantity"]["type"] == "number"
    assert props["unit"]["type"] == "string"
    assert props["unit"]["enum"] == ["шт", "кг", "г", "л", "мл", "уп"]
    assert props["category_id"]["type"] == "integer"
    for prop_schema in props.values():
        assert "anyOf" not in prop_schema
        assert "default" not in prop_schema
        assert prop_schema.get("type") != "null"


def test_patch_item_atomic_rejection(
    client: TestClient,
    db_path: Path,
) -> None:
    list_id = _create_list(client)
    original = _create_item(
        client,
        list_id,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_id = int(original["id"])

    # AC-04-02: коректне name + quantity=0 → 422; жодне поле не змінюється.
    resp_qty = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "Нова назва", "quantity": 0},
    )
    _assert_error(resp_qty, 422, "validation_error", field="body.quantity")
    assert _get_item(client, list_id, item_id) == original

    # Коректне name + невідома category_id=99 → 422 category_not_found; name без змін.
    resp_cat = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "Нова назва", "category_id": 99},
    )
    _assert_error(resp_cat, 422, "category_not_found", field="body.category_id")
    assert _get_item(client, list_id, item_id) == original

    # Коректне name + некоректний unit або точність quantity або системне поле → 422 без змін.
    for mixed_payload, expected_field in (
        ({"name": "Нова назва", "unit": "kg"}, "body.unit"),
        ({"name": "Нова назва", "quantity": 1.2345}, "body.quantity"),
        ({"name": "Нова назва", "is_purchased": True}, "body.is_purchased"),
    ):
        resp_mixed = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json=mixed_payload,
        )
        _assert_error(resp_mixed, 422, "validation_error", field=expected_field)
        assert _get_item(client, list_id, item_id) == original

    # Аварійна помилка БД під час UPDATE → 500 internal_error та повний rollback без витоку деталей.
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TRIGGER fail_after_item_update
                AFTER UPDATE ON shopping_items
                BEGIN
                    SELECT RAISE(ABORT, 'simulated_db_failure');
                END
                """
            )
    try:
        with TestClient(
            create_app(db_path),
            raise_server_exceptions=False,
        ) as no_raise_client:
            resp_500 = no_raise_client.patch(
                f"/lists/{list_id}/items/{item_id}",
                json={"name": "Змінена назва", "quantity": 5},
            )
        detail_500 = _assert_error(resp_500, 500, "internal_error")
        assert detail_500["fields"] == []
        assert "simulated_db_failure" not in detail_500["message"]
    finally:
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute("DROP TRIGGER IF EXISTS fail_after_item_update")

    assert _get_item(client, list_id, item_id) == original


def test_patch_item_null_extra_and_empty(client: TestClient) -> None:
    list_id = _create_list(client)
    original = _create_item(
        client,
        list_id,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_id = int(original["id"])

    # AC-04-03: null у будь-якому полі → 422 validation_error без змін.
    for field_name in ("name", "quantity", "unit", "category_id"):
        resp_null = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json={field_name: None},
        )
        _assert_error(resp_null, 422, "validation_error", field=f"body.{field_name}")

    resp_mixed_null = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "Нова назва", "unit": None},
    )
    _assert_error(resp_mixed_null, 422, "validation_error", field="body.unit")

    # Заборонені системні, невідомі та регістро-некоректні поля → 422 без змін.
    for forbidden_key, forbidden_value in (
        ("id", item_id),
        ("list_id", list_id),
        ("is_purchased", True),
        ("created_at", "2026-11-19T16:01:00Z"),
        ("unknown", "x"),
        ("Name", "Молоко 2"),
    ):
        resp_extra = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json={forbidden_key: forbidden_value},
        )
        _assert_error(resp_extra, 422, "validation_error", field=f"body.{forbidden_key}")

    # Некоректні типи та локальні межі полів.
    for bad_payload, expected_field in (
        ({"name": 123}, "body.name"),
        ({"quantity": "2"}, "body.quantity"),
        ({"quantity": True}, "body.quantity"),
        ({"quantity": False}, "body.quantity"),
        ({"quantity": -1}, "body.quantity"),
        ({"unit": "Л"}, "body.unit"),
        ({"unit": 1}, "body.unit"),
        ({"category_id": "1"}, "body.category_id"),
        ({"category_id": True}, "body.category_id"),
        ({"category_id": False}, "body.category_id"),
        ({"category_id": 1.0}, "body.category_id"),
        ({"category_id": 0}, "body.category_id"),
        ({"category_id": -1}, "body.category_id"),
        ({"category_id": 2147483648}, "body.category_id"),
    ):
        resp_bad = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json=bad_payload,
        )
        _assert_error(resp_bad, 422, "validation_error", field=expected_field)

    # NaN / Infinity / -Infinity → 422.
    for raw_constant in ("NaN", "Infinity", "-Infinity"):
        resp_const = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            content=f'{{"quantity": {raw_constant}}}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        _assert_error(resp_const, 422, "validation_error", field="body")

    # Відсутній body, битий JSON та не-об’єктний JSON → 422.
    for raw_body in (b"", b"{not-json}", b"[]", b"null", b'"text"', b"123"):
        resp_body = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            content=raw_body,
            headers={"Content-Type": "application/json"},
        )
        _assert_error(resp_body, 422, "validation_error", field="body")

    # Зайвий query-параметр → 422.
    resp_query = client.patch(
        f"/lists/{list_id}/items/{item_id}?extra=1",
        json={},
    )
    _assert_error(resp_query, 422, "validation_error", field="query.extra")

    # Непідтримуваний Content-Type → 415.
    resp_415 = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        content='{"name": "Нова"}'.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    detail_415 = _assert_error(resp_415, 415, "unsupported_media_type")
    assert detail_415["fields"] == []

    # Порожній JSON-об’єкт {} → 200 без змін.
    resp_empty_obj = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={},
    )
    assert resp_empty_obj.status_code == 200
    assert resp_empty_obj.json() == original
    assert _get_item(client, list_id, item_id) == original


def test_patch_item_wrong_list(client: TestClient) -> None:
    list_a = _create_list(client, name="Список А")
    list_b = _create_list(client, name="Список Б")
    item_b = _create_item(
        client,
        list_b,
        name="Хліб",
        quantity=1,
        unit="шт",
        category_id=5,
    )
    item_b_id = int(item_b["id"])

    # AC-04-04: позиція належить іншому списку → 404 item_not_found без змін.
    for payload in (
        {"name": "Перехоплена назва"},
        {},
        {"category_id": 99},
        {"quantity": 0.5, "unit": "шт"},
        {"category_id": 99, "quantity": 0.5, "unit": "шт"},
    ):
        resp_wrong = client.patch(
            f"/lists/{list_a}/items/{item_b_id}",
            json=payload,
        )
        detail = _assert_error(resp_wrong, 404, "item_not_found")
        assert detail["fields"] == []

    # Відсутня позиція у наявному списку → 404 item_not_found.
    for payload in ({"name": "Нова"}, {}):
        resp_missing_item = client.patch(
            f"/lists/{list_a}/items/999999",
            json=payload,
        )
        detail = _assert_error(resp_missing_item, 404, "item_not_found")
        assert detail["fields"] == []

    # Відсутній список → 404 list_not_found (BR-06: крок 2 раніше кроку 3).
    for payload in (
        {"name": "Нова"},
        {},
        {"category_id": 99},
        {"quantity": 0.5, "unit": "шт"},
        {"category_id": 99, "quantity": 0.5, "unit": "шт"},
    ):
        resp_missing_list = client.patch(
            f"/lists/999/items/{item_b_id}",
            json=payload,
        )
        detail = _assert_error(resp_missing_list, 404, "list_not_found")
        assert detail["fields"] == []

    # BR-06: крок 1 (структурні помилки, path, 415) раніше кроку 2 (404).
    for target_url in (
        f"/lists/999/items/{item_b_id}",
        f"/lists/{list_a}/items/{item_b_id}",
    ):
        for bad_payload, expected_field in (
            ({"quantity": 0}, "body.quantity"),
            ({"name": None}, "body.name"),
            ({"is_purchased": True}, "body.is_purchased"),
        ):
            resp_struct = client.patch(target_url, json=bad_payload)
            _assert_error(resp_struct, 422, "validation_error", field=expected_field)

        resp_query = client.patch(f"{target_url}?extra=1", json={})
        _assert_error(resp_query, 422, "validation_error", field="query.extra")

        resp_415 = client.patch(
            target_url,
            content='{"name": "Нова"}'.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
        )
        _assert_error(resp_415, 415, "unsupported_media_type")

    for bad_id in ("0", "-1", "2147483648", "abc"):
        resp_bad_list = client.patch(f"/lists/{bad_id}/items/{item_b_id}", json={})
        _assert_error(resp_bad_list, 422, "validation_error", field="path.list_id")

        resp_bad_item = client.patch(f"/lists/{list_a}/items/{bad_id}", json={})
        _assert_error(resp_bad_item, 422, "validation_error", field="path.item_id")

    # Чужа позиція у списку Б не зазнала жодних змін.
    assert _get_item(client, list_b, item_b_id) == item_b


def test_patch_quantity_unit_pair(
    client: TestClient,
    db_path: Path,
) -> None:
    list_id = _create_list(client)
    original = _create_item(
        client,
        list_id,
        name="Яблука",
        quantity=0.5,
        unit="кг",
        category_id=3,
    )
    item_id = int(original["id"])

    # AC-04-05: quantity=0.5 кг, PATCH лише unit=шт або unit=уп → 422 (field=body.unit) без змін.
    for integer_unit in ("шт", "уп"):
        resp_only_unit = client.patch(
            f"/lists/{list_id}/items/{item_id}",
            json={"unit": integer_unit},
        )
        _assert_error(resp_only_unit, 422, "validation_error", field="body.unit")
        assert _get_item(client, list_id, item_id) == original

    # Змішаний PATCH з коректним name і несумісним unit → 422 без збереження name.
    resp_mixed_unit = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "Яблука зелені", "unit": "шт"},
    )
    _assert_error(resp_mixed_unit, 422, "validation_error", field="body.unit")
    assert _get_item(client, list_id, item_id) == original

    # Крок 3 BR-06 (узгоджено з API-06): несумісна пара перевіряється раніше за category_id.
    resp_unit_and_cat = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"unit": "шт", "category_id": 99},
    )
    _assert_error(resp_unit_and_cat, 422, "validation_error", field="body.unit")
    assert _get_item(client, list_id, item_id) == original

    resp_both_and_cat = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"quantity": 0.5, "unit": "шт", "category_id": 99},
    )
    _assert_error(resp_both_and_cat, 422, "validation_error", field="body.quantity")
    assert _get_item(client, list_id, item_id) == original

    # Сумісна зміна лише unit на іншу дробову одиницю (кг → л) → 200.
    resp_to_liter = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"unit": "л"},
    )
    assert resp_to_liter.status_code == 200
    assert resp_to_liter.json()["unit"] == "л"
    assert resp_to_liter.json()["quantity"] == 0.5
    assert _fetch_quantity_milli(db_path, item_id) == 500

    # Одночасний PATCH quantity=2 і unit=шт → 200.
    resp_to_pcs = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"quantity": 2, "unit": "шт"},
    )
    assert resp_to_pcs.status_code == 200
    pcs_state = resp_to_pcs.json()
    assert pcs_state["quantity"] == 2
    assert type(pcs_state["quantity"]) is int
    assert pcs_state["unit"] == "шт"
    assert _fetch_quantity_milli(db_path, item_id) == 2000

    # Зворотний випадок: quantity=2 шт, PATCH лише дробового quantity → 422 (field=body.quantity).
    resp_frac_qty = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"quantity": 0.5},
    )
    _assert_error(resp_frac_qty, 422, "validation_error", field="body.quantity")
    assert _get_item(client, list_id, item_id) == pcs_state

    resp_mixed_frac = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"name": "Груші", "quantity": 1.5},
    )
    _assert_error(resp_mixed_frac, 422, "validation_error", field="body.quantity")
    assert _get_item(client, list_id, item_id) == pcs_state

    # Одночасний перехід назад на дробову одиницю (quantity=0.5, unit=кг) → 200.
    resp_back_kg = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"quantity": 0.5, "unit": "кг"},
    )
    assert resp_back_kg.status_code == 200
    assert resp_back_kg.json()["quantity"] == 0.5
    assert resp_back_kg.json()["unit"] == "кг"
    assert _fetch_quantity_milli(db_path, item_id) == 500

    # Ціла кількість у кг → зміна лише unit на уп допустима → 200.
    resp_int_kg = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"quantity": 3},
    )
    assert resp_int_kg.status_code == 200
    resp_to_pack = client.patch(
        f"/lists/{list_id}/items/{item_id}",
        json={"unit": "уп"},
    )
    assert resp_to_pack.status_code == 200
    assert resp_to_pack.json()["quantity"] == 3
    assert resp_to_pack.json()["unit"] == "уп"
    assert _fetch_quantity_milli(db_path, item_id) == 3000


def _count_list_items_in_db(
    db_path: Path,
    list_id: int,
    is_purchased: int | None = None,
) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        if is_purchased is None:
            row = conn.execute(
                "SELECT COUNT(*) FROM shopping_items WHERE list_id = ?",
                (list_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM shopping_items WHERE list_id = ? AND is_purchased = ?",
                (list_id, is_purchased),
            ).fetchone()
    assert row is not None
    return int(row[0])


def test_delete_item_updates_statistics(
    client: TestClient,
    db_path: Path,
) -> None:
    # Примітка: HTTP-перевірку GET /lists/{list_id}/statistics (API-10) буде додано у зрізі E.
    # На цьому етапі перевіряємо AC-05-01 через 204 без тіла, GET /lists/{list_id}
    # та зменшення кількості записів у тимчасовій SQLite-БД.
    list_a = _create_list(client, name="На тиждень")
    list_b = _create_list(client, name="Інший список")

    item_unpurchased = _create_item(
        client,
        list_a,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_duplicate = _create_item(
        client,
        list_a,
        name="Молоко",
        quantity=1,
        unit="л",
        category_id=1,
    )
    item_purchased = _create_item(
        client,
        list_a,
        name="Яблука",
        quantity=1,
        unit="кг",
        category_id=3,
    )
    item_other_list = _create_item(
        client,
        list_b,
        name="Хліб",
        quantity=1,
        unit="шт",
        category_id=5,
    )

    # API-09 ще не реалізований: виставляємо is_purchased = 1 безпосередньо в ізольованій БД tmp_path.
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE shopping_items SET is_purchased = 1 WHERE id = ?",
                (item_purchased["id"],),
            )
    expected_purchased = {**item_purchased, "is_purchased": True}

    assert _count_list_items_in_db(db_path, list_a) == 3
    assert _count_list_items_in_db(db_path, list_a, is_purchased=0) == 2
    assert _count_list_items_in_db(db_path, list_a, is_purchased=1) == 1
    assert _count_list_items_in_db(db_path, list_b) == 1

    # Видалення непридбаної позиції → 204 без тіла і без application/json Content-Type.
    resp_del_unpurchased = client.delete(
        f"/lists/{list_a}/items/{item_unpurchased['id']}"
    )
    assert resp_del_unpurchased.status_code == 204
    assert resp_del_unpurchased.content == b""
    assert resp_del_unpurchased.text == ""
    assert resp_del_unpurchased.headers.get("content-type") is None

    # Дублікат і решта позицій у list_a та позиція в list_b не постраждали.
    resp_list_a = client.get(f"/lists/{list_a}")
    assert resp_list_a.status_code == 200
    assert resp_list_a.json()["items"] == [item_duplicate, expected_purchased]
    assert _count_list_items_in_db(db_path, list_a) == 2
    assert _count_list_items_in_db(db_path, list_a, is_purchased=0) == 1
    assert _count_list_items_in_db(db_path, list_a, is_purchased=1) == 1

    resp_list_b = client.get(f"/lists/{list_b}")
    assert resp_list_b.status_code == 200
    assert resp_list_b.json()["items"] == [item_other_list]
    assert _count_list_items_in_db(db_path, list_b) == 1

    # Видалення вже придбаної позиції дозволено (D-06/BR-02) → 204 без тіла.
    resp_del_purchased = client.delete(
        f"/lists/{list_a}/items/{item_purchased['id']}"
    )
    assert resp_del_purchased.status_code == 204
    assert resp_del_purchased.content == b""
    assert resp_del_purchased.headers.get("content-type") is None

    resp_list_a_after_purchased = client.get(f"/lists/{list_a}")
    assert resp_list_a_after_purchased.status_code == 200
    assert resp_list_a_after_purchased.json()["items"] == [item_duplicate]
    assert _count_list_items_in_db(db_path, list_a) == 1
    assert _count_list_items_in_db(db_path, list_a, is_purchased=0) == 1
    assert _count_list_items_in_db(db_path, list_a, is_purchased=1) == 0

    # Видалення останньої позиції залишає порожній коректний список, не зачіпаючи інші списки.
    resp_del_last = client.delete(f"/lists/{list_a}/items/{item_duplicate['id']}")
    assert resp_del_last.status_code == 204
    assert resp_del_last.content == b""
    assert resp_del_last.headers.get("content-type") is None

    resp_list_a_empty = client.get(f"/lists/{list_a}")
    assert resp_list_a_empty.status_code == 200
    assert resp_list_a_empty.json()["items"] == []
    assert _count_list_items_in_db(db_path, list_a) == 0

    resp_lists = client.get("/lists")
    assert resp_lists.status_code == 200
    assert [entry["id"] for entry in resp_lists.json()] == [list_a, list_b]
    assert _get_item(client, list_b, int(item_other_list["id"])) == item_other_list
    assert _count_list_items_in_db(db_path, list_b) == 1

    # OpenAPI-контракт: 204 без тіла відповіді й без requestBody.
    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    delete_spec = openapi_resp.json()["paths"]["/lists/{list_id}/items/{item_id}"][
        "delete"
    ]
    assert "requestBody" not in delete_spec
    assert "204" in delete_spec["responses"]
    assert "content" not in delete_spec["responses"]["204"]


def test_delete_missing_or_wrong_list_item(
    client: TestClient,
    db_path: Path,
) -> None:
    list_a = _create_list(client, name="Список А")
    list_b = _create_list(client, name="Список Б")
    item_a = _create_item(
        client,
        list_a,
        name="Молоко",
        quantity=2,
        unit="л",
        category_id=1,
    )
    item_b = _create_item(
        client,
        list_b,
        name="Хліб",
        quantity=1,
        unit="шт",
        category_id=5,
    )
    item_a_id = int(item_a["id"])
    item_b_id = int(item_b["id"])

    # AC-05-02: повторний DELETE після успішного видалення → 404 item_not_found.
    resp_first = client.delete(f"/lists/{list_a}/items/{item_a_id}")
    assert resp_first.status_code == 204
    assert resp_first.content == b""

    resp_repeat = client.delete(f"/lists/{list_a}/items/{item_a_id}")
    detail_repeat = _assert_error(resp_repeat, 404, "item_not_found")
    assert detail_repeat["fields"] == []

    # Відсутня позиція в наявному списку → 404 item_not_found.
    resp_missing_item = client.delete(f"/lists/{list_a}/items/999999")
    detail_missing_item = _assert_error(resp_missing_item, 404, "item_not_found")
    assert detail_missing_item["fields"] == []

    # AC-05-02 / BR-01: позиція іншого списку → 404 item_not_found; чужа позиція не змінюється.
    resp_wrong_list = client.delete(f"/lists/{list_a}/items/{item_b_id}")
    detail_wrong_list = _assert_error(resp_wrong_list, 404, "item_not_found")
    assert detail_wrong_list["fields"] == []
    assert _get_item(client, list_b, item_b_id) == item_b

    # Відсутній список → 404 list_not_found (навіть якщо item_id існує в іншому списку).
    for target_item_id in (item_b_id, 999999):
        resp_missing_list = client.delete(f"/lists/999/items/{target_item_id}")
        detail_missing_list = _assert_error(resp_missing_list, 404, "list_not_found")
        assert detail_missing_list["fields"] == []
    assert _get_item(client, list_b, item_b_id) == item_b

    # BR-06 крок 1 раніше кроку 2: невалідні path-параметри → 422 validation_error.
    for bad_id in ("0", "-1", "2147483648", "abc"):
        resp_bad_list = client.delete(f"/lists/{bad_id}/items/{item_b_id}")
        _assert_error(resp_bad_list, 422, "validation_error", field="path.list_id")

        resp_bad_item = client.delete(f"/lists/{list_b}/items/{bad_id}")
        _assert_error(resp_bad_item, 422, "validation_error", field="path.item_id")

        resp_bad_item_missing_list = client.delete(f"/lists/999/items/{bad_id}")
        _assert_error(
            resp_bad_item_missing_list,
            422,
            "validation_error",
            field="path.item_id",
        )

    # BR-06 крок 1 раніше кроку 2: зайві query-параметри та будь-яке непорожнє тіло → 422.
    for target_url in (
        f"/lists/{list_b}/items/{item_b_id}",
        f"/lists/{list_a}/items/{item_b_id}",
        f"/lists/999/items/{item_b_id}",
    ):
        resp_query = client.delete(f"{target_url}?extra=1")
        _assert_error(resp_query, 422, "validation_error", field="query.extra")

        resp_repeated_query = client.delete(f"{target_url}?a=1&a=2")
        _assert_error(resp_repeated_query, 422, "validation_error", field="query.a")

        for raw_body, headers in (
            (b"{}", {"Content-Type": "application/json"}),
            (b'{"confirm": true}', {"Content-Type": "application/json"}),
            (b"delete", {"Content-Type": "text/plain"}),
            (b"raw-body", {}),
        ):
            resp_body = client.request(
                "DELETE",
                target_url,
                content=raw_body,
                headers=headers,
            )
            _assert_error(resp_body, 422, "validation_error", field="body")

    assert _get_item(client, list_b, item_b_id) == item_b

    # Аварійна помилка БД під час DELETE → 500 internal_error та повний rollback без витоку деталей.
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TRIGGER fail_after_item_delete
                AFTER DELETE ON shopping_items
                BEGIN
                    SELECT RAISE(ABORT, 'simulated_delete_failure');
                END
                """
            )
    try:
        with TestClient(
            create_app(db_path),
            raise_server_exceptions=False,
        ) as no_raise_client:
            resp_500 = no_raise_client.delete(f"/lists/{list_b}/items/{item_b_id}")
        detail_500 = _assert_error(resp_500, 500, "internal_error")
        assert detail_500["fields"] == []
        assert "simulated_delete_failure" not in detail_500["message"]
    finally:
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute("DROP TRIGGER IF EXISTS fail_after_item_delete")

    # Після rollback позиція залишилася в списку Б без змін.
    assert _get_item(client, list_b, item_b_id) == item_b
    assert _count_list_items_in_db(db_path, list_b) == 1
