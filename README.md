# Bazaar POS

Version 0.1: a working local browser POS for two Windows laptops. Laptop 1 runs the Python server and SQLite database on its internal drive. Laptop 2 connects through the router using a browser. Checkout does not need internet.

## Start on this laptop

Run `Start-POS.cmd`, then open **http://localhost:8765**. On a new installation, run `Install-POS.cmd` first; installation needs internet and Python 3.11 or later. This development workspace already has the required runtime packages available.

First setup creates your manager account and records the bazaar name, currency, and timezone. There are no default production credentials. Then add categories/products, record opening stock, open Day 1, and open your cashier shift.

For two laptops, follow [Operations and LAN setup](docs/operations.md). LAN mode requires a trusted local HTTPS certificate. Keep the host powered on and awake while either cashier is working.

## Available now

- Named manager/cashier accounts, laptop approval, password hashing, expiring server sessions, request protection, and login throttling.
- Product SKU/barcode/description/category/unit, versioned prices, and uploaded product images.
- Opening stock, stock in/out, physical counts, signed adjustments, and an append-only inventory ledger.
- Saved purchase tickets, ownership transfer, server-calculated cash totals/change, duplicate-submit protection, and near-duplicate warnings.
- Acknowledgement receipts and audited print/PDF requests through the browser.
- Manager-approved returns/voids, explicit restocking, cash in/out, shifts, cash variance, audited closure of an unavailable cashier's shift, and Day 1/Day 2 closing.
- Sales reports by business-date span, day, product, category, cashier, and laptop, with Excel-compatible CSV exports.
- Audit trail, verified online database backups, and a restore tool that writes into a new directory.

## Current scope

This version uses whole quantities, one active bazaar, one open ticket per cashier, separate cash drawers, and cash payments. Discounts and added tax are zero. Confirm the currency, tax treatment, receipt layout, and printer before real trading. Fractional units, non-cash payments, item imports, tax/discount configuration, and additional bazaar creation are future work.

It has automated integration tests and a browser demonstration. The physical two-laptop router connection, printer, external backup destination, and power-loss rehearsal still need testing on the actual bazaar equipment. Local administrators can alter local files; the audit is not tamper-proof against host administrator access.

## Documents

- [Two-PC setup guide](docs/two-pc-setup.md): connect the second cashier PC, configure HTTPS, and approve its account/laptop.
- [POS plan](docs/pos-plan.md): workflows, business rules, reports, security, recovery, and acceptance criteria.
- [Database schema](docs/database-schema.md): all 28 implemented tables, named IDs, relationships, and integrity rules.
- [Operations](docs/operations.md): installation, LAN setup, daily use, backup, and restore.
- [Verification](docs/verification.md): software checks and remaining equipment checks.
- [Executable database schema](pos/schema.sql).

Run tests with `python -m unittest discover -s tests -v`.

## Separate demonstration

`python tools/demo.py` creates an isolated `.demo/` workspace with sample products and illustrations. It never seeds the main `data/` database. Start it with:

```powershell
python run.py --data-dir .demo --backup-dir .demo/backups --port 8766
```

Demo sign-in: `demo` / `Bazaar-demo-2026!`. A new browser still needs laptop approval. The development preview browser has been approved in the sample database. These credentials apply only to `.demo/`.
