import hashlib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
