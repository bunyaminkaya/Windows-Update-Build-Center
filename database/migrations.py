import sqlite3
from app.paths import DB_PATH

def run_migrations():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS search_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS favorites(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                item_key TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_search_history_created_at ON search_history(created_at);
            CREATE INDEX IF NOT EXISTS idx_favorites_type_key ON favorites(item_type, item_key);
            '''
        )
        _ensure_column(conn, "favorites", "metadata_json", "TEXT")
        for obsolete in ("packages", "downloads", "app_state"):
            conn.execute(f"DROP TABLE IF EXISTS {obsolete}")


def _ensure_column(conn, table: str, column: str, sql_type: str) -> None:
    columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        )
