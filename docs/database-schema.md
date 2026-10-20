# Database schema · version 0.1

Implemented by [pos/schema.sql](../pos/schema.sql), with additional immutability triggers in [pos/db.py](../pos/db.py). The 28 table names are plural. Every primary key is descriptive; there is no generic `id` column. `product_prices.price_id` uses the requested short name. Foreign keys normally use the referenced key's name. Role prefixes distinguish multiple user references, such as `cashier_user_id` and `approved_by_user_id`; both reference `users.user_id`.

IDs are internal integer keys. `sku`, barcode, ticket number, and receipt number are separate user-facing identifiers. Money is stored as integer minor units (`*_minor`), never binary floating-point values. The initial quantity model is whole base units. Event time is stored in UTC; `business_date` is the bazaar's local reporting date, using its configured timezone.

The bold first field is the primary key. `NULL` means optional where stated; executable nullability and checks are defined in the SQL file. Status/type fields use constrained sets. Authentication-session times are Unix seconds; transaction timestamps are UTC text.

## Bazaar, accounts, and shifts

| Table | Columns | Key relationships and rules |
| --- | --- | --- |
| `system_settings` | **`system_setting_id`**, `instance_key`, `created_at` | One row with key 1. Its stable random instance identity isolates browser cookies between workspaces and survives backup/restore to a new folder. |
| `bazaars` | **`bazaar_id`**, `name`, `starts_on`, `ends_on`, `timezone`, `currency_code`, `status`, `created_by_user_id`, `created_at` | `created_by_user_id` → `users.user_id`. One active bazaar in the initial deployment. |
| `bazaar_days` | **`bazaar_day_id`**, `bazaar_id`, `day_number`, `business_date`, `status`, `opened_at`, `opened_by_user_id`, `closed_at`, `closed_by_user_id` | Bazaar/user FKs. Unique day number and business date within a bazaar; only one day open at a time. |
| `users` | **`user_id`**, `username`, `display_name`, `password_hash`, `role`, `active`, `created_by_user_id`, `created_at`, `disabled_at` | `username` unique; `created_by_user_id` → `users.user_id` and may be NULL for bootstrap. Deactivate rather than delete. |
| `terminals` | **`terminal_id`**, `name`, `device_key_hash`, `approved`, `approved_by_user_id`, `last_seen_at` | `approved_by_user_id` → `users.user_id`. Only approved terminals may check out. |
| `auth_sessions` | **`auth_session_id`**, `token_hash`, `user_id`, `terminal_id`, `created_at`, `last_seen_at`, `expires_at` | Unique token hash; user/terminal FKs. Tokens are not stored in plaintext. Sessions have idle and absolute expiry and are revoked on restore. |
| `login_limits` | **`login_limit_id`**, `bucket_key`, `attempts`, `window_started_at` | Unique bucket per hashed sign-in identifier/address or manager approval account. Persistent throttling state, not transaction history. |
| `shifts` | **`shift_id`**, `bazaar_day_id`, `cashier_user_id`, `terminal_id`, `opening_cash_minor`, `expected_cash_minor`, `counted_cash_minor`, `variance_minor`, `opened_at`, `closed_at`, `status` | Day, user, and terminal FKs. One open shift per user and terminal. Expected/count/variance are finalized at close; manager closure records its approval and reason in the audit. |
| `cash_movements` | **`cash_movement_id`**, `shift_id`, `direction`, `amount_minor`, `reason`, `request_key`, `created_by_user_id`, `approved_by_user_id`, `created_at` | Non-sale/non-refund cash in/out; positive amount, reason, and approval required. Unique request key prevents duplicate posting. |

## Catalog

| Table | Columns | Key relationships and rules |
| --- | --- | --- |
| `categories` | **`category_id`**, `name`, `active` | Unique category name in the initial catalog; deactivate rather than delete. |
| `products` | **`product_id`**, `sku`, `barcode`, `description`, `category_id`, `unit`, `active` | Exactly the requested product fields. `sku` unique and required; `barcode` unique when present; `category_id` → `categories.category_id`. `description` replaces `name`. |
| `product_images` | **`product_image_id`**, `product_id`, `image_data`, `thumbnail_data`, `mime_type`, `size_bytes`, `sha256`, `uploaded_by_user_id`, `uploaded_at`, `superseded_at` | `product_id` → `products.product_id`. At most one current image (`superseded_at IS NULL`) per product; old versions retained. Images are validated, resized, and stored inside the database. |
| `product_prices` | **`price_id`**, `product_id`, `amount_minor`, `effective_at`, `changed_by_user_id`, `reason` | Product/user FKs. Prices are positive minor units. Changes take effect immediately; the newest price row is current. Initial price reason is generated automatically; changing an existing price requires a reason. Unchanged prices create no extra row. Historical rows are immutable. |

## Inventory

| Table | Columns | Key relationships and rules |
| --- | --- | --- |
| `stock_balances` | **`stock_balance_id`**, `product_id`, `quantity_on_hand`, `updated_at` | `product_id` unique FK → `products.product_id`; `quantity_on_hand >= 0`. Maintained with the movement transaction, not edited from the UI. |
| `stock_documents` | **`stock_document_id`**, `bazaar_id`, `bazaar_day_id`, `document_type`, `reference_no`, `reason`, `request_key`, `status`, `created_by_user_id`, `approved_by_user_id`, `created_at`, `approved_at` | Types: opening stock, stock-in, stock-out, count, adjustment. Blank reasons default to `Opening stock` or `Stock received` for opening/in only; other types require a manual reason. Unique request key. `bazaar_day_id` may be NULL before Day 1; `bazaar_id` is required. Approval and posting happen together. |
| `stock_document_lines` | **`stock_document_line_id`**, `stock_document_id`, `product_id`, `quantity_change`, `expected_quantity`, `counted_quantity`, `unit_cost_minor` | Document and product FKs. Unique `(stock_document_id, product_id)`; expected/counted quantities apply to physical counts. A nonzero movement is created only on approval. |
| `stock_movements` | **`stock_movement_id`**, `bazaar_id`, `bazaar_day_id`, `product_id`, `quantity_change`, `sale_line_id`, `stock_document_line_id`, `correction_line_id`, `created_by_user_id`, `created_at` | Append-only ledger. Exactly one of the three source-line FKs must be populated; at most one movement per source line. `quantity_change` cannot be zero. `bazaar_day_id` may be NULL for pre-event opening stock. |

## Tickets, sales, and payments

| Table | Columns | Key relationships and rules |
| --- | --- | --- |
| `purchase_tickets` | **`purchase_ticket_id`**, `bazaar_day_id`, `ticket_number`, `owner_user_id`, `terminal_id`, `state`, `version`, `created_at`, `updated_at` | Unique `(bazaar_day_id, ticket_number)`; states open, completed, cancelled. `version` guards concurrent cart edits. Transfers change owner with an audit entry. |
| `ticket_lines` | **`ticket_line_id`**, `purchase_ticket_id`, `product_id`, `quantity` | Ticket and product FKs. Unique `(purchase_ticket_id, product_id)`; positive quantity. |
| `checkout_requests` | **`checkout_request_id`**, `request_key`, `purchase_ticket_id`, `request_hash`, `status`, `sale_id`, `created_at`, `finished_at` | Unique request key. Only completed requests are persisted, atomically with the sale; `sale_id` is required. A matching retry returns the saved result; changed contents are rejected. |
| `sales` | **`sale_id`**, `purchase_ticket_id`, `receipt_number`, `bazaar_day_id`, `shift_id`, `cashier_user_id`, `terminal_id`, `subtotal_minor`, `discount_minor`, `tax_minor`, `total_minor`, `completed_at` | Unique `purchase_ticket_id` and globally unique `receipt_number`. Ticket, shift, and sale must belong to the same open bazaar day. Completed rows are immutable. |
| `sale_lines` | **`sale_line_id`**, `sale_id`, `product_id`, `price_id`, `product_image_id`, `sku_snapshot`, `description_snapshot`, `category_id_snapshot`, `category_name_snapshot`, `unit_snapshot`, `quantity`, `unit_price_minor`, `discount_minor`, `tax_minor`, `line_total_minor` | FKs preserve source item/price/image version. Snapshot fields preserve exactly what the cashier sold and how it was reported at the time. |
| `payments` | **`payment_id`**, `sale_id`, `sale_correction_id`, `direction`, `method`, `amount_minor`, `tendered_minor`, `change_minor`, `reference_no`, `recorded_at` | Exactly one of `sale_id` (money in) or `sale_correction_id` (refund out) must be set. `amount_minor` is the net payment applied to the sale or refunded; cash tendered and server-computed change are separate. |

## Corrections, receipts, and system records

| Table | Columns | Key relationships and rules |
| --- | --- | --- |
| `sale_corrections` | **`sale_correction_id`**, `original_sale_id`, `bazaar_day_id`, `shift_id`, `correction_type`, `reason`, `request_key`, `refund_total_minor`, `created_by_user_id`, `approved_by_user_id`, `created_at` | Void or return linked to the original sale; recorded on the current day and shift. Unique request key, reason, and manager approval required. |
| `correction_lines` | **`correction_line_id`**, `sale_correction_id`, `sale_line_id`, `quantity`, `refund_minor`, `restock_quantity` | Total corrected quantity cannot exceed original sold quantity. Restocking is explicit and may be zero. |
| `receipt_events` | **`receipt_event_id`**, `sale_id`, `event_type`, `output_format`, `performed_by_user_id`, `terminal_id`, `reason`, `created_at` | Receipt allocation with the sale and app-requested print/PDF copies. No new sale on reprint. Browser/OS output and physical printing cannot be proven by this record. |
| `audit_events` | **`audit_event_id`**, `bazaar_day_id`, `actor_user_id`, `terminal_id`, `attempted_username`, `action`, `entity_type`, `entity_key`, `before_json`, `after_json`, `reason`, `approved_by_user_id`, `created_at` | Append-only. Actor may be NULL for failed login. Do not store passwords or session secrets. |
| `backup_runs` | **`backup_run_id`**, `started_at`, `finished_at`, `status`, `destination`, `file_hash`, `verified_at`, `error_message` | Records backup creation and verification; data resides on storage separate from the host where practical. |

## Integrity rules spanning tables

1. A sale, its lines, payment, stock movements, ticket completion, receipt number, checkout request result, and audit event commit together or not at all.
2. A ticket can produce at most one sale. A retry with its original request key retrieves that sale; a different request key still cannot create a second sale for the same ticket.
3. Stock is rechecked at commit. No sale or adjustment may make `stock_balances.quantity_on_hand` negative. Every balance change has a corresponding append-only `stock_movements` row.
4. Past sale lines retain description, category, price, and image-version references despite later catalog changes.
5. A refund, void, or return links to an original sale and never mutates its historical payment or lines. The return limit is enforced across all prior corrections.
6. Report totals are derived from sales, payments, corrections, shifts, and stock movements. They are not independently editable records.

## Report queries

Reports use application queries over source tables; no named SQL views or independently editable report totals are created in version 0.1. Sales reports group by day, product, historical category, and cashier, with filters for business date, day, product, category, cashier, and laptop. Inventory movement history and shift reconciliation have separate screens.
