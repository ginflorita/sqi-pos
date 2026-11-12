"""Import a reviewed eight-column product masterlist into the local POS."""
import argparse
import hashlib
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pos.db import audit, connect, initialize, now, transaction


HEADERS = ('ITEM CODE', 'BARCODE', 'LONG DESCRIPTION', 'SHORT DESCRIPTION',
           'UNIT', 'UNIT DESCRIPTION', 'UNIT PRICE', 'CATEGORY')
ROOT = Path(__file__).resolve().parent.parent


def text(value):
    return '' if value is None else str(value).strip()


def price_minor(value):
    raw = text(value)
    if not raw:
        return None, 'Missing unit price'
    try:
        amount = Decimal(raw.replace(',', ''))
        cents = amount * 100
        if not amount.is_finite() or cents != cents.to_integral_value() or cents <= 0 or cents > 100_000_000_00:
            raise ValueError()
        return int(cents), None
    except (InvalidOperation, ValueError):
        return None, 'Invalid unit price'


def read_rows(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook['Template'] if 'Template' in workbook else workbook.active
        headings = tuple(' '.join(text(v).upper().split()) for v in next(sheet.iter_rows(max_row=1, values_only=True))[:8])
        if headings != HEADERS:
            raise ValueError('The first eight columns do not match the requested masterlist headers.')
        rows = []
        for number, values in enumerate(sheet.iter_rows(min_row=2, max_col=8, values_only=True), 2):
            if not any(text(value) for value in values):
                continue
            if len(rows) >= 5000:
                raise ValueError('The masterlist may contain up to 5,000 populated rows.')
            code, barcode, description, short, unit, unit_description, raw_price, category = values
            amount, price_issue = price_minor(raw_price)
            row = {'row': number, 'sku': text(code), 'barcode': text(barcode) or None,
                   'description': text(description), 'short_description': text(short),
                   'unit': text(unit), 'unit_description': text(unit_description),
                   'amount_minor': amount, 'price_text': text(raw_price),
                   'category_name': text(category), 'issues': []}
            for name, limit in (('sku', 60), ('barcode', 80), ('description', 200),
                                ('short_description', 120), ('unit', 20),
                                ('unit_description', 80), ('category_name', 80)):
                value = row[name] or ''
                if len(value) > limit or any(ord(char) < 32 for char in value):
                    row['issues'].append(f'Invalid {name.replace("_", " ")}')
            for name in ('sku', 'description', 'unit', 'category_name'):
                if not row[name]:
                    row['issues'].append(f'Missing {name.replace("_", " ")}')
            if price_issue:
                row['issues'].append(price_issue)
            rows.append(row)
        return sheet.title, rows
    finally:
        workbook.close()


def classify(rows, db):
    skus = Counter(row['sku'].casefold() for row in rows if row['sku'])
    barcodes = Counter(row['barcode'].casefold() for row in rows if row['barcode'])
    existing_skus = {sku.casefold() for (sku,) in db.execute('SELECT sku FROM products')}
    existing_barcodes = {barcode.casefold() for (barcode,) in db.execute('SELECT barcode FROM products WHERE barcode IS NOT NULL')}
    for row in rows:
        if row['sku'] and skus[row['sku'].casefold()] > 1:
            row['issues'].append('Duplicate item code in workbook')
        if row['barcode'] and barcodes[row['barcode'].casefold()] > 1:
            row['issues'].append('Duplicate barcode in workbook')
        if row['sku'].casefold() in existing_skus:
            row['issues'].append('Item code already in products')
        if row['barcode'] and row['barcode'].casefold() in existing_barcodes:
            row['issues'].append('Barcode already in products')
    return rows


def backup_database(source, directory):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'pre-masterlist-import-{datetime.now().strftime("%Y%m%d-%H%M%S")}.sqlite3'
    if target.exists():
        raise ValueError(f'Backup already exists: {target}')
    with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
        live.backup(copy)
        if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or copy.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Backup integrity check failed; import cancelled.')
    return target


def write_report(path, workbook, digest, backup, rows, counts):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'Source: {workbook.name}', f'SHA256: {digest}',
             f'Verified database backup: {backup}',
             'Mapping: ITEM CODE → products.sku; BARCODE → products.barcode; '
             'LONG DESCRIPTION → products.description; SHORT DESCRIPTION → products.short_description; '
             'UNIT → products.unit; UNIT DESCRIPTION → products.unit_description; '
             'UNIT PRICE → products.unit_price_minor; initial selling price → product_prices.amount_minor; '
             'CATEGORY → categories.name / products.category_id.',
             'No stock quantities were included, so new products start at zero on hand.',
             '', f"Source rows: {len(rows)}", f"Products imported: {counts['imported']}",
             f"Pending unique items saved as drafts: {counts['staged']}",
             f"Unresolved source rows: {sum(bool(row['issues']) for row in rows)}", '',
             'Rows needing review (Excel row | ITEM CODE | BARCODE | UNIT PRICE | Issue):']
    for row in rows:
        if row['issues']:
            lines.append(f"{row['row']} | {row['sku']} | {row['barcode'] or '—'} | "
                         f"{row['price_text'] or '—'} | {'; '.join(row['issues'])}")
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    parser.add_argument('--database', type=Path, default=ROOT / 'data' / 'pos.sqlite3')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-sha256', help='SHA256 shown by preview; required for --apply')
    args = parser.parse_args()
    workbook = args.workbook.resolve()
    database = args.database.resolve()
    if not workbook.is_file() or not database.is_file():
        parser.error('Choose an existing workbook and database.')
    source_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if args.apply and source_hash != args.expected_sha256:
        parser.error('Workbook changed since preview, or the preview SHA256 was not supplied.')
    sheet, rows = read_rows(workbook)
    with connect(database) as db:
        classify(rows, db)
    ready = [row for row in rows if not row['issues']]
    pending = [row for row in rows if row['issues']]
    print(f'Sheet: {sheet}; source rows: {len(rows)}; ready: {len(ready)}; unresolved: {len(pending)}')
    print(f'SHA256: {source_hash}')
    if not args.apply:
        return
    backup = backup_database(database, database.parent.parent / 'backups')
    initialize(database)
    counts = {'imported': 0, 'staged': 0, 'drafts_removed': 0}
    with connect(database) as db, transaction(db):
        managers = db.execute("SELECT user_id FROM users WHERE role='manager' AND active=1 ORDER BY user_id").fetchall()
        if len(managers) != 1:
            raise RuntimeError('Import requires exactly one active manager account for price attribution.')
        manager_id = managers[0]['user_id']
        categories = {record['name'].casefold(): record['category_id'] for record in db.execute('SELECT category_id,name FROM categories')}
        for row in ready:
            category_key = row['category_name'].casefold()
            if category_key not in categories:
                categories[category_key] = db.execute('INSERT INTO categories(name) VALUES(?)',
                                                      (row['category_name'],)).lastrowid
            product_id = db.execute('''INSERT INTO products
                (sku,barcode,description,short_description,category_id,unit,unit_description,unit_price_minor,active)
                VALUES(?,?,?,?,?,?,?,?,1)''',
                (row['sku'],row['barcode'],row['description'],row['short_description'],
                 categories[category_key],row['unit'],row['unit_description'],row['amount_minor'])).lastrowid
            db.execute('''INSERT INTO product_prices(product_id,amount_minor,effective_at,changed_by_user_id,reason)
                VALUES(?,?,?,?,?)''', (product_id,row['amount_minor'],now(),manager_id,
                                      f'Initial price from {workbook.name}, row {row["row"]}'))
            counts['drafts_removed'] += db.execute('DELETE FROM product_import_drafts WHERE sku=? COLLATE NOCASE',
                                                   (row['sku'],)).rowcount
            counts['imported'] += 1
        for row in pending:
            if not row['sku'] or 'Duplicate item code in workbook' in row['issues'] or 'Item code already in products' in row['issues']:
                continue
            issue = '; '.join(row['issues'])
            values = (row['description'], workbook.name, manager_id, now(), row['barcode'],
                      row['short_description'], row['unit'], row['unit_description'],
                      row['category_name'], row['amount_minor'], row['amount_minor'], row['row'], issue)
            old = db.execute('SELECT product_import_draft_id FROM product_import_drafts WHERE sku=? COLLATE NOCASE',
                             (row['sku'],)).fetchone()
            if old:
                db.execute('''UPDATE product_import_drafts SET description=?,source_filename=?,imported_by_user_id=?,imported_at=?,
                    barcode=?,short_description=?,unit=?,unit_description=?,category_name=?,amount_minor=?,unit_price_minor=?,source_row=?,import_issue=?
                    WHERE product_import_draft_id=?''', (*values, old['product_import_draft_id']))
            else:
                db.execute('''INSERT INTO product_import_drafts
                    (sku,description,source_filename,imported_by_user_id,imported_at,barcode,short_description,
                     unit,unit_description,category_name,amount_minor,unit_price_minor,source_row,import_issue)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (row['sku'], *values))
            counts['staged'] += 1
        audit(db, 'products.masterlist_imported', 'products', actor=None,
              reason='Local workbook import requested by user',
              after={'source_filename': workbook.name, 'sha256': source_hash, 'sheet': sheet,
                     'source_rows': len(rows), 'unresolved_rows': len(pending), **counts})
    report = database.parent / 'imports' / f'masterlist-review-{datetime.now().strftime("%Y%m%d-%H%M%S")}.txt'
    write_report(report, workbook, source_hash, backup, rows, counts)
    print(f'Imported {counts["imported"]} products; staged {counts["staged"]} incomplete items; removed {counts["drafts_removed"]} completed drafts.')
    print(f'Backup: {backup}')
    print(f'Review: {report}')


if __name__ == '__main__':
    main()
