from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running this module directly: python src/app.py
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ttkbootstrap as tb

from src.controllers.client_controller import ClientController
from src.controllers.payment_controller import PaymentController
from src.database.db import Database
from src.models.client_model import ClientModel
from src.models.payment_model import PaymentModel
from src.views.dialogs import EULADialog
from src.views.main_view import MainView


class PartialPaymentsApp:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parent
        if getattr(sys, "frozen", False):
            local_appdata = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            db_path = local_appdata / "PartialPaymentsSystem" / "partial_payments.sqlite3"
        else:
            db_path = base_dir / "database" / "partial_payments.sqlite3"
        database = Database(db_path)

        client_model = ClientModel(database)
        payment_model = PaymentModel(database)
        client_model.ensure_all_client_barcodes()

        self.client_controller = ClientController(client_model)
        self.payment_controller = PaymentController(payment_model, client_model)

        self.root = tb.Window(themename="litera")
        self.root.title("Partial Payments System")
        self.root.geometry("1280x760")
        self.root.minsize(640, 420)
        self.root.state("zoomed")
        self.root.resizable(False, False)

        self._configure_style()

        self.view = MainView(
            self.root,
            client_controller=self.client_controller,
            payment_controller=self.payment_controller,
            db_path=db_path,
        )

    def _configure_style(self) -> None:
        style = self.root.style
        self.root.configure(background="#bfdcff")

        heading_bg = "#1f5cb8"
        heading_fg = "#ffffff"
        tree_bg = "#ffffff"
        tree_fg = "#1e3557"
        selected_bg = "#2f6fcb"
        selected_fg = "#ffffff"

        # Apply row height to both default and ttkbootstrap color variants.
        style.configure(
            "Treeview",
            rowheight=90,
            font=("Segoe UI", 12),
            foreground=tree_fg,
            background=tree_bg,
            fieldbackground=tree_bg,
        )
        style.configure(
            "primary.Treeview",
            rowheight=90,
            font=("Segoe UI", 12),
            foreground=tree_fg,
            background=tree_bg,
            fieldbackground=tree_bg,
        )
        style.map(
            "Treeview",
            foreground=[("selected", selected_fg)],
            background=[("selected", selected_bg)],
        )
        style.map(
            "primary.Treeview",
            foreground=[("selected", selected_fg)],
            background=[("selected", selected_bg)],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI", 12, "bold"),
            foreground=heading_fg,
            background=heading_bg,
        )
        style.configure("TButton", font=("Segoe UI Semibold", 11), padding=10)
        style.configure(
            "TEntry",
            font=("Segoe UI", 11),
            foreground=tree_fg,
            fieldbackground=tree_bg,
            insertcolor=tree_fg,
        )
        # Action-column buttons: keep row-matching background (normal/selected).
        action_styles = {
            "ActionInfo.TButton": "#0ea5c6",
            "ActionDanger.TButton": "#ef4444",
            "ActionSuccess.TButton": "#00a86b",
            "ActionWarning.TButton": "#e7a12b",
            "ActionInfoSel.TButton": "#8fe6f6",
            "ActionDangerSel.TButton": "#ff9c9c",
            "ActionSuccessSel.TButton": "#8bf0c5",
            "ActionWarningSel.TButton": "#ffd182",
        }
        for style_name, fg in action_styles.items():
            bg = selected_bg if "Sel" in style_name else tree_bg
            style.configure(
                style_name,
                font=("Segoe UI Semibold", 11),
                foreground=fg,
                background=bg,
                borderwidth=0,
                padding=(8, 3),
            )
            style.map(
                style_name,
                foreground=[("active", fg)],
                background=[("active", bg), ("pressed", bg)],
            )
        self.root.tk.call("ttk::style", "configure", "Treeview", "-rowheight", 90)
        self.root.tk.call("ttk::style", "configure", "primary.Treeview", "-rowheight", 90)

    def run(self) -> None:
        eula_dialog = EULADialog(self.root)
        self.root.wait_window(eula_dialog)
        if not eula_dialog.accepted:
            self.root.destroy()
            return

        self.view.refresh_clients()
        self.root.mainloop()
