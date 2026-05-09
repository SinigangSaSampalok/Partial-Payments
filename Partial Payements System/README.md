# Partial Payments System (Tkinter + ttkbootstrap + SQLite)

Desktop app for tracking clients, recording partial payments, and automatically deducting payments from client balances.

## Features
- Add client
- Edit client
- Delete client
- Record partial payment per client
- Record partial payment for multiple selected clients (bulk, sequential per client)
- Auto-deduct payment from current balance
- Keep client record even when balance reaches 0
- Add new balance to existing clients
- Track excess payments as credit and auto-apply credit when new balance is added while current balance is zero
- View payment history per client
- Select all clients and bulk delete
- SQLite database storage
- MVC architecture

## Tech Stack
- Python
- tkinter + ttkbootstrap (GUI)
- SQLite (`sqlite3`)

## MVC Structure
- `src/models/`: data access and business persistence logic
- `src/controllers/`: validation and workflow rules
- `src/views/`: GUI and dialogs
- `src/database/`: SQLite initialization and connection

## Run
1. Install dependencies:
```powershell
pip install -r requirements.txt
```
2. Start app:
```powershell
python main.py
```

## Notes
- Database file is created automatically at:
  - `src/database/partial_payments.sqlite3`
- If payment amount is larger than current balance, only the remaining balance is deducted and recorded.
- Any amount beyond current balance is saved as `excess_payment` credit.
- If a client currently has zero balance and you add new balance, available excess credit is automatically applied.
- Use `Select All` or `Ctrl+A` to quickly select rows for bulk actions.
- Bulk add payment now runs first-to-last based on current table order, and `Enter` confirms each client payment in sequence.
