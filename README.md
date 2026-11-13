# SQI POS

A local-network POS with products, inventory, cash sales, acknowledgement receipts, and daily reporting. Two Windows PCs share one SQLite database through a local router. The Start SQI POS icon opens a dedicated app window without browser tabs or an address bar.

**Version:** 0.1 · **Server:** Python, Flask, Cheroot · **Database:** SQLite · **Interface:** HTML, CSS, JavaScript

## Features

| Area | Available in version 0.1 |
| --- | --- |
| Products | Unique SKU, optional barcode, description, category, unit, locked company unit price, adjustable selling price history, product images, and Excel bulk upload |
| Inventory | Opening stock, stock receipts, sales-linked deductions, returns, and movement history |
| Checkout | Optional fullscreen with no sidebar, name/SKU/barcode search, a dedicated scanner or manual barcode field with quantity confirmation before adding, saved tickets, cashier selection from manager-set discount rates, cash paid, calculated change, and SQI-branded acknowledgement receipts with company contact details and office hours |
| Duplicate protection | One sale per ticket, replay of repeated payment requests, and warnings for matching recent baskets |
| Accounts | Named managers/cashiers, account-only sign-in, password confirmation for sensitive changes, and expiring sessions |
| Events, days, shifts | IT System Administrator starts and archives events; managers open and close days; cashiers open and close shifts. The next event keeps products but starts with zero stock. |
| Corrections | Manager-approved returns/voids, refunds based on the amount paid after any discount, and explicit restocking |
| Reports | Business-date span, day, product, category, and cashier filters, with a formatted Excel workbook export |
| Audit and recovery | Append-only audit events, verified database backups, and restore into a new folder |

## Requirements

- **Main PC:** Windows, Python 3.11 or later available through `python` or `py`, and Chrome or Microsoft Edge. Tested with Python 3.13.
- **Second PC:** Chrome or Microsoft Edge connected to the same router as the main PC; Python and its printer driver are also needed for the optional local USB print helper. No second database or POS server.
- **Network:** Private Wi-Fi or Ethernet; LAN mode uses HTTPS.
- **Storage:** Keep the live database on the main PC's internal drive and configure a separate backup destination.

## Install and start on the main PC

**Install Python first.** Install [Python Install Manager](https://www.python.org/downloads/windows/), open a new terminal, then run:

```powershell
py install 3.13
py -3.13 --version
```

For a traditional Python installer, enable **Add python.exe to PATH** instead. If installation says “Python was not found,” see the [troubleshooting instructions](docs/two-pc-setup.md#if-installation-says-python-was-not-found). Disabling the Microsoft Store shortcut alone does not install Python.

Then clone the repository, or use **Code → Download ZIP** on GitHub and extract the source. Git is only needed for the clone option. In PowerShell, open the project folder and run:

```powershell
git clone https://github.com/ginflorita/sqi-pos.git
cd sqi-pos
.\Install-POS.cmd
.\Start-POS.cmd
```

If you downloaded the offline Windows ZIP, skip the `git clone` and `cd sqi-pos` commands above, extract the complete ZIP, and double-click `Install-POS.cmd`. When Python is missing, the bundled official installer runs for the current Windows user. Installation creates `.venv` and uses the bundled dependency wheels without internet. Complete first-time setup with `Start-POS.cmd`. After the two-PC HTTPS setup, run `Setup-Host-Shortcut.cmd` once on the main laptop. It creates a **Start SQI POS** desktop icon and starts the server automatically when that Windows user signs in. The icon also starts the LAN HTTPS server if needed, waits until it is ready, and opens a dedicated Chrome or Edge app window. `Start-POS.cmd` remains available for manual troubleshooting.

**Keeping existing records:** back up and stop the old server before moving its complete `data` folder to a new main laptop. Preserve `data`, `backups`, certificates, and print-helper configuration when updating application files. GitHub contains application code, not your live records.

Open **http://localhost:8765** on the main PC. Keep the server running while either cashier is working.

For the second laptop, complete the [two-PC HTTPS setup](docs/two-pc-setup.md), extract a fresh copy of the application files there, and run `Create-Cashier-Shortcut.cmd` on that laptop with the main laptop's reserved network address. It creates a **SQI POS Cashier** desktop icon that opens the shared POS in an app window. Do not copy the main laptop's `data`, backups, or private `pos.key` file. The second laptop runs no POS server and has no separate database. The main laptop must be signed in to Windows, awake, and connected to the router.

### First-time setup

1. Create your manager account using a password of at least 12 characters.
2. Enter the bazaar name and confirm its currency and timezone.
3. Add categories, products, selling prices, and optional photos.
4. Record opening stock in **Inventory**.
5. Open the first bazaar day and your cashier shift, including opening cash.
6. Add items, review payment, enter cash received, and confirm the sale.

You create the production manager credentials during setup. Setup must be completed on the main PC.

Signed-in managers can add or edit products and photos without entering their password again. Each product has a company unit price that is locked after creation and a selling price that checkout charges. Existing products start with both prices equal to the former current price. A reason is required when changing an existing selling price. Product changes record the manager, time, and changed details in the audit trail. Financial, stock, and account approvals retain password confirmation.

For a large product list, open **Products → Add from Excel** and choose an `.xlsx` workbook containing `ITEM CODE` and `DESCRIPTION` headers. Only those two columns are read. Select **Show uploaded products** to preview every valid row without saving it. Review the list, then select **Save all, set up later** above the list; repeated and existing SKUs are skipped. Imported rows remain under **Products saved for later** with image, category, price, and quantity blank. Use **Set up** whenever you are ready to add selling details and an opening quantity; the item stays out of checkout until then.

The eight-column masterlist uses `tools/import_masterlist.py` for a reviewed local import. It maps item code, barcode, long and short descriptions, unit code and description, price, and category into separate database fields. Rows with missing prices or conflicting item codes/barcodes remain pending, with their Excel row numbers in a review file. The workbook has no stock quantity column, so imported products begin with zero stock until a manager records stock.

Managers record **Opening stock** once for a new item and **Stock in** for received deliveries. In **Inventory → Record movement**, they can search and select up to 200 items, enter a quantity beside each, review the total, confirm with their password, and post them together. The POS records `Opening stock` or `Stock received` automatically, along with the manager and time. Completed sales deduct stock; approved returns can restock it. Manual stock-out, physical count resets, and signed adjustments are disabled so the balance follows recorded transactions.

The `ginflorita` account is the **IT System Administrator**. It retains all manager features. Only the signed-in `ginflorita` user can change that account's display name or password; its role and active status are locked. An existing `ginflorita` manager account is upgraded when the main POS server next starts.

![First-time POS setup](docs/screenshots/first-setup.png)

## Connect the second PC

| Device | Responsibility |
| --- | --- |
| Main PC | Runs the server, holds the database, and can also operate a cashier browser |
| Second PC | Opens the host's POS address in its browser and signs in with its own cashier account |

Follow the **[Two-PC setup guide](docs/two-pc-setup.md)** to create and trust the local HTTPS certificate, allow the private-network connection through Windows Firewall, and connect the second laptop.

After certificate setup, stop the existing server and start LAN mode:

```powershell
.\Start-POS.cmd --lan --cert certs/pos.crt --key certs/pos.key
```

The main PC uses `https://localhost:8765`; the second PC uses `https://<MAIN-PC-IP>:8765`. Replace the placeholder with the main PC's actual router-network address. Reserve that address in the router and keep the host awake and connected.

## Daily operation

1. The manager opens the numbered business day.
2. Each cashier signs in and opens a shift with their own drawer's starting cash.
3. Search or scan products, add quantities, review cash payment, and issue the saved sale's receipt.
4. Use **Transactions** to review receipts and process manager-approved corrections.
5. Complete, transfer, or cancel open orders, then count cash and close each shift.
6. Review reports, close the business day, and check that its backup succeeded.

After an uncertain payment response, refresh the same browser to check the existing ticket. It retrieves the original receipt when the sale committed. Use one ticket for each physical customer purchase.

### Sales report export

In **Reports**, choose the date range and any day, cashier, category, or item filters, then click **Download Excel report**. The file is named `SQI-POS-Event-###-(YYYY-MM-DD-to-YYYY-MM-DD).xlsx`. Its **Summary** sheet shows overall sales and daily net sales. **Days** shows receipts, units, gross sales, discounts, tax, refunds, and net sales by business day. **Items**, **Category**, and **Cashier** each have their own breakdown and totals. Refunds appear on the day they were processed and under the cashier who processed them. Sales exclude cash in/out and drawer variance; use **Cashier shifts** for cash reconciliation.

### Barcode scanners and manual search

Save each product's unique barcode under **Products**. In **Checkout**, use **Search by name, SKU, or barcode** to browse matching products, or click **Scan or type barcode** and scan a label or type its code, then press **Enter** or **Find item**. A scanner that acts as a keyboard and sends Enter after the code uses the same field. Matching opens **Choose quantity**; nothing is added until the cashier confirms. If the scanner has no Enter suffix, press **Find item** after scanning. Each cashier laptop uses its own scanner; the second laptop still connects to the single POS server on the main laptop.

The checkout product area shows 24 matching products at a time with **Previous** and **Next** controls. Search and category filters cover the full catalog, including products on other pages. The order stays beside the catalog on wide screens and moves above it on narrow screens.

## Backups and restore

Verified online backups run every 15 minutes while the server is running, at day close, and on request. The default folder is `backups/`. Set a separate drive or destination when starting the host:

```powershell
.\Start-POS.cmd --backup-dir E:\BazaarBackups
```

For LAN use, combine `--backup-dir` with the HTTPS flags. Backups include product images. The restore tool verifies a snapshot and restores into a new directory, preserving the original live data. Follow **[Operations](docs/operations.md)** for the full backup, restore, and laptop-recovery procedures.

Live databases, backups, certificate files, environment files, and installed dependencies are excluded from Git.

## Tests

After installing dependencies, run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The recorded verification has **32 passing tests**, including concurrent checkout, last-unit stock competition, payment retries, catalog permissions, Excel product imports, product/stock reason rules, returns, and restore. The browser recovery check also confirmed one sale, one payment, and one stock deduction after a simulated failed response. See the **[verification record](docs/verification.md)**.

## Optional demo

Create sample products and sales in a separate `.demo/` database:

```powershell
.\.venv\Scripts\python.exe tools\demo.py
.\Start-POS.cmd --data-dir .demo --backup-dir .demo/backups --port 8766
```

Open **http://localhost:8766**. Demo credentials are `demo` / `Bazaar-demo-2026!`; they apply only to the sample workspace. Any browser can sign in with a valid account; no laptop approval is required. Sample data is kept separate from the production database.

## Current scope

Version 0.1 supports cash payments, whole quantities, one active bazaar, one open ticket per cashier, separate cash drawers, SKU/description imports from Excel, and multiple manager-set percentage discounts for an entire order. In **Settings → Checkout discounts**, the manager adds or deletes rates from 0.01–99% with password confirmation. At checkout, the cashier selects **No discount** or one of the saved rates. Deleting a rate clears it from open orders and requires another payment review; completed receipts retain their original discount. Reports show discounts, and refunds use the discounted amount actually paid. Added tax remains zero. Fractional quantities, non-cash payments, statutory discount/tax handling, and additional bazaar creation remain planned.

Before real trading, confirm the bazaar's currency, tax treatment, receipt content, and printer layout, and test both physical PCs, the router, external backups, restore, and power interruption. The host is a single point of availability. Application audit rules do not prevent a host administrator from changing local files.

## Documentation

- [Two-PC setup](docs/two-pc-setup.md)
- [Installation, daily operation, backup, and restore](docs/operations.md)
- [POS plan and business rules](docs/pos-plan.md)
- [Database schema: 28 tables with descriptive primary keys](docs/database-schema.md)
- [Executable SQL schema](pos/schema.sql)
- [Verification and remaining equipment checks](docs/verification.md)

## Receipt printers on each cashier laptop

For remembered USB printers and automatic printing after payment confirmation, follow [printer setup](docs/printer-setup.md). A manager pairs and selects the printer in Settings, and can disconnect it there. On the POS host, a cashier can start an offline paired helper from **Connect printer** in Checkout without a Windows Administrator prompt. Automatic printing stays off until setup; browser printing remains available. Physical printer output must be verified when hardware is available.
