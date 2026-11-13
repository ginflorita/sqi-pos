import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def connect(path):
    db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('PRAGMA synchronous=FULL')
    return db


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        schema_version = db.execute('PRAGMA user_version').fetchone()[0]
        if schema_version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            raise RuntimeError('Unsupported database version. Restore the matching application.')
        db.execute('PRAGMA journal_mode=WAL')
        if schema_version == 1:
            db.execute("ALTER TABLE receipt_printers ADD COLUMN paper_size TEXT NOT NULL DEFAULT 'roll_80' CHECK(paper_size IN ('roll_58','roll_80','letter'))")
            db.execute("ALTER TABLE receipt_print_jobs ADD COLUMN paper_size TEXT NOT NULL DEFAULT 'roll_80' CHECK(paper_size IN ('roll_58','roll_80','letter'))")
        if schema_version in (1, 2, 3, 4):
            for table, column, definition in (
                ('system_settings', 'discount_percent_bp', 'INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent_bp BETWEEN 0 AND 9900)'),
                ('purchase_tickets', 'discount_selected', 'INTEGER NOT NULL DEFAULT 0 CHECK(discount_selected IN (0,1))'),
                ('sales', 'discount_percent_bp', 'INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent_bp BETWEEN 0 AND 9900)'),
                ('purchase_tickets', 'discount_percent_bp', 'INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent_bp BETWEEN 0 AND 9900)'),
            ):
                if column not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        if schema_version in (1, 2, 3, 4, 5):
            for table, column, definition in (
                ('products', 'short_description', "TEXT NOT NULL DEFAULT ''"),
                ('products', 'unit_description', "TEXT NOT NULL DEFAULT ''"),
                ('product_import_drafts', 'barcode', 'TEXT'),
                ('product_import_drafts', 'short_description', "TEXT NOT NULL DEFAULT ''"),
                ('product_import_drafts', 'unit', "TEXT NOT NULL DEFAULT ''"),
                ('product_import_drafts', 'unit_description', "TEXT NOT NULL DEFAULT ''"),
                ('product_import_drafts', 'category_name', "TEXT NOT NULL DEFAULT ''"),
                ('product_import_drafts', 'amount_minor', 'INTEGER CHECK(amount_minor>0)'),
                ('product_import_drafts', 'source_row', 'INTEGER'),
                ('product_import_drafts', 'import_issue', "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        if schema_version in (1, 2, 3, 4, 5, 6):
            for table in ('products', 'product_import_drafts'):
                if 'unit_price_minor' not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN unit_price_minor INTEGER CHECK(unit_price_minor>0)')
            db.execute('''UPDATE products SET unit_price_minor=(
                SELECT amount_minor FROM product_prices WHERE product_id=products.product_id
                ORDER BY price_id DESC LIMIT 1) WHERE unit_price_minor IS NULL''')
            if db.execute('SELECT 1 FROM products WHERE unit_price_minor IS NULL LIMIT 1').fetchone():
                raise RuntimeError('A product has no current price. Set its price before upgrading the database.')
            db.execute('''UPDATE product_import_drafts SET unit_price_minor=amount_minor
                WHERE unit_price_minor IS NULL AND amount_minor IS NOT NULL''')
        if schema_version in (1, 2, 3, 4, 5, 6, 7):
            if 'short_description_snapshot' not in {row['name'] for row in db.execute('PRAGMA table_info(sale_lines)')}:
                db.execute("ALTER TABLE sale_lines ADD COLUMN short_description_snapshot TEXT NOT NULL DEFAULT ''")
        if 1 <= schema_version <= 8:
            # SQLite cannot widen a CHECK constraint in place. Preserve user IDs so
            # every existing sale, session, shift, and audit reference remains valid.
            db.execute('PRAGMA foreign_keys=OFF')
            try:
                with transaction(db):
                    db.execute('''CREATE TABLE users_new (
                        user_id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('it_admin','manager','cashier')),
                        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                        created_by_user_id INTEGER REFERENCES users(user_id), created_at TEXT NOT NULL,
                        disabled_at TEXT)''')
                    db.execute('''INSERT INTO users_new
                        (user_id,username,display_name,password_hash,role,active,created_by_user_id,created_at,disabled_at)
                        SELECT user_id,username,display_name,password_hash,
                            CASE WHEN username='ginflorita' COLLATE NOCASE THEN 'it_admin' ELSE role END,
                            active,created_by_user_id,created_at,disabled_at FROM users''')
                    db.execute('DROP TABLE users')
                    db.execute('ALTER TABLE users_new RENAME TO users')
            finally:
                db.execute('PRAGMA foreign_keys=ON')
        if 1 <= schema_version <= 9:
            for table, column, definition in (
                ('bazaars', 'event_name', "TEXT NOT NULL DEFAULT 'Event 1'"),
                ('bazaars', 'archive_backup', 'TEXT'),
                ('audit_events', 'bazaar_id', 'INTEGER REFERENCES bazaars(bazaar_id)'),
            ):
                if column not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            db.execute('DROP TRIGGER IF EXISTS immutable_audit_events_UPDATE')
            db.execute('''UPDATE audit_events SET bazaar_id=COALESCE(
                (SELECT bazaar_id FROM bazaar_days WHERE bazaar_day_id=audit_events.bazaar_day_id),
                (SELECT bazaar_id FROM bazaars ORDER BY bazaar_id DESC LIMIT 1))
                WHERE bazaar_id IS NULL''')
        db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
        db.execute('INSERT OR IGNORE INTO system_settings(system_setting_id,instance_key,created_at) VALUES(1,?,?)',
                   (secrets.token_hex(24),now()))
        if schema_version in (1, 2, 3, 4):
            old_rate = db.execute('SELECT discount_percent_bp FROM system_settings WHERE system_setting_id=1').fetchone()[0]
            if old_rate:
                db.execute('INSERT OR IGNORE INTO discount_rates(percent_bp,created_at) VALUES(?,?)', (old_rate,now()))
                db.execute("UPDATE purchase_tickets SET discount_percent_bp=? WHERE state='open' AND discount_selected=1", (old_rate,))
        immutable = ('sales', 'sale_lines', 'payments', 'stock_movements', 'product_prices',
                     'sale_corrections', 'correction_lines', 'audit_events', 'receipt_events',
                     'stock_documents', 'stock_document_lines', 'checkout_requests')
        for table in immutable:
            for action in ('UPDATE', 'DELETE'):
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action}
                    BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Historical records are immutable'); END''')
        result = db.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Database integrity check failed. Checkout is disabled.')
        mismatch = db.execute('''SELECT b.product_id FROM stock_balances b LEFT JOIN
            (SELECT product_id,SUM(quantity_change) q FROM stock_movements
                WHERE bazaar_id=COALESCE((SELECT bazaar_id FROM bazaars WHERE status='active'),
                    (SELECT MAX(bazaar_id) FROM bazaars)) GROUP BY product_id) m USING(product_id)
            WHERE b.quantity_on_hand<>COALESCE(m.q,0) LIMIT 1''').fetchone()
        if mismatch:
            raise RuntimeError('Stock ledger does not reconcile. Checkout is disabled.')
    db.close()


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def audit(db, action, entity_type, entity_key=None, actor=None, terminal=None,
          day=None, before=None, after=None, reason=None, approved=None, username=None, bazaar=None):
    if bazaar is None and day is not None:
        row = db.execute('SELECT bazaar_id FROM bazaar_days WHERE bazaar_day_id=?', (day,)).fetchone()
        bazaar = row['bazaar_id'] if row else None
    if bazaar is None:
        row = db.execute('''SELECT bazaar_id FROM bazaars
            ORDER BY CASE status WHEN 'active' THEN 1 ELSE 0 END DESC,bazaar_id DESC LIMIT 1''').fetchone()
        bazaar = row['bazaar_id'] if row else None
    db.execute('''INSERT INTO audit_events(bazaar_day_id,actor_user_id,terminal_id,attempted_username,
        action,entity_type,entity_key,before_json,after_json,reason,approved_by_user_id,created_at,bazaar_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (day, actor, terminal, username, action, entity_type,
        str(entity_key) if entity_key is not None else None,
        json.dumps(before, ensure_ascii=False) if before is not None else None,
        json.dumps(after, ensure_ascii=False) if after is not None else None, reason, approved, now(), bazaar))
