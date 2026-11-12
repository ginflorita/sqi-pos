# Bazaar POS plan

## Status and operating assumptions

Version 0.1 implements the core workflows below. See [README](../README.md) for the available scope, [operations](operations.md) for setup, and [verification](verification.md) for tested scenarios and remaining equipment checks. The system supports two cashier users on separate Windows laptops at one active bazaar. A router creates a local network even without internet. Laptop 1 runs the application and keeps SQLite on its internal drive; Laptop 2 connects through a browser. The database file is never opened directly across the network or placed in a synced folder.

Laptop 1 must remain powered on, awake, and connected. If the host, app, or local network is unavailable, checkout stops. There is no independent offline sale queue. Reports download as formatted Excel workbooks; item imports remain planned. Quantities are whole base units and payment is cash. The cashier can select one of several manager-set percentage discounts per order; added tax remains zero pending confirmation of the bazaar's requirements.

## Users and permissions

Each person uses a named account; there is no shared cashier or guest account. Only the owner/manager may create, reset, deactivate, or change cashier accounts. Deactivation retains attribution on historical records. One of the two users may also have manager privileges, but every action remains tied to that person's account.

| Action | Cashier | Manager |
| --- | --- | --- |
| Search items and stock, create and complete sales | Yes | Yes |
| View own shift and receipts; reprint with an audit entry | Yes | Yes |
| View all cashiers, days, and management reports | No | Yes |
| Create users; edit items, prices, categories, and images | No | Yes |
| Approve voids, returns, stock adjustments, and cash exceptions | No | Yes |
| Open and close bazaar days; manage backups and settings | No | Yes |

The server checks authorization on every request and checks it again inside financial write transactions after acquiring the write lock. Passwords use salted scrypt hashes; sign-in and manager approval attempts are throttled. Sessions expire after 30 minutes without application activity or 12 hours in total. Background connection checks do not extend idle sessions. Sensitive changes require the manager's password. A valid account can sign in from any browser without device approval. LAN mode requires HTTPS; Windows permissions must protect host data and backups from cashier accounts.

## Bazaar days and cashier shifts

An owner creates a bazaar and its numbered business days (Day 1, Day 2, and so on). The owner manually opens one day at a time. A sale receives both the active `bazaar_day_id` and a host timestamp; the cashier laptop's clock cannot choose its reporting day. A day may continue after midnight until the owner closes it.

Each cashier opens a shift with an opening cash count. Closing records expected cash, counted cash, and variance. Closing a day locks its sales history. Later corrections are entered on the current open day and link to the original sale; they do not rewrite the earlier day's record. A Day 2 refund of a Day 1 sale appears in Day 2 refund and cash activity.

## Items, prices, images, and inventory

- A product has a unique SKU, optional unique barcode, required description, category, unit, and active flag. Products are deactivated rather than deleted.
- Product creation, normal edits, and photo uploads require a signed-in manager without repeated password confirmation. The audit records the actor, time, and changed details automatically; routine edits do not require a manual reason.
- Price changes create history rows. A new product's initial price receives the automatic reason `Initial selling price`; changing an existing price requires a manager-entered reason. Every sale line stores the SKU, description, category, unit, and price used at checkout, so later catalog changes do not alter old reports or receipts.
- A manager uploads or replaces a product photo. The app validates the file, strips unnecessary metadata, resizes/compresses it, and creates a thumbnail. The current and superseded image versions remain linked to the product and are included in database backups. A missing photo displays a placeholder and does not block a sale.
- Stock on hand is maintained from an append-only movement ledger: starting stock and received deliveries add units, completed sales subtract them, and approved returns can restock them. Stock documents record user, time, reference, and reason. The form records `Stock received` or `Opening stock` automatically. Manual stock-out, physical count resets, and signed adjustments are rejected. Stock postings need manager password approval. Negative stock is rejected.
- Stock displayed while building a cart is advisory. Stock is checked again in the final checkout transaction. When both cashiers try to buy the last unit, only the first valid committed sale succeeds.

## Checkout and duplicate prevention

1. A cashier creates one purchase ticket for the customer's purchase and searches or scans items. Product selection opens a quantity dialog with the price, amount to add, available stock, and any existing order quantity. The cashier confirms **Add to order** before the cart changes. Cancel/Escape adds nothing. Product double-clicks do not bypass confirmation; barcode entry follows the same flow.
2. The app calculates totals on the server. The cashier enters the payment amount and reviews the change.
3. **Confirm payment** opens a final Yes / No dialog showing total, cash paid, and change. No, closing, or Escape returns to the same payment form without submitting. Only Yes stores the pending request and sends the ticket ID, a unique request key, and a hash of the confirmed cart/payment. Retries use the existing request. The browser may disable the button, but server and database rules provide the actual protection.
4. The server acquires the database write transaction before its final recheck. Within that transaction it confirms the ticket is open and owned by the cashier, validates item status and prices, checks payment and available stock, creates one sale and receipt number, records sale lines and payment, records stock movements, marks the ticket completed, and writes the successful-sale audit event.
5. The app issues an acknowledgement receipt only after commit. Any failed check rolls back the entire sale.

`sales.purchase_ticket_id`, `sales.receipt_number`, and `checkout_requests.request_key` are unique. A double-click or retry of a committed request returns the original result. If the network drops after commit but before the browser sees the response, the cashier checks the ticket status and receives the existing receipt; the app never assumes it should submit a new sale. A request key reused with different contents is rejected. Rejected attempts are audited separately from the rolled-back sale transaction.

One ticket has one owner and laptop at a time, and each cashier can have one open ticket. Transfers are audited and require a receiving same-day shift with no existing order. Software cannot identify the same physical purchase if two people independently create different tickets. Use one ticket per customer purchase. Identical baskets sold within two minutes require the cashier to confirm they are separate purchases; questionable matches need manager review.

## Receipts, corrections, and cash

Receipts show a unique receipt number, business date, cashier, item descriptions, quantities, prices, discounts/tax if applicable, total, payment, and change. The printed layout omits the extra bazaar/name line, day number, and repeated timestamp; the database retains the full transaction day and timestamp. A printing failure does not create another sale. Printing/reprinting uses the existing sale and records the user, laptop, time, and automatic reason `Customer copy`, without asking the cashier for a reason. PDFs may be offered alongside printer output.

Completed sales and movements are not deleted or edited. Voids and returns create linked correction rows with reason, actor, and manager approval. Returned quantity cannot exceed the unreturned quantity on the original sale line. Restocking is explicit; a damaged return need not increase sellable stock. Refund payments appear on the day and shift when paid. Non-sale cash in/out movements also require a reason and approval.

Expected cash equals opening cash plus net cash received from sales, less cash refunds, plus other approved cash movements. Cash tendered and change are both recorded, but change is not counted as revenue. The cashier enters the physical count at shift close. The system stores and reports any difference without silently changing transaction history.

## Reports and monitoring

For the active bazaar, the manager can filter sales reports by Day 1/Day 2/etc., business-date span, product, category, and cashier, alone or together. Reports show transactions, units, gross sales, refunds, net sales, and average sale. Transactions provides source receipts; Inventory shows movement history and low-stock counts; Cashier shifts shows reconciliation and variance. Reprints and account activity appear in Audit trail. Historical item/category snapshots determine historical groupings. Totals come from source records. The Excel export has Summary, Days, Items, Category, and Cashier sheets; the CSV endpoint remains available for compatibility. PDF receipt output uses browser printing. Multi-bazaar selection and direct report-row drilldown are future additions.

The audit records user and terminal, host time, action, affected record, result, reason, approval, and relevant before/after values. It includes successful and failed logins, account changes, catalog changes, stock changes, sales, corrections, reprints, day/shift closes, backup failures, and restore actions. It excludes passwords and session secrets. Ordinary users cannot edit audit entries through the app.

## Reliability, backups, and recovery

SQLite uses foreign-key enforcement, WAL, full synchronous writes, and immediate write transactions. Online backups run every 15 minutes while the server runs, at day close, and on request. Create a verified backup before each update and keep it on separate storage. Snapshots receive integrity and foreign-key checks. Restore writes to a new directory, checks stock reconciliation, revokes sessions, and records an audit event. There is no automatic backup deletion; the owner manages retention until a policy is agreed.

The host has a one-click launcher and an optional per-user Windows sign-in startup shortcut. The app shows connection and backup health, checks database integrity at startup, and stops checkout on corruption or unavailable storage. After a lost payment response, the same browser retains the request and checks the ticket on refresh, retrieving the original receipt when committed. Receipts are generated from committed records.

This offline setup has a single host. A failed host drive can cause loss since the last usable backup. A person with administrator access to the host and every backup can tamper with local records; separation and retained external backups reduce that risk but do not make the system tamper-proof. A physical cash handover also cannot be made atomic with a database commit.

## Acceptance tests before bazaar use

- Double-click, refresh, or retry a confirmation: exactly one sale, payment, stock deduction, and receipt.
- Disconnect Laptop 2 after commit but before response: reconnecting retrieves that same sale and receipt.
- Both cashiers attempt the last unit: exactly one succeeds and stock never becomes negative.
- Transfer one ticket between cashiers: only its current owner can confirm it.
- Fail receipt printing after commit: reprint existing receipt without a second sale.
- Attempt a cashier-only price edit, refund, or full report: server denies and audits it.
- Close Day 1 and process a linked return on Day 2: both daily reports and cash balances remain correct.
- Change a product's category, description, price, or image: older sale lines retain their historical snapshots.
- Interrupt the app during a write, restart it, verify ticket status, run integrity checks, and restore a test backup.

## Details still to confirm

Receipt printer/model and format; bazaar currency and tax rules; whether items may be sold by weight or other fractional units; accepted payment methods; statutory discount requirements; expected item count and sales volume; backup destination and acceptable maximum data-loss window. These choices do not change the core two-laptop architecture or duplicate-save rule.
