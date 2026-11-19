from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import CATEGORIES, get_connection, init_db
from app.main import create_app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_health_rejects_unexpected_query_and_body(client: TestClient) -> None:
    query_response = client.get("/health", params={"extra": "1"})
    assert query_response.status_code == 422
    query_detail = query_response.json()["detail"]
    assert query_detail["code"] == "validation_error"
    assert query_detail["message"]
    assert query_detail["fields"] == [
        {
            "field": "query.extra",
            "message": "Маршрут не приймає query-параметрів.",
        }
    ]

    body_response = client.request("GET", "/health", content=b"{}")
    assert body_response.status_code == 422
    body_detail = body_response.json()["detail"]
    assert body_detail["code"] == "validation_error"
    assert body_detail["message"]
    assert body_detail["fields"] == [
        {
            "field": "body",
            "message": "GET-запит не приймає тіло.",
        }
    ]


def test_init_db_is_idempotent_and_seeds_ten_categories(db_path: Path) -> None:
    init_db(db_path)
    init_db(db_path)

    with closing(get_connection(db_path)) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT id, name, description FROM categories ORDER BY id ASC"
        ).fetchall()

    assert foreign_keys == 1
    assert {"categories", "shopping_lists", "shopping_items"}.issubset(tables)
    assert {
        "idx_shopping_items_list_created_id",
        "idx_shopping_items_list_category_purchased",
    }.issubset(indexes)
    assert len(rows) == 10
    assert [(row["id"], row["name"], row["description"]) for row in rows] == list(
        CATEGORIES
    )


def test_create_app_uses_isolated_temp_db_via_lifespan(tmp_path: Path) -> None:
    working_db = Path("database.db")
    working_db_existed = working_db.exists()
    temp_db = tmp_path / "lifespan.db"

    assert not temp_db.exists()

    with TestClient(create_app(temp_db)) as test_client:
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    assert temp_db.exists()
    assert working_db.exists() == working_db_existed

    with closing(get_connection(temp_db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    assert count == 10
