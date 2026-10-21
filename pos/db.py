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
        if schema_version not in (0, 1, 2):
            raise RuntimeError('Unsupported database version. Restore the matching application.')
        db.execute('PRAGMA journal_mode=WAL')
        if schema_version == 1:
            db.execute("ALTER TABLE receipt_printers ADD COLUMN paper_size TEXT NOT NULL DEFAULT 'roll_80' CHECK(paper_size IN ('roll_58','roll_80','letter'))")
            db.execute("ALTER TABLE receipt_print_jobs ADD COLUMN paper_size TEXT NOT NULL DEFAULT 'roll_80' CHECK(paper_size IN ('roll_58','roll_80','letter'))")
        db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
        db.execute('INSERT OR IGNORE INTO system_settings(system_setting_id,instance_key,created_at) VALUES(1,?,?)',
                   (secrets.token_hex(24),now()))
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
            (SELECT product_id,SUM(quantity_change) q FROM stock_movements GROUP BY product_id) m USING(product_id)
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
          day=None, before=None, after=None, reason=None, approved=None, username=None):
    db.execute('''INSERT INTO audit_events(bazaar_day_id,actor_user_id,terminal_id,attempted_username,
        action,entity_type,entity_key,before_json,after_json,reason,approved_by_user_id,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (day, actor, terminal, username, action, entity_type,
        str(entity_key) if entity_key is not None else None,
        json.dumps(before, ensure_ascii=False) if before is not None else None,
        json.dumps(after, ensure_ascii=False) if after is not None else None, reason, approved, now()))
