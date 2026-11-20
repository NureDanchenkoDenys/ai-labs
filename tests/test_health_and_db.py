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


def test_get_categories_returns_normative_catalog_ordered(
    client: TestClient,
) -> None:
    response = client.get("/categories")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 10
    for item in body:
        assert set(item.keys()) == {"id", "name", "description"}
        assert type(item["id"]) is int
        assert type(item["name"]) is str
        assert type(item["description"]) is str

    assert [item["id"] for item in body] == list(range(1, 11))
    assert [(item["id"], item["name"], item["description"]) for item in body] == list(
        CATEGORIES
    )


def test_get_categories_rejects_unexpected_query_and_body(
    client: TestClient,
) -> None:
    query_response = client.get("/categories", params={"extra": "1"})
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

    repeated_query_response = client.get("/categories?id=1&id=2")
    assert repeated_query_response.status_code == 422
    repeated_detail = repeated_query_response.json()["detail"]
    assert repeated_detail["code"] == "validation_error"
    assert repeated_detail["fields"] == [
        {
            "field": "query.id",
            "message": "Маршрут не приймає query-параметрів.",
        },
        {
            "field": "query.id",
            "message": "Маршрут не приймає query-параметрів.",
        },
    ]

    body_response = client.request("GET", "/categories", content=b"{}")
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

    combined_response = client.request(
        "GET",
        "/categories",
        params={"extra": "1"},
        content=b"{}",
    )
    assert combined_response.status_code == 422
    combined_detail = combined_response.json()["detail"]
    assert combined_detail["code"] == "validation_error"
    assert combined_detail["fields"] == [
        {
            "field": "query.extra",
            "message": "Маршрут не приймає query-параметрів.",
        },
        {
            "field": "body",
            "message": "GET-запит не приймає тіло.",
        },
    ]


def test_categories_endpoint_is_read_only(client: TestClient) -> None:
    post_response = client.post(
        "/categories",
        json={"name": "Нова категорія", "description": "Опис"},
    )
    assert post_response.status_code == 405

    get_response = client.get("/categories")
    assert get_response.status_code == 200
    assert len(get_response.json()) == 10


def test_get_categories_returns_500_on_incomplete_or_corrupted_catalog(
    db_path: Path,
) -> None:
    application = create_app(db_path)
    expected_error = {
        "detail": {
            "code": "internal_error",
            "message": "Внутрішня помилка сервера.",
            "fields": [],
        }
    }

    with TestClient(application, raise_server_exceptions=False) as no_raise_client:
        # 1. Змінено опис за наявності всіх 10 записів
        with closing(get_connection(db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE categories SET description = ? WHERE id = ?",
                    ("Пошкоджений опис", 1),
                )
        corrupted_desc_response = no_raise_client.get("/categories")
        assert corrupted_desc_response.status_code == 500
        assert corrupted_desc_response.json() == expected_error

        # 2. Змінено назву за наявності всіх 10 записів
        with closing(get_connection(db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE categories SET name = ?, description = ? WHERE id = ?",
                    ("Інша назва", CATEGORIES[0][2], 1),
                )
        corrupted_name_response = no_raise_client.get("/categories")
        assert corrupted_name_response.status_code == 500
        assert corrupted_name_response.json() == expected_error

        # 3. Неповний довідник (менше 10 категорій)
        with closing(get_connection(db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE categories SET name = ? WHERE id = ?",
                    (CATEGORIES[0][1], 1),
                )
                conn.execute("DELETE FROM categories WHERE id = ?", (10,))
        incomplete_response = no_raise_client.get("/categories")
        assert incomplete_response.status_code == 500
        assert incomplete_response.json() == expected_error

        # 4. Збій читання таблиці categories
        with closing(get_connection(db_path)) as conn:
            with conn:
                conn.execute("DROP TABLE shopping_items")
                conn.execute("DROP TABLE categories")
        missing_table_response = no_raise_client.get("/categories")
        assert missing_table_response.status_code == 500
        assert missing_table_response.json() == expected_error
