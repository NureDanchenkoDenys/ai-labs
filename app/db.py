import sqlite3
from contextlib import closing
from pathlib import Path

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
        name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shopping_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        list_id INTEGER NOT NULL REFERENCES shopping_lists(id),
        name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 160),
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
