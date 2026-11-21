import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import services
from app.db import get_connection
from app.main import create_app


def _fetch_all_lists(db_path: Path) -> list[dict[str, int | str]]:
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM shopping_lists ORDER BY id ASC"
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_create_list_trimmed(client: TestClient, db_path: Path) -> None:
    response = client.post("/lists", json={"name": "  На   Тиждень  "})

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert set(body.keys()) == {"id", "name", "created_at"}
    assert type(body["id"]) is int
    assert 1 <= body["id"] <= 2147483647
    assert body["name"] == "На   Тиждень"
    assert isinstance(body["created_at"], str)
    assert body["created_at"].endswith("Z")

    parsed_created_at = datetime.fromisoformat(body["created_at"])
    assert parsed_created_at.tzinfo == timezone.utc

    persisted = _fetch_all_lists(db_path)
    assert persisted == [body]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": ""},
        {"name": "   \t\n  "},
    ],
)
def test_create_list_required_name(
    client: TestClient,
    db_path: Path,
    payload: dict[str, Any],
) -> None:
    response = client.post("/lists", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["message"]
    assert any(item["field"] == "body.name" for item in detail["fields"])
    assert _fetch_all_lists(db_path) == []


def test_create_list_name_boundaries(client: TestClient, db_path: Path) -> None:
    min_response = client.post("/lists", json={"name": "  Ї  "})
    assert min_response.status_code == 201
    assert min_response.json()["name"] == "Ї"

    max_name = "ї" * 120
    max_response = client.post("/lists", json={"name": f"  {max_name}  "})
    assert max_response.status_code == 201
    assert max_response.json()["name"] == max_name
    assert len(max_response.json()["name"]) == 120

    too_long_response = client.post("/lists", json={"name": "ї" * 121})
    assert too_long_response.status_code == 422
    detail = too_long_response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["message"]
    assert any(item["field"] == "body.name" for item in detail["fields"])

    persisted = _fetch_all_lists(db_path)
    assert len(persisted) == 2
    assert [row["name"] for row in persisted] == ["Ї", max_name]


@pytest.mark.parametrize(
    ("payload", "expected_field"),
    [
        ({"name": "Список", "id": 10}, "body.id"),
        (
            {"name": "Список", "created_at": "2026-11-19T16:00:00Z"},
            "body.created_at",
        ),
        ({"name": "Список", "extra": "value"}, "body.extra"),
        ({"Name": "Список"}, "body.Name"),
    ],
)
def test_create_list_rejects_extra_and_system_fields(
    client: TestClient,
    db_path: Path,
    payload: dict[str, Any],
    expected_field: str,
) -> None:
    response = client.post("/lists", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["message"]
    assert any(item["field"] == expected_field for item in detail["fields"])
    assert _fetch_all_lists(db_path) == []


@pytest.mark.parametrize("invalid_name", [123, True, ["На тиждень"], {"a": "b"}])
def test_create_list_rejects_non_string_name(
    client: TestClient,
    db_path: Path,
    invalid_name: Any,
) -> None:
    response = client.post("/lists", json={"name": invalid_name})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert any(item["field"] == "body.name" for item in detail["fields"])
    assert _fetch_all_lists(db_path) == []


@pytest.mark.parametrize(
    "raw_body",
    [
        b"",
        b"{invalid",
        b"[]",
        b'"text"',
        b"123",
        b"null",
    ],
)
def test_create_list_rejects_missing_or_non_object_json_body(
    client: TestClient,
    db_path: Path,
    raw_body: bytes,
) -> None:
    response = client.post(
        "/lists",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["message"]
    assert any(item["field"] == "body" for item in detail["fields"])
    assert _fetch_all_lists(db_path) == []


def test_create_list_rejects_query_params_and_unsupported_media_type(
    client: TestClient,
    db_path: Path,
) -> None:
    query_response = client.post(
        "/lists",
        params={"extra": "1"},
        json={"name": "На тиждень"},
    )
    assert query_response.status_code == 422
    query_detail = query_response.json()["detail"]
    assert query_detail["code"] == "validation_error"
    assert query_detail["fields"] == [
        {
            "field": "query.extra",
            "message": "Маршрут не приймає query-параметрів.",
        }
    ]

    plain_response = client.post(
        "/lists",
        content=b'{"name": "\xd0\x9d\xd0\xb0 \xd1\x82\xd0\xb8\xd0\xb6\xd0\xb4\xd0\xb5\xd0\xbd\xd1\x8c"}',
        headers={"Content-Type": "text/plain"},
    )
    assert plain_response.status_code == 415
    plain_detail = plain_response.json()["detail"]
    assert plain_detail["code"] == "unsupported_media_type"
    assert plain_detail["message"]
    assert plain_detail["fields"] == []

    no_ct_response = client.post(
        "/lists",
        content=b'{"name": "A"}',
    )
    assert no_ct_response.status_code == 415
    assert no_ct_response.json()["detail"]["code"] == "unsupported_media_type"

    assert _fetch_all_lists(db_path) == []


def test_create_list_allows_charset_and_duplicate_names_isolated_from_working_db(
    client: TestClient,
    db_path: Path,
) -> None:
    working_db = Path("database.db")
    before_hash = _file_sha256(working_db)

    first = client.post(
        "/lists",
        content='{"name": "На тиждень"}'.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    second = client.post("/lists", json={"name": "На тиждень"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["name"] == second.json()["name"] == "На тиждень"

    persisted = _fetch_all_lists(db_path)
    assert len(persisted) == 2
    assert _file_sha256(working_db) == before_hash


@pytest.mark.parametrize("name", ["\u0000", "\u0000abc"])
def test_create_list_allows_nul_character_in_name(
    db_path: Path,
    name: str,
) -> None:
    application = create_app(db_path)
    with TestClient(application, raise_server_exceptions=False) as no_raise_client:
        response = no_raise_client.post("/lists", json={"name": name})

    assert response.status_code == 201, (
        f"Actual status={response.status_code}, body={response.text}"
    )
    body = response.json()
    assert body["name"] == name
    assert _fetch_all_lists(db_path) == [body]


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


def test_get_lists_empty_db(client: TestClient) -> None:
    response = client.get("/lists")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == []


def test_get_lists_ordered_by_created_at_then_id_without_items(
    client: TestClient,
    db_path: Path,
) -> None:
    with closing(get_connection(db_path)) as conn:
        with conn:
            conn.executemany(
                "INSERT INTO shopping_lists (id, name, created_at) VALUES (?, ?, ?)",
                [
                    (10, "Пізніший список", "2026-11-19T18:00:00Z"),
                    (30, "Однаковий час — більший id", "2026-11-19T16:00:00Z"),
                    (20, "Однаковий час — менший id", "2026-11-19T16:00:00Z"),
                    (5, "Проміжний час", "2026-11-19T17:00:00Z"),
                ],
            )
            conn.execute(
                """
                INSERT INTO shopping_items (
                    list_id, name, quantity_milli, unit, category_id, is_purchased, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (20, "Молоко", 2000, "л", 1, 0, "2026-11-19T16:01:00Z"),
            )

    response = client.get("/lists")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert body == [
        {
            "id": 20,
            "name": "Однаковий час — менший id",
            "created_at": "2026-11-19T16:00:00Z",
        },
        {
            "id": 30,
            "name": "Однаковий час — більший id",
            "created_at": "2026-11-19T16:00:00Z",
        },
        {
            "id": 5,
            "name": "Проміжний час",
            "created_at": "2026-11-19T17:00:00Z",
        },
        {
            "id": 10,
            "name": "Пізніший список",
            "created_at": "2026-11-19T18:00:00Z",
        },
    ]
    for item in body:
        assert set(item.keys()) == {"id", "name", "created_at"}
        assert "items" not in item
        assert type(item["id"]) is int
        assert isinstance(item["name"], str)
        assert isinstance(item["created_at"], str)


def test_get_lists_returns_created_lists_including_duplicates(
    client: TestClient,
) -> None:
    first = client.post("/lists", json={"name": "  На тиждень  "})
    second = client.post("/lists", json={"name": "На тиждень"})

    assert first.status_code == 201
    assert second.status_code == 201

    response = client.get("/lists")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body == [first.json(), second.json()]
    assert all(set(item.keys()) == {"id", "name", "created_at"} for item in body)


def test_get_lists_rejects_query_params_and_body(client: TestClient) -> None:
    single_query = client.get("/lists", params={"extra": "1"})
    assert single_query.status_code == 422
    assert single_query.headers["content-type"].startswith("application/json")
    single_detail = single_query.json()["detail"]
    assert single_detail["code"] == "validation_error"
    _assert_error_fields(single_detail, ["query.extra"])

    repeated_query = client.get("/lists?a=1&a=2")
    assert repeated_query.status_code == 422
    assert repeated_query.headers["content-type"].startswith("application/json")
    repeated_detail = repeated_query.json()["detail"]
    assert repeated_detail["code"] == "validation_error"
    _assert_error_fields(repeated_detail, ["query.a", "query.a"])

    with_body = client.request(
        "GET",
        "/lists",
        content=b'{"name": "x"}',
        headers={"Content-Type": "application/json"},
    )
    assert with_body.status_code == 422
    assert with_body.headers["content-type"].startswith("application/json")
    body_detail = with_body.json()["detail"]
    assert body_detail["code"] == "validation_error"
    _assert_error_fields(body_detail, ["body"])

    with_query_and_body = client.request(
        "GET",
        "/lists",
        params={"extra": "1"},
        content=b"raw",
    )
    assert with_query_and_body.status_code == 422
    assert with_query_and_body.headers["content-type"].startswith("application/json")
    combined_detail = with_query_and_body.json()["detail"]
    assert combined_detail["code"] == "validation_error"
    _assert_error_fields(combined_detail, ["query.extra", "body"])


def test_get_lists_returns_500_internal_error_on_db_failure(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken_fetch(*args: Any, **kwargs: Any) -> list[dict[str, int | str]]:
        raise sqlite3.OperationalError("simulated_internal_db_error")

    monkeypatch.setattr(services, "fetch_shopping_lists", _broken_fetch)

    application = create_app(db_path)
    with TestClient(application, raise_server_exceptions=False) as no_raise_client:
        response = no_raise_client.get("/lists")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    detail = response.json()["detail"]
    assert detail["code"] == "internal_error"
    assert isinstance(detail["message"], str)
    assert detail["message"]
    assert detail["fields"] == []
    assert "simulated_internal_db_error" not in response.text
