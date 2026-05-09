from __future__ import annotations

from typing import Any

from src.database.db import Database


class PaymentModel:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_payments_for_client(self, client_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, client_id, amount, item, note, created_at
                FROM payments
                WHERE client_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (client_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_distinct_items_for_client(self, client_id: int) -> list[str]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT item
                FROM (
                    SELECT TRIM(item) AS item
                    FROM payments
                    WHERE client_id = ? AND item IS NOT NULL AND TRIM(item) <> ''
                    UNION
                    SELECT TRIM(item) AS item
                    FROM balance_events
                    WHERE client_id = ? AND item IS NOT NULL AND TRIM(item) <> ''
                )
                ORDER BY item COLLATE NOCASE
                """,
                (client_id, client_id),
            ).fetchall()
            return [row["item"] for row in rows if row["item"]]

    def get_item_remaining(self, client_id: int, item: str) -> float | None:
        normalized_key = str(item or "").strip().lower()
        with self.database.connect() as connection:
            balance_rows = connection.execute(
                """
                SELECT amount, applied_excess, item
                FROM balance_events
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            payment_rows = connection.execute(
                """
                SELECT amount, item
                FROM payments
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            return_rows = connection.execute(
                """
                SELECT amount, item
                FROM returned_items
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()

        summary: dict[str, dict[str, float]] = {}
        for row in balance_rows:
            key = str(row["item"] or "").strip().lower()
            entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
            entry["balance"] += float(row["amount"] or 0.0)
            entry["paid"] += float(row["applied_excess"] or 0.0)

        for row in payment_rows:
            key = str(row["item"] or "").strip().lower()
            entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
            entry["paid"] += float(row["amount"] or 0.0)

        for row in return_rows:
            key = str(row["item"] or "").strip().lower()
            entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
            entry["returned"] += float(row["amount"] or 0.0)

        if normalized_key not in summary:
            return None

        entry = summary[normalized_key]
        return max(0.0, entry["balance"] - entry["paid"] - entry["returned"])

    def get_remaining_from_item_onward(self, client_id: int, item: str) -> float:
        normalized_item = str(item or "").strip().lower()
        with self.database.connect() as connection:
            balance_rows = connection.execute(
                """
                SELECT amount, applied_excess, item
                FROM balance_events
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            payment_rows = connection.execute(
                """
                SELECT amount, item
                FROM payments
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            return_rows = connection.execute(
                """
                SELECT amount, item
                FROM returned_items
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            order_rows = connection.execute(
                """
                SELECT item, created_at, id
                FROM balance_events
                WHERE client_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (client_id,),
            ).fetchall()

        summary: dict[str, dict[str, float]] = {}
        for row in balance_rows:
            key = str(row["item"] or "").strip()
            entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
            entry["balance"] += float(row["amount"] or 0.0)
            entry["paid"] += float(row["applied_excess"] or 0.0)

        for row in payment_rows:
            key = str(row["item"] or "").strip()
            entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
            entry["paid"] += float(row["amount"] or 0.0)

        for row in return_rows:
            key = str(row["item"] or "").strip()
            entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
            entry["returned"] += float(row["amount"] or 0.0)

        ordered_items: list[str] = []
        seen_norm: dict[str, int] = {}
        for row in order_rows:
            key = str(row["item"] or "").strip()
            norm_key = key.lower()
            if norm_key in seen_norm:
                continue
            seen_norm[norm_key] = len(ordered_items)
            ordered_items.append(key)

        for key in summary.keys():
            norm_key = key.lower()
            if norm_key not in seen_norm:
                seen_norm[norm_key] = len(ordered_items)
                ordered_items.append(key)

        if not ordered_items:
            return 0.0

        if normalized_item and normalized_item in seen_norm:
            start_idx = seen_norm[normalized_item]
        else:
            start_idx = 0

        remaining_by_norm: dict[str, float] = {}
        for key, values in summary.items():
            norm_key = key.lower()
            remaining_by_norm[norm_key] = remaining_by_norm.get(norm_key, 0.0) + max(
                0.0,
                values["balance"] - values["paid"] - values["returned"],
            )

        remaining_available = 0.0
        for key in ordered_items[start_idx:]:
            remaining_available += remaining_by_norm.get(key.lower(), 0.0)
        return remaining_available

    def update_item_for_client(self, client_id: int, old_item: str, new_item: str) -> None:
        old_item = str(old_item or "").strip()
        new_item = str(new_item or "").strip()
        with self.database.connect() as connection:
            if old_item:
                connection.execute(
                    """
                    UPDATE payments
                    SET item = ?
                    WHERE client_id = ? AND item = ?
                    """,
                    (new_item, client_id, old_item),
                )
                connection.execute(
                    """
                    UPDATE balance_events
                    SET item = ?
                    WHERE client_id = ? AND item = ?
                    """,
                    (new_item, client_id, old_item),
                )
            else:
                connection.execute(
                    """
                    UPDATE payments
                    SET item = ?
                    WHERE client_id = ? AND (item IS NULL OR TRIM(item) = '')
                    """,
                    (new_item, client_id),
                )
                connection.execute(
                    """
                    UPDATE balance_events
                    SET item = ?
                    WHERE client_id = ? AND (item IS NULL OR TRIM(item) = '')
                    """,
                    (new_item, client_id),
                )
            connection.commit()

    def get_balance_events_for_client(self, client_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, client_id, amount, applied_excess, item, note, created_at
                FROM balance_events
                WHERE client_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (client_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_payments_grouped_by_balance(self, client_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            event_rows = connection.execute(
                """
                SELECT id, client_id, amount, applied_excess, item, note, created_at
                FROM balance_events
                WHERE client_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (client_id,),
            ).fetchall()
            payment_rows = connection.execute(
                """
                SELECT id, client_id, amount, item, note, created_at
                FROM payments
                WHERE client_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (client_id,),
            ).fetchall()

        events = [dict(row) for row in event_rows]
        payments = [dict(row) for row in payment_rows]

        if not events:
            return [
                {
                    "event": {
                        "id": 0,
                        "amount": 0.0,
                        "note": "No balance event recorded",
                        "created_at": "",
                    },
                    "payments": payments,
                }
            ]

        groups: list[dict[str, Any]] = [{"event": event, "payments": []} for event in events]
        event_idx = 0

        for payment in payments:
            while event_idx + 1 < len(events):
                next_event = events[event_idx + 1]
                if (payment["created_at"], payment["id"]) >= (next_event["created_at"], next_event["id"]):
                    event_idx += 1
                else:
                    break
            groups[event_idx]["payments"].append(payment)

        for group in groups:
            event = group["event"]
            applied_excess = float(event.get("applied_excess", 0.0) or 0.0)
            if applied_excess > 0:
                group["payments"].insert(
                    0,
                    {
                        "id": f"auto-excess-{event.get('id', 0)}",
                        "client_id": client_id,
                        "amount": applied_excess,
                        "note": "Auto-applied from excess credit",
                        "created_at": event.get("created_at") or "-",
                        "is_auto_excess": True,
                    },
                )

        return groups

    def get_returned_items_for_client(self, client_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, client_id, item, amount, note, created_at
                FROM returned_items
                WHERE client_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (client_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def return_item(
        self, client_id: int, item: str, amount: float, note: str
    ) -> tuple[float | None, float | None]:
        with self.database.connect() as connection:
            client_row = connection.execute(
                "SELECT balance FROM clients WHERE id = ?",
                (client_id,),
            ).fetchone()
            if not client_row:
                return None, None

            current_balance = float(client_row["balance"])
            new_balance = max(0.0, current_balance - amount)

            connection.execute(
                """
                INSERT INTO returned_items (client_id, item, amount, note)
                VALUES (?, ?, ?, ?)
                """,
                (client_id, item.strip(), amount, note.strip()),
            )
            connection.execute(
                """
                UPDATE clients
                SET balance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_balance, client_id),
            )
            connection.commit()
            return amount, new_balance

    def add_partial_payment(
        self, client_id: int, amount: float, item: str, note: str, created_at: str | None = None
    ) -> tuple[float | None, float | None, float | None, float | None]:
        with self.database.connect() as connection:
            client_row = connection.execute(
                "SELECT balance, excess_payment FROM clients WHERE id = ?",
                (client_id,),
            ).fetchone()

            if not client_row:
                return None, None, None, None

            current_balance = float(client_row["balance"])
            current_excess = float(client_row["excess_payment"])
            normalized_item = str(item or "").strip()
            normalized_item_key = normalized_item.lower()

            balance_rows = connection.execute(
                """
                SELECT amount, applied_excess, item
                FROM balance_events
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            payment_rows = connection.execute(
                """
                SELECT amount, item
                FROM payments
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()
            return_rows = connection.execute(
                """
                SELECT amount, item
                FROM returned_items
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchall()

            summary: dict[str, dict[str, float]] = {}
            for row in balance_rows:
                key = str(row["item"] or "").strip()
                entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
                entry["balance"] += float(row["amount"] or 0.0)
                entry["paid"] += float(row["applied_excess"] or 0.0)

            for row in payment_rows:
                key = str(row["item"] or "").strip()
                entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
                entry["paid"] += float(row["amount"] or 0.0)

            for row in return_rows:
                key = str(row["item"] or "").strip()
                entry = summary.setdefault(key, {"balance": 0.0, "paid": 0.0, "returned": 0.0})
                entry["returned"] += float(row["amount"] or 0.0)

            order_rows = connection.execute(
                """
                SELECT item, created_at, id
                FROM balance_events
                WHERE client_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (client_id,),
            ).fetchall()
            ordered_items: list[str] = []
            seen_norm: dict[str, int] = {}
            for row in order_rows:
                key = str(row["item"] or "").strip()
                norm_key = key.lower()
                if norm_key in seen_norm:
                    continue
                seen_norm[norm_key] = len(ordered_items)
                ordered_items.append(key)

            for key in summary.keys():
                norm_key = key.lower()
                if norm_key not in seen_norm:
                    seen_norm[norm_key] = len(ordered_items)
                    ordered_items.append(key)

            if not ordered_items:
                ordered_items = [normalized_item] if normalized_item else []
                if normalized_item:
                    seen_norm[normalized_item_key] = 0

            start_idx = seen_norm.get(normalized_item_key, 0)

            remaining_by_norm: dict[str, float] = {}
            for key, values in summary.items():
                norm_key = key.lower()
                remaining_by_norm[norm_key] = remaining_by_norm.get(norm_key, 0.0) + max(
                    0.0,
                    values["balance"] - values["paid"] - values["returned"],
                )
            remaining_available = 0.0
            for key in ordered_items[start_idx:]:
                remaining_available += remaining_by_norm.get(key.lower(), 0.0)

            deducted_amount = min(amount, current_balance, remaining_available)
            excess_added = amount - deducted_amount
            new_balance = max(0.0, current_balance - deducted_amount)
            new_excess = current_excess + excess_added

            amount_left = deducted_amount
            allocations: list[tuple[str, float]] = []
            for key in ordered_items[start_idx:]:
                if amount_left <= 0:
                    break
                remaining = remaining_by_norm.get(key.lower(), 0.0)
                if remaining <= 0:
                    continue
                applied = min(remaining, amount_left)
                if applied <= 0:
                    continue
                allocations.append((key, applied))
                amount_left -= applied

            if not allocations and deducted_amount > 0:
                allocations.append((normalized_item, deducted_amount))

            for key, applied in allocations:
                normalized_key = str(key or "").strip()
                note_text = str(note or "").strip()
                if created_at:
                    existing = connection.execute(
                        """
                        SELECT id, amount, note
                        FROM payments
                        WHERE client_id = ?
                          AND created_at = ?
                          AND LOWER(COALESCE(TRIM(item), '')) = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (client_id, created_at, normalized_key.lower()),
                    ).fetchone()
                    if existing:
                        existing_amount = float(existing["amount"] or 0.0)
                        existing_note = str(existing["note"] or "")
                        updated_note = existing_note or note_text
                        connection.execute(
                            """
                            UPDATE payments
                            SET amount = ?, note = ?
                            WHERE id = ?
                            """,
                            (existing_amount + applied, updated_note, existing["id"]),
                        )
                        continue

                    connection.execute(
                        """
                        INSERT INTO payments (client_id, amount, item, note, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (client_id, applied, normalized_key, note_text, created_at),
                    )
                    continue

                connection.execute(
                    """
                    INSERT INTO payments (client_id, amount, item, note)
                    VALUES (?, ?, ?, ?)
                    """,
                    (client_id, applied, normalized_key, note_text),
                )

            connection.execute(
                """
                UPDATE clients
                SET balance = ?,
                    excess_payment = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_balance, new_excess, client_id),
            )
            connection.commit()
            return deducted_amount, new_balance, excess_added, new_excess
