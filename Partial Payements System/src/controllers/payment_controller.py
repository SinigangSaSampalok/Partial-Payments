from __future__ import annotations

from src.models.client_model import ClientModel
from src.models.payment_model import PaymentModel


class PaymentController:
    def __init__(self, payment_model: PaymentModel, client_model: ClientModel) -> None:
        self.payment_model = payment_model
        self.client_model = client_model

    def list_client_payments(self, client_id: int):
        return self.payment_model.get_payments_for_client(client_id)

    def list_client_balance_events(self, client_id: int):
        return self.payment_model.get_balance_events_for_client(client_id)

    def list_client_items(self, client_id: int) -> list[str]:
        return self.payment_model.get_distinct_items_for_client(client_id)

    def list_client_payments_by_balance(self, client_id: int):
        return self.payment_model.get_payments_grouped_by_balance(client_id)

    def list_returned_items(self, client_id: int) -> list:
        return self.payment_model.get_returned_items_for_client(client_id)

    def return_item(
        self, client_id: int, item: str, note: str
    ) -> tuple[bool, str]:
        client = self.client_model.get_client(client_id)
        if not client:
            return False, "Client not found."

        normalized_item = str(item or "").strip()
        if not normalized_item:
            return False, "Item name is required."

        remaining = self.payment_model.get_item_remaining(client_id, normalized_item)

        if remaining is None:
            return False, f"Item '{normalized_item}' not found for this client."

        if remaining <= 0:
            return False, (
                f"Item '{normalized_item}' is fully paid and cannot be returned."
            )

        payments = self.payment_model.get_payments_for_client(client_id)
        item_payments = [
            p for p in payments
            if str(p.get("item") or "").strip().lower() == normalized_item.lower()
        ]
        if item_payments:
            return False, (
                f"Item '{normalized_item}' already has payments recorded and cannot be returned. "
                f"Returns are only allowed on items with no payments made yet."
            )

        returned, new_balance = self.payment_model.return_item(
            client_id, normalized_item, remaining, note
        )
        if returned is None or new_balance is None:
            return False, "Could not record return."

        return True, (
            f"Item '{normalized_item}' marked as returned. "
            f"Deducted: {returned:.2f}, New balance: {new_balance:.2f}"
        )

    def rename_item_for_client(self, client_id: int, old_item: str, new_item: str) -> tuple[bool, str]:
        client = self.client_model.get_client(client_id)
        if not client:
            return False, "Client not found."

        normalized_new = str(new_item or "").strip()
        if not normalized_new:
            return False, "Item name is required."

        normalized_old = str(old_item or "").strip()
        if normalized_old.lower() == normalized_new.lower():
            return True, "Item name unchanged."

        self.client_model.update_item_for_client(client_id, normalized_old, normalized_new)
        self.payment_model.update_item_for_client(client_id, normalized_old, normalized_new)
        return True, "Item updated successfully."

    def create_partial_payment(
        self,
        client_id: int,
        amount_text: str,
        item: str,
        note: str,
        created_at: str | None = None,
    ) -> tuple[bool, str]:
        client = self.client_model.get_client(client_id)
        if not client:
            return False, "Client not found."
        if float(client.get("balance", 0.0)) <= 0:
            return False, "Cannot add payment when current balance is 0."

        item_ok, item_message = self._validate_item_remaining(client_id, item)
        if not item_ok:
            return False, item_message

        amount = self._parse_positive_float(amount_text)
        if amount is None:
            return False, "Payment amount must be greater than 0."

        deducted_amount, new_balance, excess_added, new_excess = self.payment_model.add_partial_payment(
            client_id, amount, item, note, created_at
        )
        if (
            deducted_amount is None
            or new_balance is None
            or excess_added is None
            or new_excess is None
        ):
            return False, "Could not record payment."

        if excess_added > 0:
            return True, (
                f"Payment recorded. Deducted: {deducted_amount:.2f}, "
                f"Excess added: {excess_added:.2f}, "
                f"Balance: {new_balance:.2f}, Excess: {new_excess:.2f}"
            )

        return True, (
            f"Payment recorded. Deducted: {deducted_amount:.2f}, "
            f"Balance: {new_balance:.2f}, Excess: {new_excess:.2f}"
        )

    def create_calendar_payments(
        self,
        client_id: int,
        item: str,
        note: str,
        payments: list[tuple[str, str]],
    ) -> tuple[bool, str]:
        client = self.client_model.get_client(client_id)
        if not client:
            return False, "Client not found."
        if not payments:
            return False, "Enter at least one payment amount."

        item_ok, item_message = self._validate_item_remaining(client_id, item)
        if not item_ok:
            return False, item_message

        parsed: list[tuple[str, float]] = []
        for date_str, amount_text in payments:
            amount = self._parse_positive_float(amount_text)
            if amount is None:
                return False, f"Invalid amount for {date_str}."
            parsed.append((date_str, amount))

        parsed.sort(key=lambda entry: entry[0])

        total_deducted = 0.0
        total_excess = 0.0
        last_balance = None
        last_excess = None
        for date_str, amount in parsed:
            deducted_amount, new_balance, excess_added, new_excess = self.payment_model.add_partial_payment(
                client_id,
                amount,
                item,
                note,
                created_at=date_str,
            )
            if (
                deducted_amount is None
                or new_balance is None
                or excess_added is None
                or new_excess is None
            ):
                return False, "Could not record payment."
            total_deducted += deducted_amount
            total_excess += excess_added
            last_balance = new_balance
            last_excess = new_excess

        if last_balance is None or last_excess is None:
            return False, "Could not record payment."

        if total_excess > 0:
            return True, (
                f"Recorded {len(parsed)} payment(s). Deducted: {total_deducted:.2f}, "
                f"Excess added: {total_excess:.2f}, "
                f"Balance: {last_balance:.2f}, Excess: {last_excess:.2f}"
            )

        return True, (
            f"Recorded {len(parsed)} payment(s). Deducted: {total_deducted:.2f}, "
            f"Balance: {last_balance:.2f}, Excess: {last_excess:.2f}"
        )

    @staticmethod
    def _parse_positive_float(value: str) -> float | None:
        try:
            parsed = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _validate_item_remaining(self, client_id: int, item: str) -> tuple[bool, str]:
        normalized_item = str(item or "").strip()
        remaining = self.payment_model.get_item_remaining(client_id, normalized_item)
        if remaining is not None and remaining <= 0:
            remaining_onward = self.payment_model.get_remaining_from_item_onward(client_id, normalized_item)
            if remaining_onward <= 0:
                label = normalized_item or "Unspecified"
                return False, f"Item '{label}' is already fully paid."
        return True, ""
