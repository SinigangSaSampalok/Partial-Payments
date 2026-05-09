from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
import time
from tkinter import filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y
from ttkbootstrap.icons import Emoji

from src.views.dialogs import (
    AddBalanceDialog,
    ClientFormDialog,
    ClientInfoDialog,
    PaymentDialog,
)


class MainView:
    def __init__(self, root, client_controller, payment_controller, db_path: Path) -> None:
        self.root = root
        self.client_controller = client_controller
        self.all_clients_cache: list[dict] = []
        self.payment_controller = payment_controller
        self.db_path = Path(db_path)
        self.clients_cache: list[dict] = []
        self.toolbar: tb.Frame | None = None
        self.left_toolbar: tb.Frame | None = None
        self.right_toolbar: tb.Frame | None = None
        self.toolbar_stacked: bool | None = None
        self.resize_after_id: str | None = None
        self.last_table_width: int = 0
        self.location_var = tb.StringVar(value="All locations")
        self.location_combo: tb.Combobox | None = None
        self.client_info_dialogs: dict[int, ClientInfoDialog] = {}
        self.scan_buffer: str = ""
        self.scan_last_ts: float = 0.0
        self.scan_timeout_seconds: float = 0.6
        self._search_trace_id: str = ""
        self.columns = ("name", "balance", "excess")
        self.column_min_widths = {
            "name": 320,
            "balance": 200,
            "excess": 200,
        }
        self.column_weights = {
            "name": 0.5,
            "balance": 0.25,
            "excess": 0.25,
        }

        self._build_layout()

    def _build_layout(self) -> None:
        self.root.configure(padx=18, pady=18)

        header_card = tb.Frame(self.root, bootstyle="primary", padding=18)
        header_card.pack(fill=X)

        title = tb.Label(
            header_card,
            text="Partial Payments Dashboard",
            font=("Segoe UI", 22, "bold"),
            bootstyle="inverse-primary",
        )
        title.pack(anchor="w")

        subtitle = tb.Label(
            header_card,
            text="Track client balances, record partial payments, and keep historical records ready.",
            font=("Segoe UI", 11),
            bootstyle="inverse-primary",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        self.toolbar = tb.Frame(self.root, bootstyle="info", padding=(10, 14, 10, 10))
        self.toolbar.pack(fill=X)
        self.left_toolbar = tb.Frame(self.toolbar, bootstyle="info")
        self.right_toolbar = tb.Frame(self.toolbar, bootstyle="info")
        self.left_toolbar.pack(side=LEFT, fill=X, expand=True)
        self.right_toolbar.pack(side=RIGHT)

        tb.Button(
            self.left_toolbar,
            text=f" {self._emoji('bust in silhouette', '+')} Add Client",
            bootstyle="primary",
            command=self.open_add_client,
        ).pack(side=LEFT)
        tb.Button(
            self.right_toolbar,
            text=f" {self._emoji('ballot box with check', '[ ]')} Select All",
            bootstyle="dark-outline",
            command=self.select_all_clients,
        ).pack(side=RIGHT)
        tb.Button(
            self.right_toolbar,
            text=f" {self._emoji('cross mark', '[-]')} Clear Selection",
            bootstyle="dark-outline",
            command=self.clear_selection,
        ).pack(side=RIGHT, padx=(8, 0))
        tb.Button(
            self.right_toolbar,
            text=f" {self._emoji('clockwise rightwards and leftwards open circle arrows', 'R')} Refresh",
            bootstyle="dark-outline",
            command=self.refresh_clients,
        ).pack(side=RIGHT)
        tb.Button(
            self.right_toolbar,
            text=f" {self._emoji('floppy disk', 'B')} Backup",
            bootstyle="dark-outline",
            command=self.backup_database,
        ).pack(side=RIGHT, padx=(8, 0))
        tb.Button(
            self.right_toolbar,
            text=f" {self._emoji('inbox tray', 'U')} Restore",
            bootstyle="dark-outline",
            command=self.restore_database,
        ).pack(side=RIGHT, padx=(8, 0))

        self.search_var = tb.StringVar(value="")
        search_row = tb.Frame(self.root, bootstyle="light", padding=(0, 8, 0, 8))
        search_row.pack(fill=X)
        tb.Label(search_row, text="Search", bootstyle="secondary").pack(side=LEFT, padx=(0, 8))
        search_entry = tb.Entry(search_row, textvariable=self.search_var, width=36)
        search_entry.pack(side=LEFT)
        tb.Button(
            search_row,
            text="Clear",
            bootstyle="secondary-outline",
            command=self._clear_search,
        ).pack(side=LEFT, padx=(8, 0))
        tb.Label(search_row, text="Location", bootstyle="secondary").pack(side=LEFT, padx=(16, 8))
        self.location_combo = tb.Combobox(
            search_row,
            textvariable=self.location_var,
            values=["All locations"],
            width=24,
            state="readonly",
        )
        self.location_combo.pack(side=LEFT)
        self.location_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_client_filter())
        self._search_trace_id = self.search_var.trace_add("write", lambda *_: self._apply_client_filter())

        table_card = tb.Frame(self.root, bootstyle="light", padding=14)
        table_card.pack(fill=BOTH, expand=True)

        self.table = tb.Treeview(
            table_card,
            columns=self.columns,
            show="headings",
            selectmode="extended",
            bootstyle="primary",
        )

        self.table.heading("name", text="Client Name", anchor="center")
        self.table.heading("balance", text="Current Balance", anchor="center")
        self.table.heading("excess", text="Excess Payment", anchor="center")

        self.table.column("name", width=420, anchor="center", stretch=False)
        self.table.column("balance", width=220, anchor="center", stretch=False)
        self.table.column("excess", width=220, anchor="center", stretch=False)

        self.table.pack(side=LEFT, fill=BOTH, expand=True)
        self.table.bind("<Configure>", self._on_table_configure)
        self.table.bind("<ButtonRelease-1>", self._on_table_click, add="+")
        self.root.after_idle(self._apply_responsive_layout)
        self.root.bind("<Configure>", self._on_root_resize, add="+")
        self.root.bind_all("<KeyPress>", self._on_global_keypress, add="+")

        self.status_var = tb.StringVar(value="Ready")
        tb.Label(self.root, textvariable=self.status_var, bootstyle="secondary").pack(anchor="w", pady=(10, 0))
        self.root.bind("<Control-a>", self._handle_select_all)

    def refresh_clients(self) -> None:
        self.all_clients_cache = self.client_controller.list_clients()
        self._refresh_location_options()
        self._apply_client_filter()

    def _apply_client_filter(self) -> None:
        query = self.search_var.get().strip().lower()
        selected_location = self.location_var.get().strip()
        filter_location = (
            selected_location
            and selected_location.lower() != "all locations"
        )
        sorted_clients = sorted(
            self.all_clients_cache,
            key=lambda c: str(c.get("name", "")).strip().lower(),
        )
        if query:
            self.clients_cache = [
                client
                for client in sorted_clients
                if query in str(client.get("name", "")).lower()
                and (
                    not filter_location
                    or str(client.get("location", "")).strip().lower() == selected_location.lower()
                )
            ]
        else:
            if filter_location:
                self.clients_cache = [
                    client
                    for client in sorted_clients
                    if str(client.get("location", "")).strip().lower() == selected_location.lower()
                ]
            else:
                self.clients_cache = sorted_clients

        for item in self.table.get_children():
            self.table.delete(item)

        for client in self.clients_cache:
            self.table.insert(
                "",
                "end",
                iid=str(client["id"]),
                values=(
                    client["name"],
                    f"{float(client['balance']):.2f}",
                    f"{float(client.get('excess_payment', 0.0)):.2f}",
                ),
            )
        if query:
            self.status_var.set(
                f"Showing {len(self.clients_cache)} of {len(self.all_clients_cache)} client(s)."
            )
        else:
            self.status_var.set(f"Loaded {len(self.clients_cache)} client(s).")

    def _refresh_location_options(self) -> None:
        locations = sorted(
            {
                str(client.get("location", "")).strip()
                for client in self.all_clients_cache
                if str(client.get("location", "")).strip()
            },
            key=lambda value: value.lower(),
        )
        options = ["All locations", *locations]
        if self.location_combo is not None:
            self.location_combo.configure(values=options)
        if self.location_var.get() not in options:
            self.location_var.set("All locations")

    def _clear_search(self) -> None:
        if self.search_var.get():
            self.search_var.set("")

    def backup_database(self) -> None:
        default_name = f"{self.db_path.stem}_backup.sqlite3"
        file_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Backup Database",
            defaultextension=".sqlite3",
            initialfile=default_name,
            filetypes=[("SQLite Database", "*.sqlite3 *.db"), ("All files", "*.*")],
        )
        if not file_path:
            return

        try:
            shutil.copy2(self.db_path, file_path)
        except Exception as exc:
            messagebox.showerror("Backup Error", f"Could not create backup:\n{exc}", parent=self.root)
            return

        self.status_var.set(f"Backup created: {file_path}")
        messagebox.showinfo("Backup Complete", f"Database backup saved to:\n{file_path}", parent=self.root)

    def restore_database(self) -> None:
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Restore Database",
            filetypes=[("SQLite Database", "*.sqlite3 *.db"), ("All files", "*.*")],
        )
        if not file_path:
            return

        source_path = Path(file_path)
        if source_path.resolve() == self.db_path.resolve():
            messagebox.showinfo("Restore", "Selected file is already the active database.", parent=self.root)
            return

        try:
            with sqlite3.connect(source_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            required = {"clients", "payments"}
            if not required.issubset(tables):
                messagebox.showerror(
                    "Restore Error",
                    "Selected file is not a valid Partial Payments database.",
                    parent=self.root,
                )
                return
        except Exception as exc:
            messagebox.showerror("Restore Error", f"Could not read selected file:\n{exc}", parent=self.root)
            return

        confirmed = messagebox.askyesno(
            "Confirm Restore",
            "Restoring will replace the current database with the selected file. Continue?",
            icon="warning",
            parent=self.root,
        )
        if not confirmed:
            return

        try:
            shutil.copy2(source_path, self.db_path)
        except Exception as exc:
            messagebox.showerror("Restore Error", f"Could not restore database:\n{exc}", parent=self.root)
            return

        self.refresh_clients()
        self.status_var.set(f"Database restored from: {source_path}")
        messagebox.showinfo("Restore Complete", "Database restored successfully.", parent=self.root)

    def _selected_client(self) -> dict | None:
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning("Selection required", "Select a client first.")
            return None
        if len(selected) > 1:
            messagebox.showwarning("Single selection", "Select only one client for this action.")
            return None

        client_id = int(selected[0])
        for client in self.clients_cache:
            if client["id"] == client_id:
                return client
        return None

    def _selected_clients(self) -> list[dict]:
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning("Selection required", "Select at least one client.")
            return []

        selected_ids: set[int] = {int(item_id) for item_id in selected}
        clients_by_id = {client["id"]: client for client in self.clients_cache}

        ordered_clients: list[dict] = []
        for row_id in self.table.get_children():
            client_id = int(row_id)
            if client_id in selected_ids and client_id in clients_by_id:
                ordered_clients.append(clients_by_id[client_id])

        return ordered_clients

    def _handle_select_all(self, _event=None) -> None:
        self.select_all_clients()

    def select_all_clients(self) -> None:
        items = self.table.get_children()
        if not items:
            return
        self.table.selection_set(items)
        self.status_var.set(f"Selected {len(items)} client(s).")

    def clear_selection(self) -> None:
        self.table.selection_remove(self.table.selection())
        self.status_var.set("Selection cleared.")

    def open_add_client(self) -> None:
        def on_submit(_, name, location, item, balance):
            success, message = self.client_controller.create_client(name, location, item, balance)
            if success:
                self.refresh_clients()
                self.status_var.set(message)
            return success, message

        ClientFormDialog(self.root, "Add Client", on_submit, show_item=True, show_balance=True)

    def open_edit_client(self) -> None:
        client = self._selected_client()
        if not client:
            return

        def on_submit(client_id, name, location, item, balance):
            success, message = self.client_controller.edit_client(client_id, name, location, item, balance)
            if success:
                self.refresh_clients()
                self.status_var.set(message)
            return success, message

        ClientFormDialog(
            self.root,
            "Edit Client",
            on_submit,
            client,
            show_item=False,
            show_balance=False,
        )

    def delete_client(self) -> None:
        client = self._selected_client()
        if not client:
            return

        confirmed = messagebox.askyesno(
            "Delete client",
            f"Delete {client['name']} and all their payments?",
            icon="warning",
        )
        if not confirmed:
            return

        success, message = self.client_controller.remove_client(client["id"])
        if success:
            self.refresh_clients()
            self.status_var.set(message)
            return

        messagebox.showerror("Error", message)

    def open_add_payment(self) -> None:
        client = self._selected_client()
        if not client:
            return
        if float(client.get("balance", 0.0)) <= 0:
            messagebox.showerror(
                "Cannot Add Payment",
                "Cannot add payment when current balance is 0.",
                parent=self.root,
            )
            return

        existing_items = self.payment_controller.list_client_items(client["id"])

        def get_payments_for_item(item_value: str):
            return self.payment_controller.list_client_payments(client["id"])

        def on_submit(payments, item, note):
            success, message = self.payment_controller.create_calendar_payments(client["id"], item, note, payments)
            if success:
                self.refresh_clients()
                self.status_var.set(message)
            return success, message

        PaymentDialog(
            self.root,
            client["name"],
            on_submit,
            item=client.get("item") or "",
            existing_items=existing_items,
            get_payments_for_item=get_payments_for_item,
        )

    def open_add_balance(self) -> None:
        client = self._selected_client()
        if not client:
            return
        existing_items = self.payment_controller.list_client_items(client["id"])

        def on_submit(amount, item, excess_target_item):
            normalized_target = str(excess_target_item or "").strip()
            if normalized_target == "Unspecified":
                normalized_target = ""
            success, message = self.client_controller.increase_balance(
                client["id"],
                amount,
                item,
                excess_target_item=normalized_target or None,
            )
            if success:
                self.refresh_clients()
                self.status_var.set(message)
            return success, message

        AddBalanceDialog(
            self.root,
            client["name"],
            on_submit,
            existing_items=existing_items,
            excess_amount=float(client.get("excess_payment", 0.0) or 0.0),
        )

    def _on_table_scroll(self, *args) -> None:
        self.table.yview(*args)

    def _on_table_configure(self, _event=None) -> None:
        width = self.table.winfo_width()
        if abs(width - self.last_table_width) > 2:
            self.last_table_width = width
            self._update_table_columns()

    def _on_root_resize(self, _event=None) -> None:
        if _event is not None and _event.widget is not self.root:
            return
        if self.resize_after_id is not None:
            self.root.after_cancel(self.resize_after_id)
        self.resize_after_id = self.root.after(60, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self.resize_after_id = None
        self._arrange_toolbar()
        self._update_table_columns()

    def _arrange_toolbar(self) -> None:
        if self.toolbar is None or self.left_toolbar is None or self.right_toolbar is None:
            return

        width = self.root.winfo_width()
        stacked = width < 1180
        if stacked == self.toolbar_stacked:
            return

        self.left_toolbar.pack_forget()
        self.right_toolbar.pack_forget()
        if stacked:
            self.left_toolbar.pack(fill=X, anchor="w")
            self.right_toolbar.pack(fill=X, anchor="e", pady=(8, 0))
        else:
            self.left_toolbar.pack(side=LEFT, fill=X, expand=True)
            self.right_toolbar.pack(side=RIGHT)
        self.toolbar_stacked = stacked

    def _update_table_columns(self) -> None:
        table_width = self.table.winfo_width()
        if table_width <= 1:
            return

        available_width = max(1, table_width)
        min_total = sum(self.column_min_widths.values())

        widths: dict[str, int] = {}
        if available_width <= min_total:
            for col in self.columns:
                # Keep readable minimums; horizontal scrollbar handles smaller windows.
                widths[col] = self.column_min_widths[col]
        else:
            extra = available_width - min_total
            for col in self.columns:
                widths[col] = self.column_min_widths[col] + int(extra * self.column_weights[col])

        used = sum(widths.values())
        if used != available_width:
            last_col = self.columns[-1]
            widths[last_col] = max(self.column_min_widths[last_col], widths[last_col] + (available_width - used))

        for col in self.columns:
            self.table.column(col, width=widths[col], stretch=False)

    def _client_by_row_id(self, row_id: str) -> dict | None:
        client_id = int(row_id)
        for client in self.clients_cache:
            if client["id"] == client_id:
                return client
        return None

    def _emoji(self, name: str, fallback: str) -> str:
        item = Emoji.get(name)
        if item is None:
            return fallback
        return item.char

    def _on_table_click(self, event) -> None:
        region = self.table.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.table.identify_row(event.y)
        if not row_id:
            return
        self.table.selection_set(row_id)
        client = self._client_by_row_id(row_id)
        if client:
            self._open_client_info_dialog(client)

    def _forget_client_info_dialog(self, client_id: int) -> None:
        self.client_info_dialogs.pop(int(client_id), None)

    def _open_client_info_dialog(self, client: dict) -> None:
        client_id = int(client.get("id"))
        existing = self.client_info_dialogs.get(client_id)
        if existing is not None:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_set()
                existing.refresh()
                return
            self.client_info_dialogs.pop(client_id, None)

        dialog = ClientInfoDialog(
            self.root,
            client,
            client_controller=self.client_controller,
            payment_controller=self.payment_controller,
            on_refresh=self.refresh_clients,
            on_close=self._forget_client_info_dialog,
        )
        self.client_info_dialogs[client_id] = dialog

    def _on_global_keypress(self, event) -> None:
        if event is None:
            return
        now = time.time()
        if now - self.scan_last_ts > self.scan_timeout_seconds:
            self.scan_buffer = ""
        self.scan_last_ts = now

        key = str(getattr(event, "keysym", "") or "")
        text = str(getattr(event, "char", "") or "")

        if key == "Return":
            code = self.scan_buffer.strip()
            self.scan_buffer = ""
            if code:
                self._handle_scanned_barcode(code)
            return

        if len(text) == 1 and text.isprintable():
            self.scan_buffer += text

    def _handle_scanned_barcode(self, barcode_value: str) -> None:
        client = self.client_controller.get_client_by_barcode(barcode_value)
        if not client:
            return

        # Open the dialog immediately — before any table refresh that might
        # trigger additional Tk trace callbacks and delay focus.
        self._open_client_info_dialog(client)

        # Refresh the table so the list stays current.
        self.refresh_clients()
        self.location_var.set("All locations")

        # Temporarily remove the search trace so setting "" doesn't fire a
        # second _apply_client_filter that could steal focus from the dialog.
        self.search_var.trace_remove("write", self._search_trace_id)
        self.search_var.set("")
        self._search_trace_id = self.search_var.trace_add("write", lambda *_: self._apply_client_filter())
        self._apply_client_filter()

        # Highlight the matching row in the table.
        row_id = str(client["id"])
        if row_id in self.table.get_children():
            self.table.selection_set(row_id)
            self.table.focus(row_id)
            self.table.see(row_id)