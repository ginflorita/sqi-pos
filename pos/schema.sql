PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS system_settings (
 system_setting_id INTEGER PRIMARY KEY CHECK(system_setting_id=1),
 instance_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
 discount_percent_bp INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent_bp BETWEEN 0 AND 9900)
);
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('it_admin','manager','cashier')), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_by_user_id INTEGER REFERENCES users(user_id), created_at TEXT NOT NULL, disabled_at TEXT
);
CREATE TABLE IF NOT EXISTS discount_rates (
 discount_rate_id INTEGER PRIMARY KEY,
 percent_bp INTEGER NOT NULL UNIQUE CHECK(percent_bp BETWEEN 1 AND 9900),
 created_by_user_id INTEGER REFERENCES users(user_id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bazaars (
 bazaar_id INTEGER PRIMARY KEY, name TEXT NOT NULL, starts_on TEXT NOT NULL, ends_on TEXT,
 timezone TEXT NOT NULL, currency_code TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','closed')),
 created_by_user_id INTEGER NOT NULL REFERENCES users(user_id), created_at TEXT NOT NULL,
 event_name TEXT NOT NULL DEFAULT 'Event 1', archive_backup TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_bazaar ON bazaars(status) WHERE status='active';
CREATE TABLE IF NOT EXISTS bazaar_days (
 bazaar_day_id INTEGER PRIMARY KEY, bazaar_id INTEGER NOT NULL REFERENCES bazaars(bazaar_id),
 day_number INTEGER NOT NULL CHECK(day_number>0), business_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('open','closed')), opened_at TEXT NOT NULL,
 opened_by_user_id INTEGER NOT NULL REFERENCES users(user_id), closed_at TEXT, closed_by_user_id INTEGER REFERENCES users(user_id),
 UNIQUE(bazaar_id,day_number), UNIQUE(bazaar_id,business_date)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_day ON bazaar_days(status) WHERE status='open';
CREATE TABLE IF NOT EXISTS terminals (
 terminal_id INTEGER PRIMARY KEY, name TEXT NOT NULL, device_key_hash TEXT NOT NULL UNIQUE,
 approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)), approved_by_user_id INTEGER REFERENCES users(user_id), last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
 auth_session_id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users(user_id),
 terminal_id INTEGER NOT NULL REFERENCES terminals(terminal_id), created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_limits (
 login_limit_id INTEGER PRIMARY KEY, bucket_key TEXT NOT NULL UNIQUE, attempts INTEGER NOT NULL, window_started_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS shifts (
 shift_id INTEGER PRIMARY KEY, bazaar_day_id INTEGER NOT NULL REFERENCES bazaar_days(bazaar_day_id),
 cashier_user_id INTEGER NOT NULL REFERENCES users(user_id), terminal_id INTEGER NOT NULL REFERENCES terminals(terminal_id),
 opening_cash_minor INTEGER NOT NULL CHECK(opening_cash_minor>=0), expected_cash_minor INTEGER,
 counted_cash_minor INTEGER CHECK(counted_cash_minor>=0), variance_minor INTEGER,
 opened_at TEXT NOT NULL, closed_at TEXT, status TEXT NOT NULL CHECK(status IN ('open','closed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_shift_per_user ON shifts(cashier_user_id) WHERE status='open';
CREATE UNIQUE INDEX IF NOT EXISTS one_shift_per_terminal ON shifts(terminal_id) WHERE status='open';
CREATE TABLE IF NOT EXISTS cash_movements (
 cash_movement_id INTEGER PRIMARY KEY, shift_id INTEGER NOT NULL REFERENCES shifts(shift_id),
 direction TEXT NOT NULL CHECK(direction IN ('in','out')), amount_minor INTEGER NOT NULL CHECK(amount_minor>0), reason TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE, created_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
 approved_by_user_id INTEGER NOT NULL REFERENCES users(user_id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
 category_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS products (
 product_id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE COLLATE NOCASE, barcode TEXT UNIQUE,
 description TEXT NOT NULL, short_description TEXT NOT NULL DEFAULT '',
 category_id INTEGER NOT NULL REFERENCES categories(category_id), unit TEXT NOT NULL,
 unit_description TEXT NOT NULL DEFAULT '', unit_price_minor INTEGER NOT NULL CHECK(unit_price_minor>0),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS product_import_drafts (
 product_import_draft_id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
 description TEXT NOT NULL, source_filename TEXT NOT NULL,
 imported_by_user_id INTEGER NOT NULL REFERENCES users(user_id), imported_at TEXT NOT NULL,
 barcode TEXT, short_description TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT '',
 unit_description TEXT NOT NULL DEFAULT '', category_name TEXT NOT NULL DEFAULT '',
 amount_minor INTEGER CHECK(amount_minor>0), unit_price_minor INTEGER CHECK(unit_price_minor>0), source_row INTEGER,
 import_issue TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS product_images (
 product_image_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(product_id),
 image_data BLOB NOT NULL, thumbnail_data BLOB NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 sha256 TEXT NOT NULL, uploaded_by_user_id INTEGER NOT NULL REFERENCES users(user_id), uploaded_at TEXT NOT NULL, superseded_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_image ON product_images(product_id) WHERE superseded_at IS NULL;
CREATE TABLE IF NOT EXISTS product_prices (
 price_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(product_id), amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 effective_at TEXT NOT NULL, changed_by_user_id INTEGER NOT NULL REFERENCES users(user_id), reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prices_product ON product_prices(product_id,price_id DESC);
CREATE TABLE IF NOT EXISTS stock_balances (
 stock_balance_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL UNIQUE REFERENCES products(product_id),
 quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK(quantity_on_hand>=0), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_documents (
 stock_document_id INTEGER PRIMARY KEY, bazaar_id INTEGER NOT NULL REFERENCES bazaars(bazaar_id),
 bazaar_day_id INTEGER REFERENCES bazaar_days(bazaar_day_id), document_type TEXT NOT NULL CHECK(document_type IN ('opening','in','out','count','adjustment')),
 reference_no TEXT NOT NULL, reason TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL CHECK(status='posted'), created_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
 approved_by_user_id INTEGER NOT NULL REFERENCES users(user_id), created_at TEXT NOT NULL, approved_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS stock_documents_receipts_only BEFORE INSERT ON stock_documents
WHEN NEW.document_type NOT IN ('opening','in')
BEGIN SELECT RAISE(ABORT,'Only opening stock and receipts can be posted'); END;
CREATE TABLE IF NOT EXISTS stock_document_lines (
 stock_document_line_id INTEGER PRIMARY KEY, stock_document_id INTEGER NOT NULL REFERENCES stock_documents(stock_document_id),
 product_id INTEGER NOT NULL REFERENCES products(product_id), quantity_change INTEGER NOT NULL,
 expected_quantity INTEGER, counted_quantity INTEGER, unit_cost_minor INTEGER, UNIQUE(stock_document_id,product_id)
);
CREATE TABLE IF NOT EXISTS purchase_tickets (
 purchase_ticket_id INTEGER PRIMARY KEY, bazaar_day_id INTEGER NOT NULL REFERENCES bazaar_days(bazaar_day_id),
 ticket_number TEXT NOT NULL, owner_user_id INTEGER NOT NULL REFERENCES users(user_id), terminal_id INTEGER NOT NULL REFERENCES terminals(terminal_id),
 state TEXT NOT NULL CHECK(state IN ('open','completed','cancelled')), version INTEGER NOT NULL DEFAULT 0,
 discount_selected INTEGER NOT NULL DEFAULT 0 CHECK(discount_selected IN (0,1)),
 discount_percent_bp INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent_bp BETWEEN 0 AND 9900),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(bazaar_day_id,ticket_number)
);
CREATE TABLE IF NOT EXISTS ticket_lines (
 ticket_line_id INTEGER PRIMARY KEY, purchase_ticket_id INTEGER NOT NULL REFERENCES purchase_tickets(purchase_ticket_id),
 product_id INTEGER NOT NULL REFERENCES products(product_id), quantity INTEGER NOT NULL CHECK(quantity>0), UNIQUE(purchase_ticket_id,product_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_ticket_per_cashier ON purchase_tickets(owner_user_id) WHERE state='open';
CREATE TABLE IF NOT EXISTS sales (
 sale_id INTEGER PRIMARY KEY, purchase_ticket_id INTEGER NOT NULL UNIQUE REFERENCES purchase_tickets(purchase_ticket_id),
 receipt_number TEXT NOT NULL UNIQUE, bazaar_day_id INTEGER NOT NULL REFERENCES bazaar_days(bazaar_day_id),
 shift_id INTEGER NOT NULL REFERENCES shifts(shift_id), cashier_user_id INTEGER NOT NULL REFERENCES users(user_id),
 terminal_id INTEGER NOT NULL REFERENCES terminals(terminal_id), subtotal_minor INTEGER NOT NULL CHECK(subtotal_minor>0),
 discount_minor INTEGER NOT NULL DEFAULT 0 CHECK(discount_minor>=0), tax_minor INTEGER NOT NULL DEFAULT 0 CHECK(tax_minor>=0),
 discount_percent_bp INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent_bp BETWEEN 0 AND 9900),
 total_minor INTEGER NOT NULL CHECK(total_minor=subtotal_minor-discount_minor+tax_minor), completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkout_requests (
 checkout_request_id INTEGER PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
 purchase_ticket_id INTEGER NOT NULL REFERENCES purchase_tickets(purchase_ticket_id), request_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status='completed'), sale_id INTEGER NOT NULL REFERENCES sales(sale_id), created_at TEXT NOT NULL, finished_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sale_lines (
 sale_line_id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(sale_id), product_id INTEGER NOT NULL REFERENCES products(product_id),
 price_id INTEGER NOT NULL REFERENCES product_prices(price_id), product_image_id INTEGER REFERENCES product_images(product_image_id),
 sku_snapshot TEXT NOT NULL, description_snapshot TEXT NOT NULL,
 short_description_snapshot TEXT NOT NULL DEFAULT '', category_id_snapshot INTEGER NOT NULL REFERENCES categories(category_id),
 category_name_snapshot TEXT NOT NULL, unit_snapshot TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price_minor INTEGER NOT NULL CHECK(unit_price_minor>0), discount_minor INTEGER NOT NULL DEFAULT 0,
 tax_minor INTEGER NOT NULL DEFAULT 0, line_total_minor INTEGER NOT NULL CHECK(line_total_minor=quantity*unit_price_minor-discount_minor+tax_minor)
);
CREATE TABLE IF NOT EXISTS sale_corrections (
 sale_correction_id INTEGER PRIMARY KEY, original_sale_id INTEGER NOT NULL REFERENCES sales(sale_id),
 bazaar_day_id INTEGER NOT NULL REFERENCES bazaar_days(bazaar_day_id), shift_id INTEGER NOT NULL REFERENCES shifts(shift_id),
 correction_type TEXT NOT NULL CHECK(correction_type IN ('return','void')), reason TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE,
 refund_total_minor INTEGER NOT NULL CHECK(refund_total_minor>0), created_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
 approved_by_user_id INTEGER NOT NULL REFERENCES users(user_id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS correction_lines (
 correction_line_id INTEGER PRIMARY KEY, sale_correction_id INTEGER NOT NULL REFERENCES sale_corrections(sale_correction_id),
 sale_line_id INTEGER NOT NULL REFERENCES sale_lines(sale_line_id), quantity INTEGER NOT NULL CHECK(quantity>0),
 refund_minor INTEGER NOT NULL CHECK(refund_minor>0), restock_quantity INTEGER NOT NULL CHECK(restock_quantity>=0 AND restock_quantity<=quantity),
 UNIQUE(sale_correction_id,sale_line_id)
);
CREATE TABLE IF NOT EXISTS payments (
 payment_id INTEGER PRIMARY KEY, sale_id INTEGER REFERENCES sales(sale_id), sale_correction_id INTEGER REFERENCES sale_corrections(sale_correction_id),
 direction TEXT NOT NULL CHECK(direction IN ('in','out')), method TEXT NOT NULL CHECK(method='cash'), amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 tendered_minor INTEGER NOT NULL CHECK(tendered_minor>=amount_minor), change_minor INTEGER NOT NULL CHECK(change_minor=tendered_minor-amount_minor),
 reference_no TEXT, recorded_at TEXT NOT NULL,
 CHECK((sale_id IS NOT NULL AND sale_correction_id IS NULL AND direction='in') OR
 (sale_id IS NULL AND sale_correction_id IS NOT NULL AND direction='out')),
 UNIQUE(sale_id), UNIQUE(sale_correction_id)
);
CREATE TABLE IF NOT EXISTS stock_movements (
 stock_movement_id INTEGER PRIMARY KEY, bazaar_id INTEGER NOT NULL REFERENCES bazaars(bazaar_id), bazaar_day_id INTEGER REFERENCES bazaar_days(bazaar_day_id),
 product_id INTEGER NOT NULL REFERENCES products(product_id), quantity_change INTEGER NOT NULL CHECK(quantity_change<>0),
 sale_line_id INTEGER UNIQUE REFERENCES sale_lines(sale_line_id), stock_document_line_id INTEGER UNIQUE REFERENCES stock_document_lines(stock_document_line_id),
 correction_line_id INTEGER UNIQUE REFERENCES correction_lines(correction_line_id), created_by_user_id INTEGER NOT NULL REFERENCES users(user_id), created_at TEXT NOT NULL,
 CHECK((sale_line_id IS NOT NULL)+(stock_document_line_id IS NOT NULL)+(correction_line_id IS NOT NULL)=1)
);
CREATE TABLE IF NOT EXISTS receipt_events (
 receipt_event_id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(sale_id), event_type TEXT NOT NULL CHECK(event_type IN ('issued','reprint')),
 output_format TEXT NOT NULL, performed_by_user_id INTEGER NOT NULL REFERENCES users(user_id), terminal_id INTEGER NOT NULL REFERENCES terminals(terminal_id),
 reason TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
 audit_event_id INTEGER PRIMARY KEY, bazaar_day_id INTEGER REFERENCES bazaar_days(bazaar_day_id), actor_user_id INTEGER REFERENCES users(user_id),
 terminal_id INTEGER REFERENCES terminals(terminal_id), attempted_username TEXT, action TEXT NOT NULL, entity_type TEXT NOT NULL,
 entity_key TEXT, before_json TEXT, after_json TEXT, reason TEXT, approved_by_user_id INTEGER REFERENCES users(user_id), created_at TEXT NOT NULL,
 bazaar_id INTEGER REFERENCES bazaars(bazaar_id)
);
CREATE TABLE IF NOT EXISTS backup_runs (
 backup_run_id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL CHECK(status IN ('running','verified','failed')),
 destination TEXT, file_hash TEXT, verified_at TEXT, error_message TEXT
);
CREATE TRIGGER IF NOT EXISTS product_balance AFTER INSERT ON products BEGIN
 INSERT INTO stock_balances(product_id,quantity_on_hand,updated_at) VALUES(NEW.product_id,0,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
END;
CREATE TRIGGER IF NOT EXISTS product_unit_price_required BEFORE INSERT ON products
WHEN NEW.unit_price_minor IS NULL OR NEW.unit_price_minor<=0
BEGIN SELECT RAISE(ABORT,'Unit price is required'); END;
CREATE TRIGGER IF NOT EXISTS product_unit_price_locked BEFORE UPDATE OF unit_price_minor ON products
WHEN NEW.unit_price_minor IS NOT OLD.unit_price_minor
BEGIN SELECT RAISE(ABORT,'Unit price is locked'); END;
CREATE TRIGGER IF NOT EXISTS movement_balance AFTER INSERT ON stock_movements BEGIN
 UPDATE stock_balances SET quantity_on_hand=quantity_on_hand+NEW.quantity_change,updated_at=NEW.created_at WHERE product_id=NEW.product_id;
END;
CREATE TRIGGER IF NOT EXISTS valid_movement BEFORE INSERT ON stock_movements BEGIN
 SELECT CASE WHEN NEW.sale_line_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM sale_lines WHERE sale_line_id=NEW.sale_line_id AND product_id=NEW.product_id AND NEW.quantity_change=-quantity)
 THEN RAISE(ABORT,'Invalid sale movement') END;
 SELECT CASE WHEN NEW.correction_line_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM correction_lines c JOIN sale_lines s USING(sale_line_id) WHERE correction_line_id=NEW.correction_line_id AND s.product_id=NEW.product_id AND NEW.quantity_change=c.restock_quantity)
 THEN RAISE(ABORT,'Invalid return movement') END;
 SELECT CASE WHEN NEW.stock_document_line_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM stock_document_lines WHERE stock_document_line_id=NEW.stock_document_line_id AND product_id=NEW.product_id AND NEW.quantity_change=quantity_change)
 THEN RAISE(ABORT,'Invalid document movement') END;
END;
CREATE TRIGGER IF NOT EXISTS return_limit BEFORE INSERT ON correction_lines BEGIN
 SELECT CASE WHEN NEW.quantity+COALESCE((SELECT SUM(quantity) FROM correction_lines WHERE sale_line_id=NEW.sale_line_id),0) >
 (SELECT quantity FROM sale_lines WHERE sale_line_id=NEW.sale_line_id) THEN RAISE(ABORT,'Return quantity exceeds sale') END;
END;
CREATE INDEX IF NOT EXISTS sales_day ON sales(bazaar_day_id,cashier_user_id);
CREATE INDEX IF NOT EXISTS recent_sales ON sales(bazaar_day_id,completed_at);
CREATE INDEX IF NOT EXISTS movements_product ON stock_movements(product_id,stock_movement_id);
CREATE INDEX IF NOT EXISTS audit_time ON audit_events(audit_event_id DESC);
CREATE TABLE IF NOT EXISTS receipt_printers (
 receipt_printer_id INTEGER PRIMARY KEY,
 terminal_id INTEGER NOT NULL UNIQUE REFERENCES terminals(terminal_id),
 token_hash TEXT NOT NULL UNIQUE, printer_name TEXT NOT NULL DEFAULT '',
 paper_width_mm INTEGER NOT NULL DEFAULT 80 CHECK(paper_width_mm IN (58,80)),
 paper_size TEXT NOT NULL DEFAULT 'roll_80' CHECK(paper_size IN ('roll_58','roll_80','letter')),
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 available_printers_json TEXT NOT NULL DEFAULT '[]', last_seen_at TEXT,
 configured_by_user_id INTEGER NOT NULL REFERENCES users(user_id), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipt_print_jobs (
 receipt_print_job_id INTEGER PRIMARY KEY,
 sale_id INTEGER NOT NULL REFERENCES sales(sale_id),
 terminal_id INTEGER NOT NULL REFERENCES terminals(terminal_id),
 job_kind TEXT NOT NULL CHECK(job_kind IN ('automatic','copy')),
 printer_name TEXT NOT NULL, paper_width_mm INTEGER NOT NULL CHECK(paper_width_mm IN (58,80)),
 paper_size TEXT NOT NULL DEFAULT 'roll_80' CHECK(paper_size IN ('roll_58','roll_80','letter')),
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','claimed','submitted','failed')),
 requested_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
 created_at TEXT NOT NULL, claimed_at TEXT, finished_at TEXT, error_message TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_automatic_print_per_sale ON receipt_print_jobs(sale_id) WHERE job_kind='automatic';
PRAGMA user_version=10;
