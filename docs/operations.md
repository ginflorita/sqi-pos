# Installation and operation

## Start the host

Install Python 3.11 or later on Laptop 1. Keep the project on its internal drive, outside OneDrive or other synchronization folders. Run `Install-POS.cmd` with internet available, then `Start-POS.cmd`. Laptop 2 only needs a browser.

Open http://localhost:8765 on the host to create your manager account and bazaar. Confirm currency and timezone. This version uses whole quantities, cash, separate cash drawers, manager-set percentage discount rates, and zero added tax. Confirm tax treatment before real trading. Add categories, products, prices, optional photos, and opening stock.

Product creation, normal product edits, and photo uploads use the signed-in manager session without another password prompt. Set the original company **Unit price** when creating a product; it is locked after saving. **Selling price** starts at the same amount unless the manager enters another amount. Checkout charges the selling price. Changing an existing selling price requires a reason and adds a price-history row; leaving it unchanged does not. The audit records the manager, time, and before/after details automatically. Stock, financial, and account approvals still require password confirmation.

For bulk entry, choose **Products → Add from Excel** and upload an `.xlsx` workbook up to 6 MB. The importer finds `ITEM CODE` and `DESCRIPTION` headers within the first 50 rows and ignores all other columns. Select **Show uploaded products** to preview the valid rows without writing them to the database. Review the list, then select **Save all, set up later** above it; repeated rows and SKUs already in the catalog or saved list are skipped. Saved rows remain under **Products saved for later** with image, category, price, and quantity blank. Select **Set up** whenever you are ready to add category, unit, selling price, opening quantity, availability, and an optional photo. A positive opening quantity creates an audited opening-stock movement. Products without selling details remain safely outside checkout and inventory.

For the eight-column masterlist, stop the POS server and run `python tools/import_masterlist.py "MASTERLIST - INCOMPLETE.xlsx" --database data/pos.sqlite3` to preview counts and SHA256. Run again with `--apply --expected-sha256 <preview hash>` to create a verified backup and import valid rows in one transaction. The script maps ITEM CODE → `products.sku`, BARCODE → `products.barcode`, LONG DESCRIPTION → `products.description`, SHORT DESCRIPTION → `products.short_description`, UNIT → `products.unit`, UNIT DESCRIPTION → `products.unit_description`, UNIT PRICE → locked `products.unit_price_minor`, and CATEGORY → `categories.name`/`products.category_id`. The initial selling price in `product_prices.amount_minor` is set equal to UNIT PRICE and may be adjusted later. The script leaves missing-price and duplicate-identifier rows as pending drafts or in the review file under `data/imports`. New products start at zero stock; record received quantities separately in Inventory. Restart the POS after import.

For **Stock in** and **Opening stock**, open **Inventory → Record movement**. Choose a type, search products by name, SKU, or barcode, and select up to 200 items across the list pages. Select **Continue**, enter the quantity to add beside every item, check the review warning, and confirm with the manager password. All selected lines post in one transaction; an invalid line prevents the whole posting. A posted movement cannot be undone from this form. The form does not ask for a reason; the POS records `Stock received` or `Opening stock` automatically. Completed sales reduce stock, and approved returns can restock it. Manual stock-out, physical count resets, and signed adjustments are unavailable. Every stock posting records its quantities, manager, time, and approval; duplicate-request checks remain enforced. A mismatch between the shelf and the recorded total must be investigated rather than silently corrected.

To offer discounts, a manager opens **Settings → Checkout discounts → Add rate**, enters a percentage from 0.01% to 99% (up to two decimal places), and confirms with their password. Add several rates as needed; duplicate percentages are rejected. The manager can disable or enable a rate with password confirmation. At checkout, the cashier selects **No discount** or one active rate under the order subtotal. The reduced total appears before payment. Disabling a rate clears it from open orders, forcing another payment review; the disabled rate remains in settings and saved receipts and reports keep the rate and amount charged at the time of sale.

The server runs Cheroot with eight worker threads and debug mode disabled. Startup checks SQLite integrity, foreign keys, and stock-ledger reconciliation. It stops if these fail. Local HTTP binds only to loopback; LAN mode requires HTTPS.

## Connect two laptops

Use a trusted router and a private Wi-Fi/Ethernet network. Reserve a stable private IP for Laptop 1. Replace the example `192.168.1.10` below with its actual assigned address. The server trusts localhost, the host computer name, and host IPs resolved at startup; restart after an IP change.

Create a certificate on the host:

```powershell
python tools/certificate.py --ip 192.168.1.10
```

This creates `certs/pos.crt` and `certs/pos.key` with a one-year expiry. Keep the private key on the host under a protected owner account. Copy only `pos.crt` to Laptop 2. On both laptops, have the owner inspect the certificate, compare its SHA256 fingerprint with the tool output, and import it into the current user's Trusted Root Certification Authorities store. Never share `pos.key`.

Start LAN mode:

```powershell
.\Start-POS.cmd --lan --cert certs/pos.crt --key certs/pos.key
```

Use https://localhost:8765 on the host and https://192.168.1.10:8765 on Laptop 2. Keep a consistent address in each browser for cookies and pending-payment recovery. When switching from HTTP to HTTPS, sign out and back in to refresh cookies with their Secure flag. Fix certificate warnings before entering credentials.

The owner must allow inbound TCP port 8765 for Python on the Windows Private network profile, restricted to the local subnet. Do not enable internet port forwarding. The application does not change firewall or certificate trust settings automatically.

Create the second cashier in Team. Sign in on Laptop 2 with that account; no laptop name or approval is needed. Each browser profile keeps its own shift and printer pairing. Only one shift per cashier and browser profile may be open.

## Checkout fullscreen

Click **Checkout** in the sidebar to choose **Open fullscreen** or **Standard view**. Cancel, the close button, or Escape dismisses this choice without leaving the current section. Checkout also has a **Fullscreen** button.

Fullscreen hides the sidebar and workspace header, giving products and Current order the full page. Use **Exit fullscreen** or Escape to restore navigation. Choose quantity and Set quantity have an on-screen number pad on the right; a keyboard can still be used. While Checkout is open, the browser checks the product catalog and stock every 30 seconds in the background; checkout checks stock again before saving a sale. This background check does not keep an idle login active. The app requests browser fullscreen when supported; if the browser declines, the expanded checkout layout still works. Leaving Checkout or signing out restores the standard layout. Reloading the browser starts in the standard view.

Current order uses compact text-only rows with **SKU | DESC | QTY | TOTAL**. Select **View** under DESC to open the full description, SKU, and unit price. Use the +/− controls under QTY to adjust an existing line. Product thumbnails remain in Browse products; they are omitted from the order rows.

## Daily workflow

1. The manager opens Day 1, Day 2, etc. with the business date. The date must follow the prior day. It remains open across midnight until explicitly closed.
2. Each cashier opens a shift with the actual starting cash in their own drawer.
3. Search by product name, SKU, or barcode and click a product. For a scanner or manually typed code, use the dedicated **Scan or type barcode** field; Enter or **Find item** opens the exact matching product. A keyboard-style scanner can send Enter automatically. In **Choose quantity**, enter **Quantity to add**, review the amount, and confirm **Add to order**. Clicking or scanning a product alone does not add it; Cancel or Escape leaves the order unchanged. Existing quantities are shown separately, and additional quantities cannot exceed remaining available stock. Confirmed cart changes save to the host; available stock is rechecked at checkout.
4. Review payment, enter cash paid, verify change, and select **Confirm payment**. A **Yes / No** dialog shows the total, amount paid, and change. **Yes** submits the payment; **No**, Escape, or closing the confirmation returns to the payment form with its amount retained. No payment request is created before Yes. The receipt comes from the committed sale. **Print / save PDF** opens printing directly, with no reason prompt. Each request automatically records `Customer copy`, the receipt, user, laptop, and time in the audit. Browser printing cannot prove that paper actually printed.
5. Complete, transfer, or cancel open tickets before closing shifts. Count actual cash. Variances are retained for manager review.
6. Close every shift and ticket before closing the day. Check the backup result after day close.

Use one ticket per physical customer purchase. One ticket can produce only one sale; retries retrieve that sale. Identical baskets sold within two minutes require a separate-purchase confirmation. The application cannot recognize physical customers.

### Acknowledgement receipt branding

Receipts and their print/PDF layout show the supplied SQI logo at the top, with **SQI Group Int'l. Corp - Philippines** directly beneath it. A compact footer below the totals shows head office **18 Pineapple Rd, Malabon, 1475 Metro Manila, Philippines**, followed by two aligned columns: telephone **8-364-7561** beside **Website: https://sqigroup.ph**, then **Office Hours: 9:00 AM – 6:00 PM** beside **Monday – Saturday**. The receipt number sits directly below ACKNOWLEDGEMENT RECEIPT, without the extra bazaar/name line. Receipt details show one business date (without Day 1 or a repeated timestamp), cashier, items, totals, cash, and change. New receipts show the product's saved short description, or its long description when no short description is available. Earlier receipts keep their original saved wording. The head office address is left-aligned with the footer columns.

The logo is bundled at `static/sqi-logo.png`, so displaying or printing it needs no connection to the source network share or internet. The same receipt layout is used when viewing saved receipts and requesting a print/PDF copy. Printing waits for the logo image to decode. Check the final paper layout on the actual receipt printer.

Receipt numbers use the `SQI` prefix, for example `SQI-001-000009`. Existing `BZ` numbers are displayed with the `SQI` prefix on receipts, transaction lists, duplicate warnings, and correction forms, preserving their numeric suffix. Original historical identifiers remain stored unchanged; new sales store the `SQI` number directly.

### Orders and corrections

Transfer orders using the icon beside the ticket number. The receiving cashier needs an open same-day shift and no current order, then refreshes their counter. Only the current owner and laptop can confirm payment.

After a lost payment response, keep the same browser and ticket. Refresh when connected: the app checks the saved pending request and retrieves the original receipt if committed, or allows retry of that request. Resolve its outcome before starting a new order. Checkout pauses if the host or network is unavailable.

Managers can open original receipts in Transactions to return items or void the full sale, with password confirmation and a reason. Returned quantity cannot exceed the remaining sold amount. Voids are unavailable after partial returns. Restocking is explicit; damaged goods can have zero restock. Refunds use the original price and the current day's shift.

The return form automatically shows each item's refund and **Refund to customer** as quantities change. Refunds use the amount actually paid after any discount; odd cents are distributed across the sold units so returning all units refunds the full paid line amount. Restock quantity only changes inventory and does not change the refund. Invalid or excessive return quantities show a validation message instead of a misleading total. Review the amount before **Record correction**; the server calculates and validates the saved refund, and the cashier physically gives the cash to the customer.

If a cashier's laptop is unavailable, the manager can use **Cashier shifts → Manager close** from a signed-in browser. Count the physical drawer, record a reason, and confirm the manager password. If the shift has an unpaid order, review its items and explicitly confirm cancellation; a changed order requires a fresh review. The server serializes closure against checkout and records both cancellation and closure in the audit. This allows a lost-laptop shift to be reconciled without rewriting its sales.

## Events, days, and shifts

The IT System Administrator (`ginflorita`) controls the overall event in **Management → Events**. A manager opens and closes business days within the event. Each cashier opens and closes a shift within an open day. The initial installed database begins with **Event 1**; the administrator can rename it before ending it.

To finish an event, complete or cancel unpaid orders, close every cashier shift, close the business day, and resolve pending receipt print jobs. The administrator then reviews the cash and reports, selects **End event**, and confirms with their password. The POS closes the event and creates a verified database archive. If archiving fails, **Retry archive** must succeed before another event can start.

**Start event** keeps the product list, categories, images, current prices, saved product drafts, accounts, and printer settings. It resets the current stock balance to zero. The manager then opens Day 1, and staff record opening stock for the new event. Current Transactions, Reports, Inventory, Cashier shifts, and Audit trail show only the new event. Past events remain read-only under **Events**, with report, inventory, and audit views and an Excel report download. Verified database archives retain the complete original records. Receipt numbers continue to use globally increasing day and ticket IDs, so they do not repeat across events.

## Backups

Online snapshots include product images and receive integrity/foreign-key checks and a SHA256 checksum. Backups run every 15 minutes while the server runs, at day close, and on request. Settings shows runs/failures. Old backups are retained until the owner manages retention.

The default `backups/` folder is on the same drive. Configure a separate drive to protect against host-drive loss:

```powershell
.\Start-POS.cmd --backup-dir E:\BazaarBackups
```

Add this option to the LAN command when using HTTPS. `POS_BACKUP_DIR` is an alternative environment setting. Check available space, write access, drive connection, and protection from cashier access. Loss after a drive failure extends back to the last usable external backup.

Before updates, create a verified backup and stop the server. Retain matching application source and dependency requirements. Do not copy only the live `.sqlite3` file while open; its WAL may contain committed data.

## Restore

Stop the server and checkout on both laptops. Preserve current data and the original backup. Restore to a new folder that does not exist:

```powershell
python tools/restore.py E:\BazaarBackups\pos-20261019-180000-1.sqlite3 --output F:\BazaarRecovered
```

The tool verifies integrity, foreign keys, schema version, and stock reconciliation, revokes copied sessions, and adds a restore audit event. It refuses to overwrite an existing destination. Start the recovered data with:

```powershell
.\Start-POS.cmd --data-dir F:\BazaarRecovered --backup-dir E:\BazaarBackups
```

Compare receipt counts, last receipt, stock, and shifts against the backup point. For practice, use a separate port and do not trade from the restored copy. For actual recovery, add normal LAN certificate flags after verification. Sales after the backup are absent; reconcile paper receipts and cash before resuming without blindly re-entering receipts that already exist.

Sign in to the restored server with a valid account. A replacement browser does not require laptop approval. Re-pair its printer if automatic printing is used. Reconcile any shift left on the unavailable laptop through Manager close before opening a new shift for that cashier.

## Equipment readiness

Keep the host powered and awake. Protect its data, code, keys, and backups from ordinary cashier Windows accounts. The host remains a single point of availability. Run `Setup-Host-Shortcut.cmd` once to create a per-user Windows sign-in startup shortcut and a desktop icon that starts the server if needed. This is not a Windows service: the host user must be signed in. `Start-POS.cmd` remains available for manual troubleshooting.

Before the bazaar, test the actual router, both laptops, printer, external backup destination, and a power interruption. Confirm receipt content, currency, tax treatment, and business dates. An administrator can edit local files; the audit is not tamper-proof against host administrator access. Physical cash handover cannot be atomic with a database commit.

## References

[SQLite transactions](https://www.sqlite.org/lang_transaction.html), [WAL](https://www.sqlite.org/wal.html), [online backup API](https://www.sqlite.org/backup.html), and [Flask security](https://flask.palletsprojects.com/en/stable/web-security/).

## Per-laptop receipt printers

See [printer setup](printer-setup.md) for separate USB printers, administrator configuration, helper startup, and interrupted print-job recovery. Print jobs are committed with sales but printer I/O happens afterward; never repeat checkout to repair a print failure. After database restore, re-pair each print helper before enabling automatic printing.
