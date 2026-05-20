"""
Run at container start to create planning-owned tables in MariaDB if they don't exist.
Safe to run repeatedly (all statements use IF NOT EXISTS).
"""
import logging
import os
import sys

from db_config import get_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SQL_FILE = os.path.join(os.path.dirname(__file__), "migrations", "planning_mariadb_init.sql")


def run() -> None:
    with open(SQL_FILE, encoding="utf-8") as f:
        sql = f.read()

    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        logger.info("Planning tables initialized in MariaDB.")
    except Exception as e:
        conn.rollback()
        logger.error("init_db failed: %s", e)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
