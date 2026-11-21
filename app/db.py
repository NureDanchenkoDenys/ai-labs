import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("database.db")

CATEGORIES: tuple[tuple[int, str, str], ...] = (
    (
        1,
        "Молочні продукти",
        "Молоко тваринного походження, кисломолочні продукти, сир, вершкове масло. "
        "Рослинні замінники належать до категорії 7.",
    ),
    (
        2,
        "Овочі",
        "Свіжі та заморожені овочі, зелень. Готові соуси належать до категорії 8.",
    ),
    (
        3,
        "Фрукти",
        "Свіжі та заморожені фрукти, ягоди.",
    ),
    (
        4,
        "М’ясо та риба",
        "М’ясо, птиця, риба та морепродукти.",
    ),
    (
        5,
        "Хліб та випічка",
        "Хліб, лаваш, несолодкі булочки та інша несолодка випічка. "
        "Солодощі належать до категорії 10.",
    ),
    (
        6,
        "Крупи та макаронні вироби",
        "Рис, гречка, інші крупи, пластівці та макаронні вироби.",
    ),
    (
        7,
        "Рослинні напої",
        "Рослинні замінники питного молока: вівсяні, соєві, мигдальні та інші напої. "
        "Кулінарне кокосове молоко для соусів належить до категорії 8.",
    ),
    (
        8,
        "Продукти для приготування страв",
        "У цьому довіднику: готові соуси, приправи, кулінарні суміші та кокосове "
        "молоко для приготування страв. Свіжі овочі, м’ясо і крупи зберігають свої "
        "окремі категорії.",
    ),
    (
        9,
        "Побутова хімія",
        "Мийні й чистильні засоби для дому, прання та посуду. "
        "Харчові продукти сюди не належать.",
    ),
    (
        10,
        "Кондитерські вироби",
        "Цукерки, шоколад, печиво, торти та інші солодощі, зокрема солодка випічка.",
    ),
)

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 10),
        name TEXT NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 120),
        description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 500)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shopping_lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL CHECK (length(CAST(name AS BLOB)) BETWEEN 1 AND 480),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shopping_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        list_id INTEGER NOT NULL REFERENCES shopping_lists(id),
        name TEXT NOT NULL CHECK (length(CAST(name AS BLOB)) BETWEEN 1 AND 640),
        quantity_milli INTEGER NOT NULL CHECK (quantity_milli BETWEEN 1 AND 10000000),
        unit TEXT NOT NULL CHECK (unit IN ('шт', 'кг', 'г', 'л', 'мл', 'уп')),
        category_id INTEGER NOT NULL REFERENCES categories(id),
        is_purchased INTEGER NOT NULL DEFAULT 0 CHECK (is_purchased IN (0, 1)),
        created_at TEXT NOT NULL,
        CHECK (unit NOT IN ('шт', 'уп') OR quantity_milli % 1000 = 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_shopping_items_list_created_id
        ON shopping_items (list_id, created_at, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_shopping_items_list_category_purchased
        ON shopping_items (list_id, category_id, is_purchased)
    """,
)


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    if str(db_path) != ":memory:" and path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with closing(get_connection(db_path)) as conn:
        with conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.executemany(
                "INSERT OR IGNORE INTO categories (id, name, description) VALUES (?, ?, ?)",
                CATEGORIES,
            )


def fetch_categories(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, int | str]]:
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM categories ORDER BY id ASC"
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
        }
        for row in rows
    ]


def insert_shopping_list(
    db_path: str | Path,
    name: str,
    created_at: str,
) -> dict[str, int | str]:
    with closing(get_connection(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                "INSERT INTO shopping_lists (name, created_at) VALUES (?, ?)",
                (name, created_at),
            )
            list_id = cursor.lastrowid
            if list_id is None:
                raise RuntimeError("Не вдалося отримати ідентифікатор створеного списку.")
            row = conn.execute(
                "SELECT id, name, created_at FROM shopping_lists WHERE id = ?",
                (list_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Створений список не знайдено після збереження.")
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "created_at": str(row["created_at"]),
    }


def fetch_shopping_lists(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, int | str]]:
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM shopping_lists ORDER BY created_at ASC, id ASC"
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def _milli_to_quantity(quantity_milli: int) -> int | float:
    if quantity_milli % 1000 == 0:
        return quantity_milli // 1000
    return float(Decimal(quantity_milli) / Decimal(1000))


def fetch_shopping_list_with_items(
    db_path: str | Path,
    list_id: int,
) -> dict[str, Any] | None:
    with closing(get_connection(db_path)) as conn:
        list_row = conn.execute(
            "SELECT id, name, created_at FROM shopping_lists WHERE id = ?",
            (list_id,),
        ).fetchone()
        if list_row is None:
            return None

        item_rows = conn.execute(
            """
            SELECT
                id,
                list_id,
                name,
                quantity_milli,
                unit,
                category_id,
                is_purchased,
                created_at
            FROM shopping_items
            WHERE list_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (list_id,),
        ).fetchall()

    return {
        "id": int(list_row["id"]),
        "name": str(list_row["name"]),
        "created_at": str(list_row["created_at"]),
        "items": [
            {
                "id": int(row["id"]),
                "list_id": int(row["list_id"]),
                "name": str(row["name"]),
                "quantity": _milli_to_quantity(int(row["quantity_milli"])),
                "unit": str(row["unit"]),
                "category_id": int(row["category_id"]),
                "is_purchased": bool(int(row["is_purchased"])),
                "created_at": str(row["created_at"]),
            }
            for row in item_rows
        ],
    }
