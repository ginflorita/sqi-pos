"""Preview or apply safe updates from a product masterlist to existing POS products."""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

from import_masterlist import read_rows

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pos.db import audit, connect, transaction


def catalog(db):
    return {row['sku'].casefold(): dict(row) for row in db.execute('''
        SELECT p.*, c.name category_name,
            (SELECT amount_minor FROM product_prices WHERE product_id=p.product_id
             ORDER BY price_id DESC LIMIT 1) selling_price_minor
        FROM products p JOIN categories c USING(category_id)''')}


def make_plan(rows, db):
    products = catalog(db)
    drafts = {row['sku'].casefold() for row in db.execute('SELECT sku FROM product_import_drafts')}
    categories = {row['name'].casefold(): row['category_id']
                  for row in db.execute('SELECT category_id,name FROM categories WHERE active=1')}
    existing_barcodes = {row['barcode'].casefold(): row['sku'].casefold()
                         for row in products.values() if row['barcode']}
    sku_counts = Counter(row['sku'].casefold() for row in rows if row['sku'])
    barcode_counts = Counter(row['barcode'].casefold() for row in rows if row['barcode'])
    changes = []
    unresolved = []
    counts = Counter()
    for row in rows:
        sku = row['sku'].casefold()
        if sku_counts[sku] > 1:
            unresolved.append((row['row'], row['sku'], 'Repeated item code in workbook'))
            counts['repeated_item_code_rows'] += 1
            continue
        if sku not in products:
            if sku in drafts:
                counts['draft_rows'] += 1
                unresolved.append((row['row'], row['sku'], 'Import draft, not yet a product; review its missing or shared values'))
            else:
                counts['new_rows'] += 1
                unresolved.append((row['row'], row['sku'], 'Not an existing product'))
            continue
        counts['matched_product_rows'] += 1
        old = products[sku]
        update = {}
        for name in ('description', 'short_description', 'unit', 'unit_description'):
            value = row[name]
            if name in ('description', 'unit') and not value:
                unresolved.append((row['row'], row['sku'], f'Missing {name.replace("_", " ")}; existing value retained'))
            elif len(value) <= {'description': 200, 'short_description': 120,
                                'unit': 20, 'unit_description': 80}[name] and value != old[name]:
                update[name] = value
        if row['category_name'] and row['category_name'].casefold() != old['category_name'].casefold():
            category_id = categories.get(row['category_name'].casefold())
            if category_id:
                update['category_id'] = category_id
            else:
                unresolved.append((row['row'], row['sku'], 'Category is not in the POS; existing category retained'))
        barcode = row['barcode']
        if barcode and barcode != old['barcode']:
            key = barcode.casefold()
            if barcode_counts[key] > 1:
                counts['shared_barcode_product_rows'] += 1
                unresolved.append((row['row'], row['sku'], f'Shared barcode {barcode}; existing barcode retained'))
            elif key in existing_barcodes and existing_barcodes[key] != sku:
                counts['assigned_barcode_product_rows'] += 1
                unresolved.append((row['row'], row['sku'], f'Barcode {barcode} belongs to another product'))
            elif len(barcode) <= 80:
                update['barcode'] = barcode
                counts['barcode_updates'] += 1
            else:
                unresolved.append((row['row'], row['sku'], 'Barcode exceeds 80 characters'))
        if row['amount_minor'] is not None and (row['amount_minor'] != old['unit_price_minor'] or row['amount_minor'] != old['selling_price_minor']):
            counts['price_difference_rows'] += 1
            unresolved.append((row['row'], row['sku'], 'Workbook price differs; price retained for separate review'))
        if update:
            changes.append({'row': row['row'], 'sku': row['sku'], 'product_id': old['product_id'],
                            'before': {name: old[name] for name in update}, 'after': update})
    counts['updated_product_rows'] = len(changes)
    counts['unchanged_product_rows'] = counts['matched_product_rows'] - len(changes)
    absent = sorted(row['sku'] for key, row in products.items() if key not in sku_counts)
    return changes, unresolved, absent, dict(counts)


def plan_hash(changes, unresolved, absent, counts):
    raw = json.dumps([changes, unresolved, absent, counts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def backup_database(db_path, directory):
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    target = directory / f'pre-masterlist-sync-{timestamp}.sqlite3'
    with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(target)) as copy:
        source.backup(copy)
        valid = copy.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not copy.execute('PRAGMA foreign_key_check').fetchone()
    if not valid:
        target.unlink(missing_ok=True)
        raise RuntimeError('Backup verification failed; no products were changed.')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    parser.add_argument('--database', type=Path, default=ROOT / 'data' / 'pos.sqlite3')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-file-sha256')
    parser.add_argument('--expected-plan-sha256')
    args = parser.parse_args()
    source = args.workbook.resolve()
    database = args.database.resolve()
    if not source.is_file() or not database.is_file():
        parser.error('Choose an existing workbook and database.')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if args.apply and source_hash != args.expected_file_sha256:
        parser.error('The workbook changed since preview; rerun preview.')
    sheet, rows = read_rows(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        parser.error('The workbook changed while it was being read; rerun preview.')
    with closing(connect(database)) as db:
        changes, unresolved, absent, counts = make_plan(rows, db)
    digest = plan_hash(changes, unresolved, absent, counts)
    print(f'Sheet: {sheet}; source rows: {len(rows)}')
    print('Counts:', json.dumps(counts, sort_keys=True))
    print('Existing products absent from workbook:', len(absent))
    print('File SHA256:', source_hash)
    print('Plan SHA256:', digest)
    if not args.apply:
        return
    if digest != args.expected_plan_sha256:
        parser.error('The catalog or plan changed since preview; rerun preview.')
    if counts.get('price_difference_rows'):
        parser.error('Price differences need separate review before this update.')
    if not changes:
        print('No existing products need updates.')
        return
    backup = backup_database(database, database.parent / 'backups')
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('The workbook changed after backup; no products were updated.')
    with closing(connect(database)) as db, transaction(db):
        if db.execute("SELECT 1 FROM purchase_tickets WHERE state='open' LIMIT 1").fetchone():
            raise RuntimeError('An order is open; complete or cancel it before syncing products.')
        current = make_plan(rows, db)
        if plan_hash(*current) != digest:
            raise RuntimeError('The catalog changed after backup; no products were updated.')
        for change in changes:
            fields = change['after']
            assignments = ','.join(f'{name}=?' for name in fields)
            db.execute(f'UPDATE products SET {assignments} WHERE product_id=?',
                       (*fields.values(), change['product_id']))
            audit(db, 'product.masterlist_updated', 'products', change['product_id'],
                  before=change['before'], after={**fields, 'source_row': change['row'],
                                                   'source_sha256': source_hash},
                  reason=f'Product masterlist sync: {source.name}')
    with closing(connect(database)) as db:
        updated = catalog(db)
        for change in changes:
            if any(updated[change['sku'].casefold()][name] != value for name, value in change['after'].items()):
                raise RuntimeError(f'Post-update verification failed for {change["sku"]}.')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Post-update database integrity check failed.')
    report = database.parent / 'imports' / f'masterlist-sync-{datetime.now().strftime("%Y%m%d-%H%M%S")}.txt'
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'Source: {source}', f'Worksheet: {sheet}', f'File SHA256: {source_hash}',
             f'Plan SHA256: {digest}', f'Verified pre-update backup: {backup}',
             'Scope: existing products matched by ITEM CODE; no price, stock, active status, or product IDs changed.',
             '', 'Counts:']
    lines += [f'  {name}: {value}' for name, value in sorted(counts.items())]
    lines += ['', f'Existing products absent from workbook ({len(absent)}):']
    lines += [f'  {sku}' for sku in absent]
    lines += ['', f'Rows needing follow-up ({len(unresolved)}):']
    lines += [f'  Excel row {number} | {sku} | {reason}' for number, sku, reason in unresolved]
    groups = {}
    for row in rows:
        if row['barcode']:
            groups.setdefault(row['barcode'].casefold(), []).append(row)
    shared = {code: items for code, items in groups.items() if len(items) > 1}
    lines += ['', f'Shared workbook barcodes ({len(shared)} codes across {sum(map(len, shared.values()))} rows; each item needs a unique code):']
    lines += [f'  {items[0]["barcode"]}: ' + ', '.join(f'{item["sku"]} (row {item["row"]})' for item in items)
              for _, items in sorted(shared.items())]
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Backup:', backup)
    print('Review:', report)


if __name__ == '__main__':
    main()
