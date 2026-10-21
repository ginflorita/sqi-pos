# Installation and operation

## Start the host

Install Python 3.11 or later on Laptop 1. Keep the project on its internal drive, outside OneDrive or other synchronization folders. Run `Install-POS.cmd` with internet available, then `Start-POS.cmd`. Laptop 2 only needs a browser.

Open http://localhost:8765 on the host to create your manager account and bazaar. Confirm currency and timezone. This version uses whole quantities, cash, separate cash drawers, and zero added tax/discounts. Confirm that tax treatment before real trading. Add categories, products, prices, optional photos, and opening stock.

Product creation, normal product edits, and photo uploads use the signed-in manager session without another password prompt. A new product's initial price gets an automatic audit reason. Changing an existing selling price requires a reason; leaving its price unchanged does not. The audit records the manager, time, and before/after details automatically. Stock, financial, and account approvals still require password confirmation.

For bulk entry, choose **Products → Add from Excel** and upload an `.xlsx` workbook up to 6 MB. The importer finds `ITEM CODE` and `DESCRIPTION` headers within the first 50 rows and ignores all other columns. Select **Add & save all** to save every valid row at once; repeated rows and SKUs already in the catalog or saved list are skipped. Valid rows remain under **Products saved for later** with image, category, price, and quantity blank. Select **Set up** whenever you are ready to add category, unit, selling price, availability, and an optional photo. Products without selling details remain safely outside checkout and inventory.

For **Stock in** and **Opening stock**, the reason is optional. Leave it blank to record `Stock received` or `Opening stock` automatically, or enter a delivery note. **Stock out**, **Physical count**, and **Signed adjustment** require an explanation. Every stock posting still records its quantities, manager, time, and approval; duplicate-request and negative-stock checks remain enforced.

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

Create the second cashier in Team & laptops. Sign in on Laptop 2 and name it. The host manager approves the pending laptop. Unapproved laptops cannot access the catalog or checkout. Clearing cookies or switching profiles requires approval again. Only one shift per cashier and laptop may be open.

## Checkout fullscreen

Click **Checkout** in the sidebar to choose **Open fullscreen** or **Standard view**. Cancel, the close button, or Escape dismisses this choice without leaving the current section. Checkout also has a **Fullscreen** button beside **Refresh stock**.

Fullscreen hides the sidebar and workspace header, giving products and Current order the full page. Use **Exit fullscreen** or Escape to restore navigation. Refresh stock keeps the selected view and saved order. The app requests browser fullscreen when supported; if the browser declines, the expanded checkout layout still works. Leaving Checkout or signing out restores the standard layout. Reloading the browser starts in the standard view.

Current order uses compact text-only rows with **SKU | DESC | QTY | TOTAL**. Select **View** under DESC to open the full description, SKU, and unit price. Use the +/− controls under QTY to adjust an existing line. Product thumbnails remain in Browse products; they are omitted from the order rows.

## Daily workflow

1. The manager opens Day 1, Day 2, etc. with the business date. The date must follow the prior day. It remains open across midnight until explicitly closed.
2. Each cashier opens a shift with the actual starting cash in their own drawer.
3. Search products/SKUs and click a product, or scan a barcode and press Enter. In **Choose quantity**, enter **Quantity to add**, review the amount, and confirm **Add to order**. Clicking a product alone does not add it; Cancel or Escape leaves the order unchanged. Existing quantities are shown separately, and additional quantities cannot exceed remaining available stock. Confirmed cart changes save to the host; available stock is rechecked at checkout.
4. Review payment, enter cash paid, verify change, and select **Confirm payment**. A **Yes / No** dialog shows the total, amount paid, and change. **Yes** submits the payment; **No**, Escape, or closing the confirmation returns to the payment form with its amount retained. No payment request is created before Yes. The receipt comes from the committed sale. **Print / save PDF** opens printing directly, with no reason prompt. Each request automatically records `Customer copy`, the receipt, user, laptop, and time in the audit. Browser printing cannot prove that paper actually printed.
5. Complete, transfer, or cancel open tickets before closing shifts. Count actual cash. Variances are retained for manager review.
6. Close every shift and ticket before closing the day. Check the backup result after day close.

Use one ticket per physical customer purchase. One ticket can produce only one sale; retries retrieve that sale. Identical baskets sold within two minutes require a separate-purchase confirmation. The application cannot recognize physical customers.

### Acknowledgement receipt branding

Receipts and their print/PDF layout show the supplied SQI logo at the top, with **SQI Group Int'l. Corp - Philippines** directly beneath it. A compact footer below the totals shows head office **18 Pineapple Rd, Malabon, 1475 Metro Manila, Philippines**, followed by two aligned columns: telephone **8-364-7561** beside **Website: https://sqigroup.ph**, then **Office Hours: 9:00 AM – 6:00 PM** beside **Monday – Saturday**. The receipt number sits directly below ACKNOWLEDGEMENT RECEIPT, without the extra bazaar/name line. Receipt details show one business date (without Day 1 or a repeated timestamp), cashier, items, totals, cash, and change. The head office address is left-aligned with the footer columns.

The logo is bundled at `static/sqi-logo.png`, so displaying or printing it needs no connection to the source network share or internet. The same receipt layout is used when viewing saved receipts and requesting a print/PDF copy. Printing waits for the logo image to decode. Check the final paper layout on the actual receipt printer.

Receipt numbers use the `SQI` prefix, for example `SQI-001-000009`. Existing `BZ` numbers are displayed with the `SQI` prefix on receipts, transaction lists, duplicate warnings, and correction forms, preserving their numeric suffix. Original historical identifiers remain stored unchanged; new sales store the `SQI` number directly.

### Orders and corrections

Transfer orders using the icon beside the ticket number. The receiving cashier needs an open same-day shift and no current order, then refreshes their counter. Only the current owner and laptop can confirm payment.

After a lost payment response, keep the same browser and ticket. Refresh when connected: the app checks the saved pending request and retrieves the original receipt if committed, or allows retry of that request. Resolve its outcome before starting a new order. Checkout pauses if the host or network is unavailable.

Managers can open original receipts in Transactions to return items or void the full sale, with password confirmation and a reason. Returned quantity cannot exceed the remaining sold amount. Voids are unavailable after partial returns. Restocking is explicit; damaged goods can have zero restock. Refunds use the original price and the current day's shift. Record a documented cash-in if that drawer has insufficient expected cash. Cash in/out does not count as sales.

The return form automatically shows each item's refund and **Refund to customer** as quantities change: return quantity × original selling price, summed across selected items. Restock quantity only changes inventory and does not change the refund. Invalid or excessive return quantities show a validation message instead of a misleading total. Review the amount before **Record correction**; the server calculates and validates the saved refund, and the cashier physically gives the cash to the customer.

If a cashier's laptop is unavailable, the manager can use **Cashier shifts → Manager close** from an approved laptop. Count the physical drawer, record a reason, and confirm the manager password. If the shift has an unpaid order, review its items and explicitly confirm cancellation; a changed order requires a fresh review. The server serializes closure against checkout and records both cancellation and closure in the audit. This allows a lost-laptop shift to be reconciled without rewriting its sales.

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

The database's instance identity survives restore, so a retained device cookie still identifies an approved browser at the same hostname. If the host/browser has been replaced, sign in once to register its pending laptop, then stop the server. An owner with local filesystem access can list terminals and approve the replacement using an existing active manager password:

```powershell
python tools/approve_terminal.py --data-dir F:\BazaarRecovered
python tools/approve_terminal.py --data-dir F:\BazaarRecovered --terminal-id 3 --username owner
```

Replace the ID and username with the pending terminal and actual manager account. The tool prompts for the password and explicit confirmation, then records a recovery-approval audit event. Restart and sign in. Reconcile any shift left on the unavailable laptop through Manager close before opening a new shift for that cashier.

## Equipment readiness

Keep the host powered and awake. Protect its data, code, keys, and backups from ordinary cashier Windows accounts. The host remains a single point of availability. Start `Start-POS.cmd` before selling; this version does not install a Windows startup service.

Before the bazaar, test the actual router, both laptops, printer, external backup destination, and a power interruption. Confirm receipt content, currency, tax treatment, and business dates. An administrator can edit local files; the audit is not tamper-proof against host administrator access. Physical cash handover cannot be atomic with a database commit.

## References

[SQLite transactions](https://www.sqlite.org/lang_transaction.html), [WAL](https://www.sqlite.org/wal.html), [online backup API](https://www.sqlite.org/backup.html), and [Flask security](https://flask.palletsprojects.com/en/stable/web-security/).

## Per-laptop receipt printers

See [printer setup](printer-setup.md) for separate USB printers, administrator configuration, helper startup, and interrupted print-job recovery. Print jobs are committed with sales but printer I/O happens afterward; never repeat checkout to repair a print failure. After database restore, re-pair each print helper before enabling automatic printing.
