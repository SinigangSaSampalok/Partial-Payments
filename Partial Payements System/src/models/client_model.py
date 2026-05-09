from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.database.db import Database


class ClientModel:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.barcode_dir = self.database.db_path.parent / "barcodes"
        self.barcode_dir.mkdir(parents=True, exist_ok=True)

    def get_all_clients(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id,
                    c.name,
                    c.location,
                    c.item,
                    c.barcode_value,
                    c.barcode_image_path,
                    c.balance,
                    c.excess_payment,
                    c.created_at,
                    c.updated_at
                FROM clients c
                ORDER BY c.name COLLATE NOCASE
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def ensure_all_client_barcodes(self) -> None:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, location
                FROM clients
                """
            ).fetchall()
            for row in rows:
                self._ensure_client_barcode(
                    connection,
                    int(row["id"]),
                    str(row["name"] or "").strip(),
                    str(row["location"] or "").strip(),
                )
            connection.commit()

    def get_client(self, client_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, location, item, barcode_value, barcode_image_path, balance, excess_payment, created_at, updated_at
                FROM clients
                WHERE id = ?
                """,
                (client_id,),
            ).fetchone()
            return dict(row) if row else None

    def add_client(self, name: str, location: str, item: str, balance: float) -> None:
        with self.database.connect() as connection:
            normalized_name = name.strip()
            normalized_location = location.strip()
            normalized_item = item.strip()
            cursor = connection.execute(
                """
                INSERT INTO clients (name, location, item, balance)
                VALUES (?, ?, ?, ?)
                """,
                (normalized_name, normalized_location, normalized_item, balance),
            )
            client_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO balance_events (client_id, amount, applied_excess, item, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (client_id, max(0.0, balance), 0.0, normalized_item, "Opening balance"),
            )
            self._ensure_client_barcode(connection, client_id, normalized_name, normalized_location)
            connection.commit()

    def update_client(self, client_id: int, name: str, location: str, item: str, balance: float) -> None:
        with self.database.connect() as connection:
            normalized_name = name.strip()
            normalized_location = location.strip()
            normalized_item = item.strip()
            connection.execute(
                """
                UPDATE clients
                SET name = ?,
                    location = ?,
                    item = ?,
                    balance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_name, normalized_location, normalized_item, balance, client_id),
            )
            self._ensure_client_barcode(connection, client_id, normalized_name, normalized_location)
            connection.commit()

    def name_exists(self, name: str, exclude_client_id: int | None = None) -> bool:
        with self.database.connect() as connection:
            if exclude_client_id is None:
                row = connection.execute(
                    "SELECT 1 FROM clients WHERE name = ? COLLATE NOCASE LIMIT 1",
                    (name.strip(),),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM clients
                    WHERE name = ? COLLATE NOCASE
                      AND id <> ?
                    LIMIT 1
                    """,
                    (name.strip(), exclude_client_id),
                ).fetchone()
            return row is not None

    def delete_client(self, client_id: int) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT barcode_image_path FROM clients WHERE id = ?",
                (client_id,),
            ).fetchone()
            connection.execute("DELETE FROM payments WHERE client_id = ?", (client_id,))
            connection.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            connection.commit()
        if row and row["barcode_image_path"]:
            try:
                Path(str(row["barcode_image_path"])).unlink(missing_ok=True)
            except OSError:
                pass

    def get_client_by_barcode(self, barcode_value: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, location, item, barcode_value, barcode_image_path, balance, excess_payment, created_at, updated_at
                FROM clients
                WHERE barcode_value = ?
                """,
                (barcode_value.strip(),),
            ).fetchone()
            return dict(row) if row else None

    def _ensure_client_barcode(
        self,
        connection,
        client_id: int,
        client_name: str,
        client_location: str,
    ) -> None:
        row = connection.execute(
            "SELECT barcode_value FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        existing_value = str(row["barcode_value"] or "").strip() if row else ""
        barcode_value = existing_value or self._build_barcode_value(client_id)
        barcode_image_path = self.barcode_dir / f"client_{client_id}.png"

        generated_path = self._render_barcode_image(
            barcode_value=barcode_value,
            client_name=client_name,
            client_location=client_location,
            target_path=barcode_image_path,
        )

        connection.execute(
            """
            UPDATE clients
            SET barcode_value = ?,
                barcode_image_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                barcode_value,
                str(generated_path) if generated_path is not None else str(barcode_image_path),
                client_id,
            ),
        )

    @staticmethod
    def _build_barcode_value(client_id: int) -> str:
        timestamp = datetime.utcnow().strftime("%y%m%d%H%M%S")
        return f"PPS{client_id:06d}{timestamp}"

    def _render_barcode_image(
        self,
        barcode_value: str,
        client_name: str,
        client_location: str,
        target_path: Path,
    ) -> Path | None:
        try:
            from barcode import get as barcode_get
            from barcode.writer import ImageWriter
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return None

        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_stem = target_path.parent / f"{target_path.stem}_tmp"
        temp_png = temp_stem.with_suffix(".png")

        try:
            code128 = barcode_get("code128", barcode_value, writer=ImageWriter())
            written_path = Path(
                code128.save(
                    str(temp_stem),
                    options={
                        "module_width": 0.4,
                        "module_height": 16,
                        "quiet_zone": 4,
                        "font_size": 11,
                        "text_distance": 4,
                        "write_text": True,
                    },
                )
            )
            if not written_path.exists():
                return None

            with Image.open(written_path).convert("RGB") as base_image:
                padding = 20
                label_gap = 10
                line_height = 18
                n_lines = 2  # client name + location line
                canvas_width = max(base_image.width + padding * 2, 480)
                canvas_height = base_image.height + padding * 2 + label_gap + line_height * n_lines

                canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
                draw = ImageDraw.Draw(canvas)

                # Try to load a nicer font; fall back to default
                try:
                    font_regular = ImageFont.truetype("arial.ttf", 14)
                    font_bold = ImageFont.truetype("arialbd.ttf", 15)
                except Exception:
                    try:
                        font_regular = ImageFont.load_default(size=14)
                        font_bold = font_regular
                    except Exception:
                        font_regular = ImageFont.load_default()
                        font_bold = font_regular

                # Center barcode
                barcode_x = (canvas_width - base_image.width) // 2
                canvas.paste(base_image, (barcode_x, padding))

                # Client name line
                name_text = client_name.strip()
                name_box = draw.textbbox((0, 0), name_text, font=font_bold)
                name_w = name_box[2] - name_box[0]
                name_y = padding + base_image.height + label_gap
                draw.text(((canvas_width - name_w) // 2, name_y), name_text, fill="#111111", font=font_bold)

                # Location line
                loc_text = (client_location.strip() or "-")
                loc_box = draw.textbbox((0, 0), loc_text, font=font_regular)
                loc_w = loc_box[2] - loc_box[0]
                loc_y = name_y + line_height
                draw.text(((canvas_width - loc_w) // 2, loc_y), loc_text, fill="#555555", font=font_regular)

                canvas.save(target_path, format="PNG")
            return target_path
        except Exception:
            return None
        finally:
            try:
                temp_png.unlink(missing_ok=True)
            except OSError:
                pass

    def add_balance(
        self,
        client_id: int,
        amount: float,
        item: str,
        excess_target_item: str | None = None,
    ) -> tuple[float, float, float] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT balance, excess_payment FROM clients WHERE id = ?",
                (client_id,),
            ).fetchone()
            if not row:
                return None

            current_balance = float(row["balance"])
            current_excess = float(row["excess_payment"])
            new_balance = current_balance + amount
            applied_excess = 0.0
            new_excess = current_excess
            normalized_item = item.strip()
            normalized_target = str(excess_target_item or "").strip()
            target_for_excess = normalized_target or normalized_item

            # Apply excess credit only when this client currently has zero balance.
            if current_balance <= 0 and current_excess > 0:
                item_summary = self._item_summary(connection, client_id)
                has_existing_items = any(value > 1e-6 for value in item_summary.values())
                cap_by_balance = min(new_balance, current_excess)

                if has_existing_items:
                    target_remaining = item_summary.get(target_for_excess.lower(), 0.0)
                    applied_excess = min(cap_by_balance, target_remaining)
                else:
                    # No existing item yet: apply excess directly to this new item.
                    target_for_excess = normalized_item
                    applied_excess = min(cap_by_balance, amount)

                new_balance -= applied_excess
                new_excess = current_excess - applied_excess

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
            if applied_excess > 0 and target_for_excess.lower() != normalized_item.lower():
                connection.execute(
                    """
                    INSERT INTO balance_events (client_id, amount, applied_excess, item, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (client_id, amount, 0.0, normalized_item, "Added balance"),
                )
                connection.execute(
                    """
                    INSERT INTO balance_events (client_id, amount, applied_excess, item, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (client_id, 0.0, applied_excess, target_for_excess, "Applied excess credit"),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO balance_events (client_id, amount, applied_excess, item, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (client_id, amount, applied_excess, normalized_item, "Added balance"),
                )
            connection.commit()
            return new_balance, new_excess, applied_excess

    def _item_summary(self, connection, client_id: int) -> dict[str, float]:
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

        remaining: dict[str, float] = {}
        for key, values in summary.items():
            remaining[key] = max(0.0, values["balance"] - values["paid"] - values["returned"])
        return remaining

    def update_item_for_client(self, client_id: int, old_item: str, new_item: str) -> None:
        old_item = str(old_item or "").strip()
        new_item = str(new_item or "").strip()
        with self.database.connect() as connection:
            if old_item:
                connection.execute(
                    """
                    UPDATE clients
                    SET item = ?
                    WHERE id = ? AND item = ?
                    """,
                    (new_item, client_id, old_item),
                )
            else:
                connection.execute(
                    """
                    UPDATE clients
                    SET item = ?
                    WHERE id = ? AND (item IS NULL OR TRIM(item) = '')
                    """,
                    (new_item, client_id),
                )
            connection.commit()