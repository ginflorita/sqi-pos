# Verification record

Updated: 2026-11-11 (Asia/Taipei). Release: 0.1. Test/demo data is separate from `data/pos.sqlite3`.

Run `python -m unittest discover -s tests -v`. Integration tests use isolated SQLite files in ignored `.test-runs/` directories and separate cookie sessions.

Latest result: **44 tests passed**. JavaScript syntax validation with `node --check static/app.js` also passed.

## Automated coverage

- Repeated and concurrent checkout requests produce one sale/payment/stock deduction.
- Managers can disconnect a printer from Settings. The helper token is revoked, waiting jobs are marked failed with an audit record, and an already claimed job blocks disconnection until reviewed. A cashier cannot disconnect the printer. The 30-second background catalog read does not extend an idle login session.
- Printer Settings shows queued and claimed jobs directly; older submitted and failed entries sit under **View recent print history**. The pending list remains complete even when more than 15 newer completed jobs exist. Historical print records are retained.
- Checkout no longer shows the connected-printer badge, payment confirmation printer panel, or manual stock-refresh button. The active checkout refreshes changed catalog and stock data every 30 seconds without replacing the search or current order. The restarted local server returned HTTP 200 and served the updated JavaScript; its existing printer pairing remained in place.
- A different request key cannot create another sale for a completed ticket; changed contents cannot reuse a key.
- Two cashiers race for the last unit: one succeeds and stock stays nonnegative.
- Price changes force review; old receipt descriptions/prices remain unchanged.
- New sales save each product's short description for the on-screen and printed receipt; blank short descriptions fall back to the long description. Later product edits do not change the saved receipt name. The version 8 upgrade passed on both a copy and the live database: 25 sales, 54 sale lines, and 44,092 stock units were unchanged; integrity, foreign keys, and stock reconciliation passed. The live pre-upgrade backup is `data/backups/before-short-receipt-v8-20261111-110423.sqlite3`; the restarted local server returned HTTP 200 and served the new browser receipt code.
- The original company unit price is locked in the API and database; selling price changes create history and change checkout totals. A version 6 migration on a live-database copy preserved all 882 existing current prices as unit prices, all 197 drafts, and 24 completed sales. The live version 7 migration passed integrity and foreign-key checks, with selling prices and stock unchanged.
- Cashier permissions, receipt ownership, CSRF, Origin, and trusted Host checks.
- Stale cart versions and ticket ownership transfer.
- Stock/refund idempotency, return limits, and explicit restocking.
- Stock-in/opening stock accept omitted or blank reasons with automatic audit text; equivalent retries do not add stock twice and changed reasons cannot reuse a request key. Manual stock-out, physical counts, and signed adjustments are rejected even with a reason.
- Bulk stock posting of two items creates one document with two lines, changes both balances, and is safe to retry. An invalid line rolls back the entire posting. The catalog marks products with prior stock history so opening stock can be limited to eligible items in the picker.
- Managers can add multiple distinct discount rates and delete them with password confirmation. Cashiers can select only saved rates. Deleting a selected rate clears it from open tickets and invalidates earlier payment quotes, while completed sales keep their saved percentage. A version 4 database migrates its single rate and open-ticket selection into the current schema.
- Product records retain separate long and short descriptions and unit code and description. A trial import of the eight-column masterlist into a copy of the live database mapped all seven product and price fields for 878 ready rows with zero mismatches; 149 rows had missing prices, duplicate item codes/barcodes, or missing categories. The live import retained the previous 24 sales, 24 payments, 55 stock movements, and 9 stock documents, and database integrity and foreign keys passed after migration to version 6.
- Day 2 refunds leave Day 1 totals unchanged.
- Failed checkout rolls back financial and inventory records together.
- Historical database rows cannot be edited/deleted; negative stock is rejected.
- Image versions are retained and included in a verified backup.
- Managers create/edit products and upload photos without repeated password confirmation; audit attribution remains automatic.
- Existing price changes require a nonblank reason; rejected changes roll back product details and price together.
- Cashiers and anonymous browsers cannot write the catalog; stock and account actions retain password confirmation.
- Login throttling, disabled-account sessions, and idle sessions despite background polling.
- Receipt printing accepts omitted/blank reasons with the automatic `Customer copy` audit text and preserves user/laptop/time. Copies create no new sale, payment, or stock deduction; cashier receipt ownership still applies.
- Report filters and Excel CSV formula protection.
- Near-duplicate baskets require separate-purchase review.
- Restore writes to a new directory, retains live data, and revokes copied sessions.
- Cookie identities remain stable after restore and are isolated between independent databases; HTTPS cookies carry Secure, HttpOnly, and SameSite flags.
- Checkout rejects sessions revoked after the request began, when the write lock is acquired.
- Manager closure of another cashier's shift requires explicit review of its unpaid order and leaves a cancellation/closure audit.

## Browser verification

Checked first-run setup, login, pending-laptop approval, product images/grid, saved cart, cash/change, committed acknowledgement receipt, inventory ledger, and reports at a laptop-size viewport. A separate demo sale with total 420.00, paid 500.00, and change 80.00 produced one receipt and the expected inventory/report changes.

On 2026-10-20, enlarged and prioritized **Current order**. At the checked laptop viewport, the panel measured approximately 461 px wide, the total used 36 px text, quantity buttons measured 36 px wide, and **Review payment** measured 56 px high. Adding four different items confirmed that the item list scrolled while payment stayed visible. The larger +/− controls changed one ₱150 item to qty 2 / ₱300 and back to qty 1 / ₱150. These checks used an unpaid ticket in `.demo`; no sale was completed and no production records were changed. The CSS places the order first in a single-column layout at widths up to 1000 px. Whitespace checks passed; this CSS-only update did not rerun the integration suite.

![Larger Current order panel and payment controls](screenshots/larger-current-order.png)

The checkout heading now uses one compact row for **The counter**, its subtitle, and **Refresh stock**. The redundant eyebrow above the title was removed on Checkout. Browser measurement confirmed a 44 px row with all three elements vertically centered. The subtitle truncates when space is limited and is hidden on narrow screens to keep the title and refresh action on one row. JavaScript syntax and whitespace checks passed; this layout check only viewed the existing demo ticket.

![Compact single-row checkout heading](screenshots/compact-checkout-heading.png)

Fullscreen checkout browser checks passed in `.demo`: clicking Checkout from Transactions opened a choice; closing it kept Transactions visible; Standard view retained navigation. Both the checkout Fullscreen button and the choice's Open fullscreen entered the expanded view with sidebar/header hidden and the existing four-unit ₱510 order preserved. Exit fullscreen and Escape restored navigation. Refresh stock retained fullscreen and the order. Browser fullscreen expanded the tested viewport to the display size. JavaScript syntax and whitespace checks passed. This frontend-only update did not submit a sale or stock movement.

![Checkout display-mode choice](screenshots/checkout-mode-choice.png)

![Fullscreen checkout without the sidebar](screenshots/fullscreen-checkout.png)

The current-order list now uses a text-only table with SKU, DESC/View, QTY controls, and TOTAL. Browser checks confirmed zero images in the order table and row heights of approximately 47 px for two sample SKUs. View for BAZ-008 opened the correct full description and unit price. The notebook +/− controls changed its quantity and amount to 2 / ₱300 and back to 1 / ₱150, restoring the ₱510 order total. These checks only changed an unpaid demo ticket; no sale was completed. JavaScript syntax and whitespace checks passed.

![Compact text-only current-order table](screenshots/compact-order-table.png)

![Full description opened from the order table](screenshots/order-description.png)

The final **Confirm payment?** dialog was checked against the separate demo ticket 11: total ₱510, cash ₱600, change ₱90. No, Escape, and the close button returned to the original payment form with ₱600 retained; after No/Escape the database still held 10 sales, 10 payments, and 184 stock units. Double-clicking Yes produced only one sale for that ticket, receipt `SQI-001-000011`, one additional payment, and the expected four-unit deduction (180 units remaining). Pending-payment storage and checkout submission occur only after Yes. Focus is contained in the top confirmation dialog. JavaScript syntax and whitespace checks passed; production data was not used for this test.

![Yes/No confirmation before recording payment](screenshots/payment-yes-no.png)

The standard sidebar now uses the supplied local SQI logo in place of the former B icon and bazaar wordmark. The POS badge and bazaar-name / LOCAL WORKSPACE / currency box have been removed, leaving the logo centered above navigation. Browser verification confirmed the logo loaded in the signed-in demo workspace and the removed labels were absent; responsive CSS scales it for the compact sidebar. JavaScript syntax and whitespace checks passed. This branding-only change did not alter stock, sales, or tickets.

![SQI company logo in the sidebar](screenshots/sqi-sidebar-logo.png)

Product selection now opens **Choose quantity** for both product clicks and barcode Enter. Browser checks in `.demo` confirmed that product click/double-click followed by Cancel left ticket version 9 and its 19 update events unchanged. An excessive quantity (8 with 7 available) was blocked. Confirming qty 3 once added exactly 3 units and advanced the ticket to version 10 with 20 update events. Selecting the same barcode then showed 3 already in the order and 4 available; Escape made no additional cart change. The demo retained 10 sales and 184 stock units throughout. The confirmation button briefly ignores the opening double-click, and submissions in progress cannot be submitted again. JavaScript syntax and whitespace checks passed; no production data or sale was changed by these checks.

![Quantity confirmation before adding a product](screenshots/product-quantity.png)

On 2026-10-20, checked the simplified product forms in the separate demo workspace. Creating a product shows no reason or password field. Editing a product shows no password field; changing its selling price reveals the required reason field, and restoring the original price hides and disables that field. No sample price changes were saved during this check.

![Product editing without repeated password confirmation](screenshots/product-form.png)

The stock movement form now offers **Stock in** and **Opening stock** only. It explains both incoming movement types and does not ask for a reason. This supersedes the earlier browser check of stock-out fields.

![Stock-in with an optional reason](screenshots/stock-reason.png)

On 2026-10-20, checked SQI receipt branding against saved demo receipt `BZ-001-000010`. The supplied local PNG loaded at its original 5442 × 3064 resolution and displayed at 150 px wide. Verified the company name directly below the logo, full head office address in the footer, and a two-column footer grid: telephone / website on row one and office hours / Monday–Saturday on row two. The dialog opens at the logo. Verified the visible label `Website: https://sqigroup.ph` and its HTTPS destination. The production host served the logo successfully with HTTP 200. JavaScript syntax and whitespace checks passed. These presentation changes did not rerun the 27-test integration suite recorded above.

The logo header and compact company footer are inside the same receipt content used by the existing 80 mm print stylesheet. Also verified the simplified receipt: the extra bazaar/name line under ACKNOWLEDGEMENT RECEIPT is absent, the metadata shows one business date without a Day number or repeated timestamp, and the head office address is left-aligned with the first footer column. The explicitly labeled Cashier line remains in the metadata. These display changes do not alter stored transaction dates or stock. Actual printer/PDF pagination remains an equipment check.

![SQI acknowledgement receipt header](screenshots/sqi-receipt.png)

![SQI receipt totals and office hours](screenshots/sqi-receipt-footer.png)

Receipt-prefix verification: the two focused checkout tests (`one_sale_on_double` and `concurrent_duplicate`) passed in 3.127 seconds, including an assertion that a new sale stores `SQI-001-000001`. The demo transaction list and saved receipt `SQI-001-000009` displayed the new prefix for an existing stored `BZ` number. The numeric suffix and historical database records were preserved. JavaScript syntax and whitespace checks passed.

![Receipt with the SQI prefix](screenshots/sqi-receipt-number.png)

The direct-print update passed two focused regression tests in 2.814 seconds (`python -m unittest discover -s tests -k print -k cashier_roles -v`), plus JavaScript syntax and whitespace checks. In the demo browser, clicking **Print / save PDF** skipped the former reason form and recorded `receipt.print_requested` with `Customer copy` and actor/terminal attribution. The receipt remained visible after the print request. No physical printing was performed; printer output remains an equipment check.

![Receipt after a direct print request without a reason form](screenshots/direct-print.png)

The earlier return-form browser check used original sale prices because discounts were unavailable then. The current return form and backend now calculate refunds from the amount actually paid after a selected discount, while restock quantity continues to affect inventory only.

![Live refund amount with return qty one and restock qty zero](screenshots/refund-preview.png)

On 2026-10-20, a dedicated demo server deliberately replaced one successful checkout response with HTTP 503 **after the sale committed**. The browser displayed the failure and retained its payment request. Reloading automatically recovered receipt `BZ-001-000010`: total 150.00, paid 200.00, change 50.00. Database verification found exactly one sale, one payment, and one stock deduction for that ticket. The same session also verified manager closure of the previous demo drawer and opening a replacement-browser shift.

This simulates an uncertain response after commit; it does not replace a physical Wi-Fi-disconnection or power-loss test. The fault-injection helper is `tests/preview_server.py`, restricted to the `.demo/` workspace and loopback. It is not used by `run.py`.

HTTPS startup was verified on loopback with a generated local certificate and certificate validation enabled: the application returned HTTP 200, Secure cookies, and HSTS. No Windows trust or firewall settings were changed. A real LAN connection still requires the target router, certificate trust, and firewall setup described in Operations.

![Receipt recovered after a failed checkout response](screenshots/payment-recovery.png)

## Remaining equipment checks

Complete a sale from each physical laptop; disconnect/reconnect Laptop 2 during confirmation; check printer failure/reprint; reconcile both cash drawers; verify the external backup drive and a restore; rehearse a power interruption; confirm actual currency, tax treatment, receipt content, and dates.

Fractional quantities, non-cash payments, statutory discount/tax handling, additional bazaar creation, Windows startup-service installation, and automatic backup deletion are outside version 0.1. The manager-set order percentage is supported.

## Separate laptop receipt printers — 2026-10-20

- Added manager printer setup in Settings, per-terminal pairing, saved queue and 58/80 mm width, and an optional local Windows print helper.
- One automatic print job is committed with each sale when enabled. Checkout retries cannot create another automatic job. Claims are never automatically replayed after uncertain output. Explicit copies and resolution are audited.
- Verified 28 backend tests (42.518 s); focused printer and restore tests passed after the final changes. Tests include manager permissions, isolated terminals, invalid/revoked helper tokens, rejected browser-origin helper requests, unique jobs on checkout retry, lost claim response, idempotent result acknowledgement, failed printing with unchanged sale/payment/stock totals, and no printer replay after restoring a backup.
- Windows installed-printer enumeration succeeded. The PrintDocument adapter compiled in validation mode without sending a document. No installed printer was selected or used by this verification.
- Demo UI: Settings shows the printer setup panel and controls; [screenshot](screenshots/printer-settings.png).
- Host update: verified database snapshot before restart; existing sales, payments, stock movements, products and stock totals matched after restart. Host health responded HTTP 200. No production sale or stock adjustment was used as a test.
- Physical USB output, margins, long receipt pagination and cutting require the user's eventual printer. Automatic printing remains off until administrator setup.

## Product photo viewer — 2026-10-20

Product photos in Browse products now open a large modal with the full uncropped image, SKU and description. Photo viewing is a separate button from quantity selection, remains available on out-of-stock products, and never adds an order line. Product details and + continue to open the quantity confirmation. Thumbnails use contain sizing so the whole photo is visible.

Verified in the isolated demo: open photo, close viewer, open quantity selection, cancel; current order remained empty. JavaScript syntax and diff checks passed. [Viewer screenshot](screenshots/product-photo-viewer.png). No production data changes or server restart required.

## Compact product grid — 2026-10-20

Reduced card padding, image height to 92 px, and card spacing. Product browsing uses container queries: 2–6 columns according to the space available beside the current order. Verified six columns at 1328 px browsing width (177 px card height), and three columns at 504 px in standard view. Photo viewing and quantity controls remain separate. [Six-column screenshot](screenshots/compact-six-products.png). CSS-only update; no production records changed.
