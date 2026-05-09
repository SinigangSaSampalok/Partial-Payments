from __future__ import annotations

import sqlite3

from src.models.client_model import ClientModel


class ClientController:
    def __init__(self, client_model: ClientModel) -> None:
        self.client_model = client_model

    def list_clients(self):
        return self.client_model.get_all_clients()

    def get_client(self, client_id: int):
        return self.client_model.get_client(client_id)

    def get_client_by_barcode(self, barcode_value: str):
        return self.client_model.get_client_by_barcode(barcode_value)

    def create_client(self, name: str, location: str, item: str, balance_text: str) -> tuple[bool, str]:
        normalized_name = name.strip()
        normalized_location = location.strip()
        normalized_item = item.strip()
        balance = self._parse_non_negative_float(balance_text)
        if not normalized_name:
            return False, "Client name is required."
        if balance is None:
            return False, "Opening balance must be a valid number (0 or higher)."
        if self.client_model.name_exists(normalized_name):
            return False, "Client name already exists."

        try:
            self.client_model.add_client(normalized_name, normalized_location, normalized_item, balance)
        except sqlite3.IntegrityError:
            return False, "Client name already exists."
        return True, "Client added successfully."

    def edit_client(
        self, client_id: int, name: str, location: str, item: str, balance_text: str
    ) -> tuple[bool, str]:
        existing = self.client_model.get_client(client_id)
        if not existing:
            return False, "Client not found."

        normalized_name = name.strip()
        normalized_location = location.strip()
        normalized_item = item.strip()
        balance = self._parse_non_negative_float(balance_text)
        if not normalized_name:
            return False, "Client name is required."
        if balance is None:
            return False, "Balance must be a valid number (0 or higher)."
        if self.client_model.name_exists(normalized_name, exclude_client_id=client_id):
            return False, "Client name already exists."

        try:
            self.client_model.update_client(
                client_id,
                normalized_name,
                normalized_location,
                normalized_item,
                balance,
            )
        except sqlite3.IntegrityError:
            return False, "Client name already exists."
        return True, "Client updated successfully."

    def remove_client(self, client_id: int) -> tuple[bool, str]:
        existing = self.client_model.get_client(client_id)
        if not existing:
            return False, "Client not found."

        self.client_model.delete_client(client_id)
        return True, "Client deleted."

    def increase_balance(
        self,
        client_id: int,
        amount_text: str,
        item: str,
        excess_target_item: str | None = None,
    ) -> tuple[bool, str]:
        amount = self._parse_positive_float(amount_text)
        if amount is None:
            return False, "Additional balance must be greater than 0."

        result = self.client_model.add_balance(
            client_id,
            amount,
            item.strip(),
            excess_target_item=excess_target_item,
        )
        if result is None:
            return False, "Client not found."

        new_balance, new_excess, applied_excess = result
        if applied_excess > 0:
            return True, (
                f"Balance increased. Applied excess credit: {applied_excess:.2f}. "
                f"New balance: {new_balance:.2f}, Remaining excess: {new_excess:.2f}"
            )
        return True, f"Balance increased. New balance: {new_balance:.2f}"

    @staticmethod
    def _parse_non_negative_float(value: str) -> float | None:
        try:
            parsed = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _parse_positive_float(value: str) -> float | None:
        try:
            parsed = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
