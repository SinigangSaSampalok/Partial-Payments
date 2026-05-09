from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    location TEXT,
                    item TEXT,
                    barcode_value TEXT,
                    barcode_image_path TEXT,
                    balance REAL NOT NULL DEFAULT 0,
                    excess_payment REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    amount REAL NOT NULL CHECK(amount > 0),
                    item TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS balance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    amount REAL NOT NULL CHECK(amount >= 0),
                    applied_excess REAL NOT NULL DEFAULT 0,
                    item TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS returned_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    item TEXT NOT NULL,
                    amount REAL NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients(id)
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(clients)").fetchall()
            }
            if "phone" in columns or "email" in columns:
                # Rebuild clients table to permanently remove legacy phone/email columns.
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clients_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        location TEXT,
                        item TEXT,
                        barcode_value TEXT,
                        barcode_image_path TEXT,
                        balance REAL NOT NULL DEFAULT 0,
                        excess_payment REAL NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                location_expr = "COALESCE(location, '')" if "location" in columns else "''"
                item_expr = "COALESCE(item, '')" if "item" in columns else "''"
                barcode_value_expr = "barcode_value" if "barcode_value" in columns else "NULL"
                barcode_image_expr = "barcode_image_path" if "barcode_image_path" in columns else "NULL"
                connection.execute(
                    f"""
                    INSERT INTO clients_new (
                        id,
                        name,
                        location,
                        item,
                        barcode_value,
                        barcode_image_path,
                        balance,
                        excess_payment,
                        created_at,
                        updated_at
                    )
                    SELECT
                        id,
                        name,
                        {location_expr},
                        {item_expr},
                        {barcode_value_expr},
                        {barcode_image_expr},
                        balance,
                        COALESCE(excess_payment, 0),
                        COALESCE(created_at, CURRENT_TIMESTAMP),
                        COALESCE(updated_at, CURRENT_TIMESTAMP)
                    FROM clients
                    """
                )
                connection.execute("DROP TABLE clients")
                connection.execute("ALTER TABLE clients_new RENAME TO clients")
                connection.execute("PRAGMA foreign_keys = ON")
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(clients)").fetchall()
                }
            if "location" not in columns:
                connection.execute("ALTER TABLE clients ADD COLUMN location TEXT")
            if "item" not in columns:
                connection.execute("ALTER TABLE clients ADD COLUMN item TEXT")
            if "barcode_value" not in columns:
                connection.execute("ALTER TABLE clients ADD COLUMN barcode_value TEXT")
            if "barcode_image_path" not in columns:
                connection.execute("ALTER TABLE clients ADD COLUMN barcode_image_path TEXT")
            if "excess_payment" not in columns:
                connection.execute(
                    "ALTER TABLE clients ADD COLUMN excess_payment REAL NOT NULL DEFAULT 0"
                )
            if "created_at" not in columns:
                connection.execute(
                    "ALTER TABLE clients ADD COLUMN created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
            if "updated_at" not in columns:
                connection.execute(
                    "ALTER TABLE clients ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
            try:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_clients_name_nocase ON clients(name COLLATE NOCASE)"
                )
            except sqlite3.IntegrityError:
                # Existing duplicate legacy names can block unique index creation.
                # Runtime controller validation still prevents inserting new duplicates.
                pass
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_clients_barcode_value ON clients(barcode_value)"
            )
            balance_event_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(balance_events)").fetchall()
            }
            if "applied_excess" not in balance_event_columns:
                connection.execute(
                    "ALTER TABLE balance_events ADD COLUMN applied_excess REAL NOT NULL DEFAULT 0"
                )
            if "item" not in balance_event_columns:
                connection.execute("ALTER TABLE balance_events ADD COLUMN item TEXT")
            payment_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(payments)").fetchall()
            }
            if "item" not in payment_columns:
                connection.execute("ALTER TABLE payments ADD COLUMN item TEXT")
            # Backfill one baseline balance event per existing client if none exists yet.
            connection.execute(
                """
                INSERT INTO balance_events (client_id, amount, applied_excess, note)
                SELECT c.id, 0, 0, 'Opening balance (legacy)'
                FROM clients c
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM balance_events b
                    WHERE b.client_id = c.id
                )
                """
            )
            connection.commit()
