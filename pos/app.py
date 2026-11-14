import csv
import hashlib
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from zipfile import BadZipFile
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, has_request_context, jsonify, make_response, render_template, request, send_file
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

from .db import audit, connect, digest, initialize, now, transaction as database_transaction
from .build import build_id
from .report_export import export_report


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def require(condition, message, status=400):
    if not condition:
        raise Problem(message, status)


def text_field(data, name, limit=200, optional=False, label=None):
    value = data.get(name, '')
    display_name = label or name.replace('_', ' ')
    require(isinstance(value, str), f'{display_name} must be text.')
    value = value.strip()
    require((optional or bool(value)) and len(value) <= limit, f'Enter {display_name} (maximum {limit} characters).')
    require(not any(ord(c) < 32 for c in value), 'Control characters are not allowed.')
    return value


def integer(data, name, minimum=0, maximum=100_000_000_00):
    value = data.get(name)
    require(type(value) is int and minimum <= value <= maximum, f'Invalid {name.replace("_", " ")}.')
    return value


def allocate_discount(lines, percent_bp):
    """Allocate an order discount in cents while leaving every unit refundable."""
    gross = [line['quantity'] * line['amount_minor'] for line in lines]
    capacity = [amount - line['quantity'] for amount, line in zip(gross, lines)]
    total_capacity = sum(capacity)
    total_discount = min((sum(gross) * percent_bp + 5000) // 10000, total_capacity)
    if not total_discount:
        return [0] * len(lines)
    portions = [total_discount * available for available in capacity]
    discounts = [portion // total_capacity for portion in portions]
    remaining = total_discount - sum(discounts)
    order = sorted(range(len(lines)), key=lambda index: (-(portions[index] % total_capacity), index))
    for index in order[:remaining]:
        discounts[index] += 1
    return discounts


def refund_for_quantity(line, already_returned, quantity):
    """Refund the actual paid line amount, distributing odd cents across units."""
    total = line['line_total_minor']
    sold = line['quantity']
    return (already_returned + quantity) * total // sold - already_returned * total // sold


def excel_text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def product_rows_from_workbook(raw):
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, OSError, ValueError):
        raise Problem('Choose a valid Excel .xlsx workbook.')
    try:
        selected = None
        for worksheet in workbook.worksheets:
            max_row = min(worksheet.max_row or 0, 50)
            max_column = min(worksheet.max_column or 0, 100)
            for row_number, row in enumerate(worksheet.iter_rows(min_row=1, max_row=max_row,
                                                                  max_col=max_column, values_only=True), 1):
                headers = {}
                for column, value in enumerate(row):
                    header = re.sub(r'[^A-Z0-9]+', ' ', excel_text(value).upper()).strip()
                    if header and header not in headers:
                        headers[header] = column
                if 'ITEM CODE' in headers and 'DESCRIPTION' in headers:
                    selected = worksheet, row_number, headers['ITEM CODE'], headers['DESCRIPTION']
                    break
            if selected:
                break
        require(selected, 'The workbook needs ITEM CODE and DESCRIPTION column headers.')
        worksheet, header_row, sku_column, description_column = selected
        products, seen, rejected, duplicate_rows, populated_rows = [], set(), [], 0, 0
        max_column = max(sku_column, description_column) + 1
        for row_number, row in enumerate(worksheet.iter_rows(min_row=header_row + 1,
                                                              max_col=max_column, values_only=True), header_row + 1):
            sku, description = excel_text(row[sku_column]), excel_text(row[description_column])
            if not sku and not description:
                continue
            populated_rows += 1
            require(populated_rows <= 5000, 'The workbook can contain up to 5,000 populated product rows.')
            if not sku or not description:
                rejected.append({'row': row_number, 'reason': 'Both ITEM CODE and DESCRIPTION are required.'})
                continue
            if len(sku) > 60 or len(description) > 200 or any(ord(character) < 32 for character in sku + description):
                rejected.append({'row': row_number, 'reason': 'ITEM CODE or DESCRIPTION is too long or contains unsupported characters.'})
                continue
            normalized = sku.casefold()
            if normalized in seen:
                duplicate_rows += 1
                continue
            seen.add(normalized)
            products.append((sku, description, row_number))
        require(populated_rows, 'No product rows were found below the headers.')
        return worksheet.title, products, rejected, duplicate_rows
    finally:
        workbook.close()


def request_key(data):
    value = text_field(data, 'request_key', 100)
    require(bool(re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', value)), 'Invalid request key.')
    return value


def payload():
    value = request.get_json(silent=True)
    require(isinstance(value, dict), 'A JSON object is required.')
    return value


def signed_in(manager=False):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            require(g.user is not None, 'Please sign in.', 401)
            require(not manager or g.user['role'] in ('manager', 'it_admin'), 'Manager access is required.', 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def create_app(database=None, backups=None, secure=False, testing=False):
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    running_build = build_id()
    app.config.update(DATABASE=str(database or root / 'data' / 'pos.sqlite3'),
                      BACKUP_DIR=str(backups or os.environ.get('POS_BACKUP_DIR', root / 'backups')),
                      SECURE_COOKIES=secure, TESTING=testing, MAX_CONTENT_LENGTH=6 * 1024 * 1024)
    trusted=['localhost','127.0.0.1','[::1]',socket.gethostname().lower()]
    try:
        trusted.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    app.config['TRUSTED_HOSTS']=trusted
    initialize(app.config['DATABASE'])
    identity_db=connect(app.config['DATABASE'])
    try:
        cookie_tag=digest(identity_db.execute('SELECT instance_key FROM system_settings WHERE system_setting_id=1').fetchone()[0])[:16]
    finally:
        identity_db.close()
    session_cookie,device_cookie,csrf_cookie=(f'pos_{kind}_{cookie_tag}' for kind in ('session','device','csrf'))
    app.config['POS_COOKIE_NAMES']=(csrf_cookie,session_cookie,device_cookie)
    backup_lock = threading.Lock()

    def db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    @contextmanager
    def transaction(connection):
        with database_transaction(connection):
            # Recheck account access after acquiring the write lock. A user may
            # have been disabled while this request was waiting for another sale.
            if has_request_context() and connection is getattr(g, 'db', None) and g.user and request.path not in ('/api/login','/api/setup','/api/logout'):
                live=connection.execute('''SELECT u.active,u.role,u.password_hash,a.expires_at,a.last_seen_at
                    FROM auth_sessions a JOIN users u USING(user_id)
                    WHERE a.auth_session_id=? AND a.user_id=? AND a.terminal_id=?''',
                    (g.auth_session,g.user['user_id'],g.terminal['terminal_id'])).fetchone()
                epoch=int(time.time())
                require(live and live['active'] and live['role']==g.user['role']
                        and live['expires_at']>epoch and epoch-live['last_seen_at']<1800,
                        'Your account access changed. Sign in again before continuing.',403)
                g.user['password_hash']=live['password_hash']
            yield connection

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    def event(action, entity, key=None, **kwargs):
        audit(db(), action, entity, key, actor=g.user['user_id'] if g.user else None,
              terminal=g.terminal['terminal_id'] if g.terminal else None, **kwargs)

    def active_bazaar():
        row = db().execute("SELECT * FROM bazaars WHERE status='active'").fetchone()
        require(row, 'Ask the IT System Administrator to start the next event.', 409)
        return row

    def report_bazaar():
        requested = request.args.get('event_id', '')
        if requested:
            require(g.user['role'] == 'it_admin', 'Only the IT System Administrator can open archived events.', 403)
            require(requested.isdecimal() and int(requested)>0, 'Choose a valid event.')
            row = db().execute('SELECT * FROM bazaars WHERE bazaar_id=?', (int(requested),)).fetchone()
            require(row, 'Event not found.', 404)
            return row
        return db().execute("SELECT * FROM bazaars WHERE status='active'").fetchone()

    def require_it_admin():
        require(g.user and g.user['role']=='it_admin' and g.user['username'].lower()=='ginflorita',
                'Only the IT System Administrator can start or end an event.', 403)

    def active_day():
        row = db().execute("SELECT * FROM bazaar_days WHERE status='open'").fetchone()
        require(row, 'A manager must open a business day first.', 409)
        return row

    def shift():
        row = db().execute("SELECT * FROM shifts WHERE cashier_user_id=? AND terminal_id=? AND status='open'",
                           (g.user['user_id'], g.terminal['terminal_id'])).fetchone()
        require(row, 'Open a cashier shift on this laptop first.', 409)
        require(row['bazaar_day_id'] == active_day()['bazaar_day_id'], 'This shift does not belong to the open day.', 409)
        return row

    def reauth(data):
        require(g.user and g.user['role'] in ('manager', 'it_admin'), 'Manager access is required.', 403)
        password = data.get('manager_password', '')
        require(isinstance(password, str) and len(password) <= 1024, 'Manager password is required.', 403)
        key = f'reauth:{g.user["user_id"]}'
        with transaction(db()):
            limit = db().execute('SELECT * FROM login_limits WHERE bucket_key=?', (key,)).fetchone()
            if limit and time.time() - limit['window_started_at'] < 900 and limit['attempts'] >= 5:
                raise Problem('Too many approval attempts. Try again in 15 minutes.', 429)
            valid = check_password_hash(g.user['password_hash'], password)
            if valid:
                db().execute('DELETE FROM login_limits WHERE bucket_key=?', (key,))
            else:
                bump_limit(key)
                event('approval.failed', 'users', g.user['user_id'])
        require(valid, 'The manager password is incorrect.', 403)

    def bump_limit(key):
        epoch = int(time.time())
        db().execute('''INSERT INTO login_limits(bucket_key,attempts,window_started_at) VALUES(?,1,?)
            ON CONFLICT(bucket_key) DO UPDATE SET attempts=CASE WHEN excluded.window_started_at-window_started_at>=900 THEN 1 ELSE attempts+1 END,
            window_started_at=CASE WHEN excluded.window_started_at-window_started_at>=900 THEN excluded.window_started_at ELSE window_started_at END''', (key, epoch))

    @app.before_request
    def context():
        g.user, g.terminal, g.auth_session = None, None, None
        csrf = request.cookies.get(csrf_cookie, '')
        g.csrf = csrf if re.fullmatch(r'[A-Za-z0-9_-]{43}', csrf) else secrets.token_urlsafe(32)
        if not request.path.startswith('/api/'):
            return
        if request.path in ('/api/print-agent/poll', '/api/print-agent/result'):
            # Helpers authenticate with a separately paired, terminal-scoped token.
            require(not request.headers.get('Origin'), 'Browser requests are not accepted by the print helper API.', 403)
            return
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            require(request.headers.get('Origin') in (None, request.host_url.rstrip('/')), 'Request origin rejected.', 403)
            require(bool(csrf) and secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), g.csrf), 'Refresh the page and try again.', 403)
        token = request.cookies.get(session_cookie, '')
        if token:
            row = db().execute('''SELECT a.*,u.username,u.display_name,u.password_hash,u.role,u.active,
                t.device_key_hash FROM auth_sessions a JOIN users u USING(user_id)
                JOIN terminals t USING(terminal_id) WHERE a.token_hash=?''', (digest(token),)).fetchone()
            epoch = int(time.time())
            device = request.cookies.get(device_cookie, '')
            if row and row['active'] and row['expires_at'] > epoch and epoch - row['last_seen_at'] < 1800 and secrets.compare_digest(row['device_key_hash'], digest(device)):
                g.user = dict(row)
                g.terminal = {'terminal_id': row['terminal_id']}
                g.auth_session = row['auth_session_id']
                background_read = request.method == 'GET' and request.path == '/api/catalog' and request.args.get('background') == '1'
                if request.path != '/api/state' and not background_read and epoch - row['last_seen_at'] >= 30:
                    db().execute('UPDATE auth_sessions SET last_seen_at=? WHERE auth_session_id=?', (epoch, g.auth_session))

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith('/api/') or request.path == '/':
            response.headers['Cache-Control'] = 'no-store'
        if getattr(g, 'csrf', None) and request.cookies.get(csrf_cookie) != g.csrf:
            response.set_cookie(csrf_cookie, g.csrf, httponly=True, samesite='Strict', secure=secure)
        if secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(Problem)
    def problem(error):
        if request.path.startswith('/api/') and request.method != 'GET' and error.status in (400, 403, 409, 429):
            try:
                event('request.rejected', 'request', reason=error.message, after={'path': request.path})
            except sqlite3.Error:
                pass
        return jsonify(error=error.message), error.status

    @app.errorhandler(sqlite3.IntegrityError)
    def constraint(error):
        app.logger.warning('Database constraint rejected an operation: %s', error)
        return jsonify(error='This operation conflicts with an existing record or stock rule. Refresh and review it.'), 409

    @app.errorhandler(sqlite3.OperationalError)
    def unavailable(error):
        app.logger.error('Database unavailable: %s', error)
        return jsonify(error='The database is busy or unavailable. Check the ticket before retrying checkout.'), 503

    @app.errorhandler(413)
    def oversized(error):
        return jsonify(error='The upload is too large. Images can be up to 5 MB and product workbooks up to 6 MB.'), 413

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/server-info')
    def server_info():
        # A loaded process retains its startup identity even while update files
        # are copied over it. The launcher checks this before opening the app.
        result = {'build': running_build, 'restart_needed': build_id() != running_build}
        if request.remote_addr in ('127.0.0.1', '::1'):
            result['pid'] = os.getpid()
        return jsonify(result)

    @app.get('/api/state')
    def state():
        result = {'setup_required': not bool(db().execute('SELECT 1 FROM users LIMIT 1').fetchone()), 'csrf': g.csrf,
                  'user': None, 'terminal': g.terminal, 'bazaar': None, 'day': None, 'shift': None}
        if g.user:
            result['user'] = {k: g.user[k] for k in ('user_id', 'username', 'display_name', 'role')}
            bazaar = db().execute("SELECT * FROM bazaars WHERE status='active'").fetchone()
            day = db().execute("SELECT * FROM bazaar_days WHERE status='open'").fetchone()
            s = db().execute("SELECT * FROM shifts WHERE cashier_user_id=? AND terminal_id=? AND status='open'", (g.user['user_id'], g.terminal['terminal_id'])).fetchone()
            result.update(bazaar=dict(bazaar) if bazaar else None, day=dict(day) if day else None, shift=dict(s) if s else None)
            result['backup'] = dict(r) if (r := db().execute('SELECT * FROM backup_runs ORDER BY backup_run_id DESC LIMIT 1').fetchone()) else None
        return jsonify(result)

    def establish(user_id, terminal_name):
        device = request.cookies.get(device_cookie) or secrets.token_urlsafe(32)
        row = db().execute('SELECT * FROM terminals WHERE device_key_hash=?', (digest(device),)).fetchone()
        if not row:
            tid = db().execute('INSERT INTO terminals(name,device_key_hash,approved,approved_by_user_id,last_seen_at) VALUES(?,?,?,?,?)',
                               (terminal_name, digest(device), 1, None, now())).lastrowid
            audit(db(), 'terminal.registered', 'terminals', tid, actor=user_id, terminal=tid, after={'name': terminal_name})
        else:
            tid = row['terminal_id']
            db().execute('UPDATE terminals SET approved=1,approved_by_user_id=NULL,last_seen_at=? WHERE terminal_id=?',(now(),tid))
        token, epoch = secrets.token_urlsafe(48), int(time.time())
        old = request.cookies.get(session_cookie)
        if old:
            db().execute('DELETE FROM auth_sessions WHERE token_hash=?', (digest(old),))
        db().execute('INSERT INTO auth_sessions(token_hash,user_id,terminal_id,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?,?)',
                     (digest(token), user_id, tid, epoch, epoch, epoch + 43200))
        audit(db(), 'login.succeeded', 'users', user_id, actor=user_id, terminal=tid)
        response = jsonify(ok=True)
        response.set_cookie(session_cookie, token, httponly=True, samesite='Strict', secure=secure)
        response.set_cookie(device_cookie, device, max_age=31536000, httponly=True, samesite='Strict', secure=secure)
        return response

    @app.post('/api/setup')
    def setup():
        require(ipaddress.ip_address(request.remote_addr or '0.0.0.0').is_loopback, 'First setup must be completed on the host laptop.', 403)
        data = payload()
        username = text_field(data, 'username', 50).lower()
        require(bool(re.fullmatch(r'[a-z0-9_.-]{3,50}', username)), 'Use 3–50 letters, digits, dots, dashes, or underscores for the username.')
        password = text_field(data, 'password', 1024)
        require(len(password) >= 12, 'Use a password of at least 12 characters.')
        display = text_field(data, 'display_name', 80)
        name = text_field(data, 'bazaar_name', 120, label='business name')
        tz = text_field(data, 'timezone', 80)
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            raise Problem('Enter a valid IANA timezone, for example Asia/Manila.')
        currency = text_field(data, 'currency_code', 3).upper()
        require(currency in ('PHP', 'USD', 'EUR', 'GBP', 'SGD', 'MYR', 'THB', 'TWD', 'HKD', 'AUD', 'CAD', 'NZD', 'INR'), 'Choose a supported currency with two decimal places.')
        with transaction(db()):
            require(not db().execute('SELECT 1 FROM users LIMIT 1').fetchone(), 'Setup is already complete.', 409)
            uid = db().execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                               (username, display, generate_password_hash(password, method='scrypt'), 'it_admin' if username == 'ginflorita' else 'manager', now())).lastrowid
            bid = db().execute('INSERT INTO bazaars(name,starts_on,timezone,currency_code,status,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                               (name, datetime.now(ZoneInfo(tz)).date().isoformat(), tz, currency, 'active', uid, now())).lastrowid
            audit(db(), 'setup.completed', 'bazaars', bid, actor=uid, after={'name': name, 'currency': currency, 'timezone': tz})
            response = establish(uid, 'Manager browser')
        return response

    @app.post('/api/login')
    def login():
        data = payload()
        username = text_field(data, 'username', 50).lower()
        password = data.get('password', '')
        require(isinstance(password, str) and len(password) <= 1024, 'Invalid sign-in details.')
        keys = ['ip:' + digest(request.remote_addr or ''), 'user:' + digest(username)]
        with transaction(db()):
            epoch = int(time.time())
            for key in keys:
                row = db().execute('SELECT * FROM login_limits WHERE bucket_key=?', (key,)).fetchone()
                require(not row or epoch-row['window_started_at'] >= 900 or row['attempts'] < (20 if key.startswith('ip:') else 5),
                        'Too many sign-in attempts. Try again in 15 minutes.', 429)
            user = db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            # A fixed dummy hash avoids a fast path for unknown usernames.
            valid = check_password_hash(user['password_hash'] if user else app.config['DUMMY_HASH'], password)
            if not user or not valid or not user['active']:
                for key in keys:
                    bump_limit(key)
                audit(db(), 'login.failed', 'users', username=username)
                response = jsonify(error='The username or password is incorrect.'), 401
            else:
                db().execute('DELETE FROM login_limits WHERE bucket_key=?', (keys[1],))
                response = establish(user['user_id'], (user['display_name'] + ' browser')[:80])
        return response

    app.config['DUMMY_HASH'] = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    @app.post('/api/logout')
    def logout():
        if g.auth_session:
            with transaction(db()):
                db().execute('DELETE FROM auth_sessions WHERE auth_session_id=?', (g.auth_session,))
                event('logout', 'users', g.user['user_id'])
        response = jsonify(ok=True)
        response.delete_cookie(session_cookie, secure=secure, httponly=True, samesite='Strict')
        return response

    @app.get('/api/catalog')
    @signed_in()
    def catalog():
        products = db().execute('''SELECT p.*,c.name category_name,b.quantity_on_hand,pr.price_id,pr.amount_minor,
            pr.amount_minor AS selling_price_minor,
            i.product_image_id,EXISTS(SELECT 1 FROM stock_movements m WHERE m.product_id=p.product_id
                AND m.bazaar_id=(SELECT bazaar_id FROM bazaars WHERE status='active')) has_stock_history
            FROM products p JOIN categories c USING(category_id) JOIN stock_balances b USING(product_id)
            LEFT JOIN product_prices pr ON pr.price_id=(SELECT MAX(price_id) FROM product_prices WHERE product_id=p.product_id)
            LEFT JOIN product_images i ON i.product_id=p.product_id AND i.superseded_at IS NULL ORDER BY p.description''').fetchall()
        drafts = db().execute('SELECT * FROM product_import_drafts ORDER BY description').fetchall() if g.user['role'] in ('manager', 'it_admin') else []
        return jsonify(products=[dict(r) for r in products], drafts=[dict(r) for r in drafts],
                       categories=[dict(r) for r in db().execute('SELECT * FROM categories ORDER BY name')])

    @app.post('/api/categories')
    @signed_in(True)
    def category_create():
        data = payload()
        name = text_field(data, 'name', 80)
        with transaction(db()):
            cid = db().execute('INSERT INTO categories(name) VALUES(?)', (name,)).lastrowid
            event('category.created', 'categories', cid, after={'name': name})
        return jsonify(category_id=cid)

    def uploaded_product_workbook():
        upload = request.files.get('workbook')
        require(upload and upload.filename, 'Choose an Excel .xlsx workbook.')
        filename = re.split(r'[\\/]', upload.filename)[-1].strip()
        require(filename.lower().endswith('.xlsx') and len(filename) <= 255, 'Choose an Excel .xlsx workbook.')
        raw = upload.read(6 * 1024 * 1024 + 1)
        require(raw and len(raw) <= 6 * 1024 * 1024, 'The workbook must be 6 MB or smaller.')
        sheet, rows, rejected, duplicate_rows = product_rows_from_workbook(raw)
        return filename, sheet, rows, rejected, duplicate_rows

    @app.post('/api/products/import/preview')
    @signed_in(True)
    def product_import_preview():
        filename, sheet, rows, rejected, duplicate_rows = uploaded_product_workbook()
        existing_skus = {row['sku'].casefold() for row in db().execute(
            'SELECT sku FROM products UNION ALL SELECT sku FROM product_import_drafts')}
        products = [{'sku': sku, 'description': description, 'row': row_number}
                    for sku, description, row_number in rows if sku.casefold() not in existing_skus]
        existing = len(rows) - len(products)
        return jsonify(filename=filename, sheet=sheet, products=products, ready=len(products),
                       existing=existing, duplicate_rows=duplicate_rows, rejected_rows=len(rejected),
                       rejected=rejected[:20])

    @app.post('/api/products/import')
    @signed_in(True)
    def product_import():
        filename, sheet, rows, rejected, duplicate_rows = uploaded_product_workbook()
        imported = 0
        existing = 0
        with transaction(db()):
            existing_skus = {row['sku'].casefold() for row in db().execute(
                'SELECT sku FROM products UNION ALL SELECT sku FROM product_import_drafts')}
            for sku, description, row_number in rows:
                if sku.casefold() in existing_skus:
                    existing += 1
                    continue
                db().execute('''INSERT INTO product_import_drafts
                    (sku,description,source_filename,imported_by_user_id,imported_at) VALUES(?,?,?,?,?)''',
                    (sku, description, filename, g.user['user_id'], now()))
                existing_skus.add(sku.casefold())
                imported += 1
            event('products.bulk_imported', 'product_import_drafts', after={
                'filename': filename, 'sheet': sheet, 'imported': imported, 'existing': existing,
                'duplicate_rows': duplicate_rows, 'rejected_rows': len(rejected)})
        return jsonify(imported=imported, existing=existing, duplicate_rows=duplicate_rows,
                       rejected_rows=len(rejected), rejected=rejected[:20], sheet=sheet)

    @app.post('/api/products')
    @app.put('/api/products/<int:product_id>')
    @signed_in(True)
    def product_save(product_id=None):
        data = payload()
        draft_id = data.get('draft_id')
        if draft_id is not None:
            require(type(draft_id) is int and draft_id > 0 and product_id is None, 'Invalid imported product.')
        fields = [text_field(data, 'sku', 60), text_field(data, 'barcode', 80, True) or None,
                  text_field(data, 'description', 200), text_field(data, 'short_description', 120, True),
                  integer(data, 'category_id', 1), text_field(data, 'unit', 20),
                  text_field(data, 'unit_description', 80, True)]
        require(type(data.get('active', True)) is bool, 'Invalid product status.')
        amount = integer(data, 'selling_price_minor' if 'selling_price_minor' in data else 'amount_minor', 1)
        if 'selling_price_minor' in data and 'amount_minor' in data:
            require(amount == integer(data, 'amount_minor', 1), 'Selling price values do not match.')
        unit_amount = integer(data, 'unit_price_minor', 1) if 'unit_price_minor' in data else amount
        opening_quantity = integer(data, 'quantity', 0, 1_000_000) if product_id is None and 'quantity' in data else 0
        stock_request_key = request_key(data) if opening_quantity else None
        with transaction(db()):
            require(db().execute('SELECT 1 FROM categories WHERE category_id=? AND active=1', (fields[4],)).fetchone(), 'Choose an active category.')
            draft = None
            if draft_id is not None:
                draft = db().execute('SELECT * FROM product_import_drafts WHERE product_import_draft_id=?', (draft_id,)).fetchone()
                require(draft, 'This imported product was already completed or is no longer available.', 409)
            before = None
            if product_id:
                old = db().execute('SELECT * FROM products WHERE product_id=?', (product_id,)).fetchone()
                require(old, 'Product not found.', 404)
                require('unit_price_minor' not in data or unit_amount == old['unit_price_minor'],
                        'The company unit price is locked and cannot be changed.', 409)
                before = dict(old)
                db().execute('UPDATE products SET sku=?,barcode=?,description=?,short_description=?,category_id=?,unit=?,unit_description=?,active=? WHERE product_id=?', (*fields, int(data.get('active', True)), product_id))
            else:
                product_id = db().execute('''INSERT INTO products
                    (sku,barcode,description,short_description,category_id,unit,unit_description,unit_price_minor,active)
                    VALUES(?,?,?,?,?,?,?,?,?)''', (*fields, unit_amount, int(data.get('active', True)))).lastrowid
            current = db().execute('SELECT amount_minor FROM product_prices WHERE product_id=? ORDER BY price_id DESC LIMIT 1', (product_id,)).fetchone()
            if before:
                before['amount_minor']=current[0] if current else None
                before['selling_price_minor']=current[0] if current else None
            reason=None
            if not current:
                reason='Initial selling price'
            elif current[0]!=amount:
                reason=text_field(data,'reason',300,optional=True)
                require(reason,'Add a reason for changing the selling price.')
            if not current or current[0] != amount:
                db().execute('INSERT INTO product_prices(product_id,amount_minor,effective_at,changed_by_user_id,reason) VALUES(?,?,?,?,?)',
                             (product_id, amount, now(), g.user['user_id'], reason))
            if draft is not None:
                db().execute('DELETE FROM product_import_drafts WHERE product_import_draft_id=?', (draft_id,))
            event('product.updated' if before else 'product.created', 'products', product_id, before=before,
                  after={**dict(zip(('sku','barcode','description','short_description','category_id','unit','unit_description'), fields)),
                         'active': data.get('active', True), 'unit_price_minor': old['unit_price_minor'] if before else unit_amount,
                         'selling_price_minor': amount, 'amount_minor': amount,
                         'import_draft_id': draft_id, 'opening_quantity': opening_quantity},
                  reason=reason, approved=g.user['user_id'])
            if opening_quantity:
                bazaar = active_bazaar()
                day = db().execute("SELECT * FROM bazaar_days WHERE status='open'").fetchone()
                day_id = day['bazaar_day_id'] if day else None
                stamp = now()
                stock_reason = 'Opening stock'
                normalized = [{'product_id': product_id, 'quantity': opening_quantity}]
                request_hash = digest(json.dumps(['opening', normalized, stock_reason, 'Product setup'], sort_keys=True))
                stock_document_id = db().execute('''INSERT INTO stock_documents
                    (bazaar_id,bazaar_day_id,document_type,reference_no,reason,request_key,status,
                     created_by_user_id,approved_by_user_id,created_at,approved_at)
                    VALUES(?,?,?,?,?,?,'posted',?,?,?,?)''',
                    (bazaar['bazaar_id'], day_id, 'opening', 'Product setup', stock_reason,
                     stock_request_key, g.user['user_id'], g.user['user_id'], stamp, stamp)).lastrowid
                stock_line_id = db().execute('''INSERT INTO stock_document_lines
                    (stock_document_id,product_id,quantity_change,expected_quantity,counted_quantity)
                    VALUES(?,?,?,?,?)''',
                    (stock_document_id, product_id, opening_quantity, None, None)).lastrowid
                db().execute('''INSERT INTO stock_movements
                    (bazaar_id,bazaar_day_id,product_id,quantity_change,stock_document_line_id,created_by_user_id,created_at)
                    VALUES(?,?,?,?,?,?,?)''',
                    (bazaar['bazaar_id'], day_id, product_id, opening_quantity, stock_line_id,
                     g.user['user_id'], stamp))
                event('stock.posted', 'stock_documents', stock_document_id, day=day_id,
                      after={'document_type': 'opening', 'lines': normalized, 'request_hash': request_hash},
                      reason=stock_reason, approved=g.user['user_id'])
        return jsonify(product_id=product_id)

    @app.post('/api/products/<int:product_id>/image')
    @signed_in(True)
    def image_upload(product_id):
        upload = request.files.get('image')
        require(upload, 'Choose an image.')
        raw = upload.read(5 * 1024 * 1024 + 1)
        require(len(raw) <= 5 * 1024 * 1024, 'Maximum image size is 5 MB.')
        try:
            with Image.open(io.BytesIO(raw)) as source:
                require(source.format in ('JPEG', 'PNG', 'WEBP') and source.width * source.height <= 12_000_000,
                        'Use a JPEG, PNG, or WebP image up to 12 megapixels.')
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1200, 1200))
                full = io.BytesIO()
                image.save(full, 'JPEG', quality=85)
                image.thumbnail((320, 320))
                thumbnail = io.BytesIO()
                image.save(thumbnail, 'JPEG', quality=80)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise Problem('This file is not a supported image.')
        content = full.getvalue()
        with transaction(db()):
            require(db().execute('SELECT 1 FROM products WHERE product_id=?', (product_id,)).fetchone(), 'Product not found.', 404)
            db().execute('UPDATE product_images SET superseded_at=? WHERE product_id=? AND superseded_at IS NULL', (now(), product_id))
            iid = db().execute('''INSERT INTO product_images(product_id,image_data,thumbnail_data,mime_type,size_bytes,sha256,uploaded_by_user_id,uploaded_at)
                VALUES(?,?,?,?,?,?,?,?)''', (product_id, content, thumbnail.getvalue(), 'image/jpeg', len(content), digest(content), g.user['user_id'], now())).lastrowid
            event('image.updated', 'product_images', iid, after={'product_id': product_id, 'sha256': digest(content)}, approved=g.user['user_id'])
        return jsonify(product_image_id=iid)

    @app.get('/api/images/<int:image_id>')
    @signed_in()
    def image_get(image_id):
        row = db().execute('SELECT thumbnail_data FROM product_images WHERE product_image_id=?', (image_id,)).fetchone()
        require(row, 'Image not found.', 404)
        return send_file(io.BytesIO(row[0]), mimetype='image/jpeg')

    @app.post('/api/days/open')
    @signed_in(True)
    def day_open():
        data = payload()
        reauth(data)
        business_date = text_field(data, 'business_date', 10)
        try:
            require(date.fromisoformat(business_date).isoformat() == business_date, 'Use YYYY-MM-DD.')
        except ValueError:
            raise Problem('Enter a valid business date.')
        with transaction(db()):
            bazaar = active_bazaar()
            require(not db().execute("SELECT 1 FROM bazaar_days WHERE status='open'").fetchone(), 'Close the current day first.', 409)
            last = db().execute('SELECT MAX(day_number) n,MAX(business_date) d FROM bazaar_days WHERE bazaar_id=?', (bazaar['bazaar_id'],)).fetchone()
            require(not last['d'] or business_date > last['d'], 'The next business date must follow the previous day.')
            did = db().execute('''INSERT INTO bazaar_days(bazaar_id,day_number,business_date,status,opened_at,opened_by_user_id)
                VALUES(?,?,?,'open',?,?)''', (bazaar['bazaar_id'], (last['n'] or 0)+1, business_date, now(), g.user['user_id'])).lastrowid
            event('day.opened', 'bazaar_days', did, day=did, after={'business_date': business_date}, approved=g.user['user_id'])
        return jsonify(bazaar_day_id=did)

    @app.post('/api/days/close')
    @signed_in(True)
    def day_close():
        data = payload()
        reauth(data)
        with transaction(db()):
            day = active_day()
            open_shift = db().execute('''SELECT s.shift_id,s.cashier_user_id,u.display_name
                FROM shifts s JOIN users u ON u.user_id=s.cashier_user_id
                WHERE s.status='open' ORDER BY s.shift_id LIMIT 1''').fetchone()
            if open_shift:
                who = 'Your' if open_shift['cashier_user_id'] == g.user['user_id'] else open_shift['display_name'] + "'s"
                raise Problem(f'{who} shift #{open_shift["shift_id"]} is still open. Close it in Cashier shifts first.', 409)
            require(not db().execute("SELECT 1 FROM purchase_tickets WHERE state='open'").fetchone(), 'Complete or cancel all open tickets first.', 409)
            db().execute("UPDATE bazaar_days SET status='closed',closed_at=?,closed_by_user_id=? WHERE bazaar_day_id=?", (now(), g.user['user_id'], day['bazaar_day_id']))
            event('day.closed', 'bazaar_days', day['bazaar_day_id'], day=day['bazaar_day_id'], approved=g.user['user_id'])
        backup = perform_backup(g.user['user_id'])
        return jsonify(ok=True, backup=backup)

    @app.get('/api/events')
    @signed_in(True)
    def events_get():
        require_it_admin()
        return jsonify(events=[dict(row) for row in db().execute(
            'SELECT * FROM bazaars ORDER BY bazaar_id DESC')])

    @app.post('/api/events/rename')
    @signed_in(True)
    def event_rename():
        require_it_admin()
        data=payload()
        name=text_field(data,'event_name',120,label='event name')
        reauth(data)
        with transaction(db()):
            current=active_bazaar()
            db().execute('UPDATE bazaars SET event_name=? WHERE bazaar_id=?',(name,current['bazaar_id']))
            event('event.renamed','bazaars',current['bazaar_id'],bazaar=current['bazaar_id'],
                  before={'event_name':current['event_name']},after={'event_name':name},
                  approved=g.user['user_id'])
        return jsonify(ok=True)

    @app.post('/api/events/end')
    @signed_in(True)
    def event_end():
        require_it_admin()
        reauth(payload())
        with transaction(db()):
            current = active_bazaar()
            require(not db().execute("SELECT 1 FROM bazaar_days WHERE status='open'").fetchone(),
                    'Ask the manager to close the business day first.', 409)
            require(not db().execute("SELECT 1 FROM shifts WHERE status='open'").fetchone(),
                    'Close every cashier shift first.', 409)
            require(not db().execute("SELECT 1 FROM purchase_tickets WHERE state='open'").fetchone(),
                    'Complete or cancel every unpaid order first.', 409)
            require(not db().execute("SELECT 1 FROM receipt_print_jobs WHERE status IN ('queued','claimed')").fetchone(),
                    'Review pending receipt print jobs in Printer before ending this event.',409)
            db().execute("UPDATE bazaars SET status='closed',ends_on=? WHERE bazaar_id=?",
                         (datetime.now(ZoneInfo(current['timezone'])).date().isoformat(),current['bazaar_id']))
            event('event.ended','bazaars',current['bazaar_id'],bazaar=current['bazaar_id'],
                  after={'event_name':current['event_name']},approved=g.user['user_id'])
        backup=perform_backup(g.user['user_id'])
        if backup['status']=='verified':
            with transaction(db()):
                db().execute('UPDATE bazaars SET archive_backup=? WHERE bazaar_id=?',
                             (backup['filename'],current['bazaar_id']))
            return jsonify(ok=True,archive=backup)
        return jsonify(error='The event ended, but its archive backup failed. Retry the archive before starting a new event.'),503

    @app.post('/api/events/archive')
    @signed_in(True)
    def event_archive_retry():
        require_it_admin()
        reauth(payload())
        require(not db().execute("SELECT 1 FROM bazaars WHERE status='active'").fetchone(),
                'End the current event before archiving.', 409)
        last=db().execute('SELECT * FROM bazaars ORDER BY bazaar_id DESC LIMIT 1').fetchone()
        require(last and last['status']=='closed' and not last['archive_backup'],
                'There is no event waiting for an archive.', 409)
        backup=perform_backup(g.user['user_id'])
        require(backup['status']=='verified','The archive backup failed. Check Backups and try again.',503)
        with transaction(db()):
            db().execute('UPDATE bazaars SET archive_backup=? WHERE bazaar_id=?',
                         (backup['filename'],last['bazaar_id']))
        return jsonify(ok=True,archive=backup)

    @app.post('/api/events/start')
    @signed_in(True)
    def event_start():
        require_it_admin()
        data=payload()
        name=text_field(data,'event_name',120,label='event name')
        reauth(data)
        with transaction(db()):
            require(not db().execute("SELECT 1 FROM bazaars WHERE status='active'").fetchone(),
                    'End the current event first.',409)
            previous=db().execute('SELECT * FROM bazaars ORDER BY bazaar_id DESC LIMIT 1').fetchone()
            require(previous and previous['status']=='closed' and previous['archive_backup'],
                    'Verify the previous event archive before starting another event.',409)
            require((Path(app.config['BACKUP_DIR'])/previous['archive_backup']).is_file(),
                    'The previous event archive file is missing. Restore it before starting another event.',409)
            bid=db().execute('''INSERT INTO bazaars(name,starts_on,timezone,currency_code,status,
                created_by_user_id,created_at,event_name) VALUES(?,?,?,?,'active',?,?,?)''',
                (previous['name'],datetime.now(ZoneInfo(previous['timezone'])).date().isoformat(),
                 previous['timezone'],previous['currency_code'],g.user['user_id'],now(),name)).lastrowid
            db().execute('UPDATE stock_balances SET quantity_on_hand=0,updated_at=?',(now(),))
            event('event.started','bazaars',bid,bazaar=bid,
                  after={'event_name':name,'stock_on_hand':0},approved=g.user['user_id'])
        return jsonify(ok=True,event_id=bid)

    def cash_expected(sid):
        opening = db().execute('SELECT opening_cash_minor FROM shifts WHERE shift_id=?', (sid,)).fetchone()[0]
        incoming = db().execute('SELECT COALESCE(SUM(p.amount_minor),0) FROM payments p JOIN sales s USING(sale_id) WHERE s.shift_id=?', (sid,)).fetchone()[0]
        outgoing = db().execute('SELECT COALESCE(SUM(p.amount_minor),0) FROM payments p JOIN sale_corrections c USING(sale_correction_id) WHERE c.shift_id=?', (sid,)).fetchone()[0]
        other = db().execute("SELECT COALESCE(SUM(CASE direction WHEN 'in' THEN amount_minor ELSE -amount_minor END),0) FROM cash_movements WHERE shift_id=?", (sid,)).fetchone()[0]
        return opening + incoming - outgoing + other

    @app.get('/api/shifts')
    @signed_in()
    def shifts_get():
        status = request.args.get('status')
        require(status in (None, 'open', 'closed'), 'Choose open or closed shifts.', 400)
        current=report_bazaar()
        filters, params = ['d.bazaar_id=?'], [current['bazaar_id'] if current else -1]
        if g.user['role'] not in ('manager', 'it_admin'):
            filters.append('s.cashier_user_id=?')
            params.append(g.user['user_id'])
        if status:
            filters.append('s.status=?')
            params.append(status)
        clause = ' WHERE ' + ' AND '.join(filters) if filters else ''
        total = db().execute('SELECT COUNT(*) FROM shifts s JOIN bazaar_days d USING(bazaar_day_id)' + clause, params).fetchone()[0]
        page, page_size = 1, 200
        if status == 'closed':
            page_arg, size_arg = request.args.get('page', '1'), request.args.get('page_size', '10')
            require(page_arg.isdecimal() and size_arg.isdecimal(), 'Choose a valid shift history page.', 400)
            page, page_size = int(page_arg), int(size_arg)
            require(1 <= page <= 100000 and 1 <= page_size <= 50, 'Choose a valid shift history page.', 400)
        query = 'SELECT s.*,u.display_name,t.name terminal_name,d.day_number FROM shifts s JOIN users u ON u.user_id=s.cashier_user_id JOIN terminals t USING(terminal_id) JOIN bazaar_days d USING(bazaar_day_id)' + clause + ' ORDER BY s.shift_id DESC'
        if status == 'closed':
            rows = db().execute(query + ' LIMIT ? OFFSET ?', (*params, page_size, (page - 1) * page_size)).fetchall()
        elif status == 'open':
            rows = db().execute(query, params).fetchall()
        else:
            rows = db().execute(query + ' LIMIT 200', params).fetchall()
        result=[]
        for row in rows:
            ticket=db().execute("SELECT purchase_ticket_id,ticket_number,version FROM purchase_tickets WHERE owner_user_id=? AND state='open'",(row['cashier_user_id'],)).fetchone() if row['status']=='open' else None
            order=None
            if ticket:
                order={**dict(ticket),'lines':[dict(l) for l in db().execute('SELECT p.description,l.quantity FROM ticket_lines l JOIN products p USING(product_id) WHERE purchase_ticket_id=?',(ticket['purchase_ticket_id'],))]}
            result.append({**dict(row),'live_expected_minor':cash_expected(row['shift_id']) if row['status']=='open' else row['expected_cash_minor'],'open_ticket':order})
        return jsonify(shifts=result, total=total, page=page, page_size=page_size)

    @app.post('/api/shifts/open')
    @signed_in()
    def shift_open():
        data = payload()
        opening = integer(data, 'opening_cash_minor')
        with transaction(db()):
            day = active_day()
            terminal_shift = db().execute('''SELECT s.shift_id,s.cashier_user_id,u.display_name
                FROM shifts s JOIN users u ON u.user_id=s.cashier_user_id
                WHERE s.terminal_id=? AND s.status='open' ''', (g.terminal['terminal_id'],)).fetchone()
            if terminal_shift:
                if terminal_shift['cashier_user_id'] == g.user['user_id']:
                    raise Problem(f'Your shift #{terminal_shift["shift_id"]} is already open here. Refresh the page to continue.', 409)
                action = ('Select Cancel, open Cashier shifts, count the drawer, and choose Manager close.' if g.user['role'] in ('manager', 'it_admin')
                          else 'Select Cancel and ask a manager to count and close it in Cashier shifts.')
                raise Problem(f'Another cashier’s shift is still open on this POS: {terminal_shift["display_name"]}, shift #{terminal_shift["shift_id"]}.\n{action} Then open your shift. Signing out alone does not close a shift.', 409)
            user_shift = db().execute("SELECT shift_id FROM shifts WHERE cashier_user_id=? AND status='open'",
                                      (g.user['user_id'],)).fetchone()
            if user_shift:
                raise Problem(f'Your shift #{user_shift["shift_id"]} is still open on another POS. Finish any unpaid orders, count and close that shift there, then try again.', 409)
            sid = db().execute("INSERT INTO shifts(bazaar_day_id,cashier_user_id,terminal_id,opening_cash_minor,opened_at,status) VALUES(?,?,?,?,?,'open')",
                (day['bazaar_day_id'], g.user['user_id'], g.terminal['terminal_id'], opening, now())).lastrowid
            event('shift.opened', 'shifts', sid, day=day['bazaar_day_id'], after={'opening_cash_minor': opening})
        return jsonify(shift_id=sid)

    @app.post('/api/shifts/close')
    @signed_in()
    def shift_close():
        data = payload()
        counted = integer(data, 'counted_cash_minor')
        with transaction(db()):
            s = shift()
            require(not db().execute("SELECT 1 FROM purchase_tickets WHERE owner_user_id=? AND state='open'", (g.user['user_id'],)).fetchone(), 'Complete or cancel your open tickets first.', 409)
            expected = cash_expected(s['shift_id'])
            db().execute("UPDATE shifts SET expected_cash_minor=?,counted_cash_minor=?,variance_minor=?,closed_at=?,status='closed' WHERE shift_id=?", (expected, counted, counted-expected, now(), s['shift_id']))
            event('shift.closed', 'shifts', s['shift_id'], day=s['bazaar_day_id'], after={'expected_minor': expected, 'counted_minor': counted, 'variance_minor': counted-expected})
        return jsonify(expected_cash_minor=expected, variance_minor=counted-expected)

    @app.post('/api/shifts/<int:sid>/close')
    @signed_in(True)
    def manager_close_shift(sid):
        data=payload()
        reauth(data)
        counted=integer(data,'counted_cash_minor')
        reason=text_field(data,'reason',300)
        with transaction(db()):
            s=db().execute('SELECT * FROM shifts WHERE shift_id=?',(sid,)).fetchone()
            require(s and s['status']=='open','This shift is already closed or unavailable.',409)
            require(s['bazaar_day_id']==active_day()['bazaar_day_id'],'The shift is not on the current open day.',409)
            order=db().execute("SELECT * FROM purchase_tickets WHERE owner_user_id=? AND state='open'",(s['cashier_user_id'],)).fetchone()
            if order:
                require(data.get('cancel_open_order') is True and data.get('purchase_ticket_id')==order['purchase_ticket_id']
                        and data.get('ticket_version')==order['version'],
                        'Review the current unpaid order and explicitly confirm its cancellation before closing.',409)
                db().execute("UPDATE purchase_tickets SET state='cancelled',version=version+1,updated_at=? WHERE purchase_ticket_id=?",(now(),order['purchase_ticket_id']))
                event('ticket.cancelled_by_manager','purchase_tickets',order['purchase_ticket_id'],day=s['bazaar_day_id'],reason=reason,approved=g.user['user_id'])
            else:
                require(not data.get('purchase_ticket_id'),'The order changed. Refresh this shift before closing.',409)
            expected=cash_expected(sid)
            db().execute("UPDATE shifts SET expected_cash_minor=?,counted_cash_minor=?,variance_minor=?,closed_at=?,status='closed' WHERE shift_id=?",(expected,counted,counted-expected,now(),sid))
            event('shift.closed_by_manager','shifts',sid,day=s['bazaar_day_id'],
                  after={'cashier_user_id':s['cashier_user_id'],'expected_minor':expected,'counted_minor':counted,'variance_minor':counted-expected},reason=reason,approved=g.user['user_id'])
        return jsonify(expected_cash_minor=expected,variance_minor=counted-expected)

    @app.post('/api/cash-movements')
    @signed_in(True)
    def cash_move():
        data = payload()
        reauth(data)
        amount, reason, key = integer(data, 'amount_minor', 1), text_field(data, 'reason', 300), request_key(data)
        direction = data.get('direction')
        require(direction in ('in','out'), 'Choose cash in or out.')
        with transaction(db()):
            old = db().execute('SELECT * FROM cash_movements WHERE request_key=?', (key,)).fetchone()
            if old:
                require(old['amount_minor'] == amount and old['direction'] == direction and old['reason'] == reason and old['created_by_user_id'] == g.user['user_id'], 'This cash request key has different contents.', 409)
                return jsonify(cash_movement_id=old['cash_movement_id'])
            s = shift()
            require(direction != 'out' or cash_expected(s['shift_id']) >= amount, 'Cash out exceeds expected cash in this drawer.', 409)
            mid = db().execute('INSERT INTO cash_movements(shift_id,direction,amount_minor,reason,request_key,created_by_user_id,approved_by_user_id,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (s['shift_id'], direction, amount, reason, key, g.user['user_id'], g.user['user_id'], now())).lastrowid
            event('cash.'+direction, 'cash_movements', mid, day=s['bazaar_day_id'], after={'amount_minor': amount}, reason=reason, approved=g.user['user_id'])
        return jsonify(cash_movement_id=mid)

    @app.post('/api/stock')
    @signed_in(True)
    def stock_post():
        data = payload()
        reauth(data)
        key = request_key(data)
        kind, lines = data.get('document_type'), data.get('lines')
        reference = text_field(data, 'reference_no', 80, True)
        require(kind in ('opening','in'), 'Only opening stock and stock receipts can be posted.')
        reason = text_field(data, 'reason', 300, optional=True)
        if not reason:
            reason = 'Opening stock' if kind == 'opening' else 'Stock received'
        require(isinstance(lines, list) and 1 <= len(lines) <= 200, 'Enter 1–200 stock lines.')
        normalized = []
        for line in lines:
            require(isinstance(line, dict), 'Invalid stock line.')
            pid = integer(line, 'product_id', 1)
            quantity = integer(line, 'quantity', 1, 1_000_000)
            normalized.append({'product_id': pid, 'quantity': quantity})
        require(len({l['product_id'] for l in normalized}) == len(normalized), 'Combine duplicate stock items.')
        request_hash = digest(json.dumps([kind, normalized, reason, reference], sort_keys=True))
        with transaction(db()):
            old = db().execute('SELECT * FROM stock_documents WHERE request_key=?', (key,)).fetchone()
            if old:
                a = db().execute("SELECT after_json FROM audit_events WHERE entity_type='stock_documents' AND entity_key=? AND action='stock.posted'", (str(old['stock_document_id']),)).fetchone()
                require(a and json.loads(a[0])['request_hash'] == request_hash and old['created_by_user_id'] == g.user['user_id'], 'This stock request key has different contents.', 409)
                return jsonify(stock_document_id=old['stock_document_id'])
            bazaar = active_bazaar()
            day = db().execute("SELECT * FROM bazaar_days WHERE status='open'").fetchone()
            require(kind == 'opening' or day, 'Open a business day before posting stock movements.', 409)
            did = day['bazaar_day_id'] if day else None
            sid = db().execute("INSERT INTO stock_documents(bazaar_id,bazaar_day_id,document_type,reference_no,reason,request_key,status,created_by_user_id,approved_by_user_id,created_at,approved_at) VALUES(?,?,?,?,?,?,'posted',?,?,?,?)",
                (bazaar['bazaar_id'], did, kind, reference, reason, key, g.user['user_id'], g.user['user_id'], now(), now())).lastrowid
            for line in normalized:
                balance = db().execute('SELECT * FROM stock_balances WHERE product_id=?', (line['product_id'],)).fetchone()
                require(balance, 'Stock item not found.', 404)
                if kind == 'opening':
                    require(not db().execute('SELECT 1 FROM stock_movements WHERE product_id=? AND bazaar_id=? LIMIT 1',
                                             (line['product_id'],bazaar['bazaar_id'])).fetchone(),
                            'Opening stock is only allowed before an item has movements in this event.', 409)
                change = line['quantity']
                lid = db().execute('INSERT INTO stock_document_lines(stock_document_id,product_id,quantity_change,expected_quantity,counted_quantity) VALUES(?,?,?,?,?)',
                    (sid, line['product_id'], change, None, None)).lastrowid
                if change:
                    db().execute('INSERT INTO stock_movements(bazaar_id,bazaar_day_id,product_id,quantity_change,stock_document_line_id,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                        (bazaar['bazaar_id'], did, line['product_id'], change, lid, g.user['user_id'], now()))
            event('stock.posted', 'stock_documents', sid, day=did, after={'document_type': kind, 'lines': normalized, 'request_hash': request_hash}, reason=reason, approved=g.user['user_id'])
        return jsonify(stock_document_id=sid)

    @app.get('/api/stock')
    @signed_in(True)
    def stock_history():
        rows = db().execute('''SELECT m.*,p.sku,p.description,u.display_name,d.day_number,
            COALESCE(sd.document_type,CASE WHEN m.sale_line_id IS NOT NULL THEN 'sale' ELSE 'return' END) movement_type,
            sd.reason FROM stock_movements m JOIN products p USING(product_id) JOIN users u ON u.user_id=m.created_by_user_id
            LEFT JOIN bazaar_days d USING(bazaar_day_id) LEFT JOIN stock_document_lines dl USING(stock_document_line_id)
            LEFT JOIN stock_documents sd USING(stock_document_id)
            WHERE m.bazaar_id=(SELECT bazaar_id FROM bazaars WHERE status='active')
            ORDER BY m.stock_movement_id DESC LIMIT 500''').fetchall()
        return jsonify(movements=[dict(r) for r in rows])

    @app.get('/api/inventory')
    @signed_in(True)
    def inventory_report():
        bazaar = report_bazaar()
        require(bazaar, 'Ask the IT System Administrator to start the next event.',409)
        dates = {}
        for name in ('from', 'to'):
            value = request.args.get(name, '')
            if value:
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    raise Problem('Use YYYY-MM-DD for inventory dates.')
                require(parsed.isoformat() == value, 'Use YYYY-MM-DD for inventory dates.')
                dates[name] = parsed
        require(not (dates.get('from') and dates.get('to') and dates['from'] > dates['to']),
                'The start date must be on or before the end date.')

        def page_number(name):
            value = request.args.get(name, '1')
            require(value.isascii() and value.isdecimal() and len(value) <= 6 and 1 <= int(value) <= 100000,
                    'Choose a valid inventory page.')
            return int(value)

        product_page = page_number('product_page')
        movement_page = page_number('movement_page')
        category_arg = request.args.get('category_id', '')
        require(not category_arg or (category_arg.isdecimal() and int(category_arg) > 0),
                'Choose a valid category.')
        category_id = int(category_arg) if category_arg else None
        search = request.args.get('q', '').strip()
        require(len(search) <= 120, 'Search for a product using 120 characters or fewer.')

        tz = ZoneInfo(bazaar['timezone'])
        def utc_start(day):
            return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc).isoformat(timespec='microseconds')
        start = utc_start(dates['from']) if dates.get('from') else ''
        end = utc_start(dates['to'] + timedelta(days=1)) if dates.get('to') and dates['to'] < date.max else '9999-12-31T23:59:59+00:00'

        filters, params = [], []
        if category_id:
            filters.append('p.category_id=?')
            params.append(category_id)
        if search:
            filters.append('(p.sku LIKE ? OR p.description LIKE ? OR COALESCE(p.barcode,\'\') LIKE ?)')
            params.extend([f'%{search}%'] * 3)
        where = ' WHERE ' + ' AND '.join(filters) if filters else ''
        product_rows = db().execute('''SELECT p.product_id,p.sku,p.description,p.unit,p.active,
                p.category_id,c.name category_name,COALESCE(SUM(m.quantity_change),0) quantity_on_hand,
                COALESCE(pr.amount_minor,0) amount_minor,
                COALESCE(SUM(CASE WHEN m.created_at<? THEN m.quantity_change ELSE 0 END),0) opening,
                COALESCE(SUM(CASE WHEN m.created_at>=? AND m.created_at<? AND m.stock_document_line_id IS NOT NULL THEN m.quantity_change ELSE 0 END),0) added,
                COALESCE(SUM(CASE WHEN m.created_at>=? AND m.created_at<? AND m.sale_line_id IS NOT NULL THEN -m.quantity_change ELSE 0 END),0) sold,
                COALESCE(SUM(CASE WHEN m.created_at>=? AND m.created_at<? AND m.correction_line_id IS NOT NULL THEN m.quantity_change ELSE 0 END),0) restocked
            FROM products p JOIN categories c USING(category_id) JOIN stock_balances b USING(product_id)
            LEFT JOIN product_prices pr ON pr.price_id=(SELECT MAX(price_id) FROM product_prices WHERE product_id=p.product_id)
            LEFT JOIN stock_movements m ON m.product_id=p.product_id AND m.bazaar_id=?'''+where+'''
            GROUP BY p.product_id ORDER BY p.description COLLATE NOCASE,p.product_id''',
            (start, start, end, start, end, start, end, bazaar['bazaar_id'], *params)).fetchall()
        products = []
        categories = {}
        totals = {'products': 0, 'opening': 0, 'added': 0, 'sold': 0, 'restocked': 0,
                  'closing': 0, 'current': 0, 'zero_products': 0, 'low_products': 0,
                  'retail_value_minor': 0}
        for row in product_rows:
            item = dict(row)
            item['closing'] = item['opening'] + item['added'] - item['sold'] + item['restocked']
            item['retail_value_minor'] = item['closing'] * item['amount_minor']
            item['zero_products'] = int(bool(item['active']) and item['closing'] == 0)
            item['low_products'] = int(bool(item['active']) and 0 < item['closing'] < 6)
            products.append(item)
            category = categories.setdefault(item['category_id'], {'category_id': item['category_id'],
                'category_name': item['category_name'], **{key: 0 for key in totals}})
            for summary in (totals, category):
                summary['products'] += 1
                for key in ('opening', 'added', 'sold', 'restocked', 'closing', 'zero_products',
                            'low_products', 'retail_value_minor'):
                    summary[key] += item[key]
                summary['current'] += item['quantity_on_hand']

        movement_filters = ['m.bazaar_id=?','m.created_at>=?', 'm.created_at<?', *filters]
        movement_params = [bazaar['bazaar_id'],start, end, *params]
        movement_where = ' WHERE ' + ' AND '.join(movement_filters)
        movement_from = ''' FROM stock_movements m JOIN products p USING(product_id)
            JOIN categories c USING(category_id) JOIN users u ON u.user_id=m.created_by_user_id
            LEFT JOIN bazaar_days d USING(bazaar_day_id)
            LEFT JOIN stock_document_lines dl USING(stock_document_line_id)
            LEFT JOIN stock_documents sd USING(stock_document_id)
            LEFT JOIN sale_lines sl USING(sale_line_id)
            LEFT JOIN sales s ON s.sale_id=sl.sale_id
            LEFT JOIN correction_lines cl USING(correction_line_id)
            LEFT JOIN sale_corrections sc ON sc.sale_correction_id=cl.sale_correction_id
            LEFT JOIN sales rs ON rs.sale_id=sc.original_sale_id'''
        movement_total = db().execute('SELECT COUNT(*)' + movement_from + movement_where,
                                      movement_params).fetchone()[0]
        movement_size, product_size = 15, 20
        movement_page = min(movement_page, max(1, (movement_total + movement_size - 1) // movement_size))
        product_page = min(product_page, max(1, (len(products) + product_size - 1) // product_size))
        movements = db().execute('''SELECT m.stock_movement_id,m.created_at,m.quantity_change,
                p.product_id,p.sku,p.description,c.name category_name,u.display_name,d.day_number,
                CASE WHEN m.sale_line_id IS NOT NULL THEN 'sale'
                     WHEN m.correction_line_id IS NOT NULL THEN 'restock'
                     WHEN sd.document_type='opening' THEN 'opening' ELSE 'received' END movement_type,
                COALESCE(s.receipt_number,rs.receipt_number,sd.reference_no,'') reference_no,
                COALESCE(sd.reason,sc.reason,CASE WHEN m.sale_line_id IS NOT NULL THEN 'Completed sale' ELSE '' END) reason
            '''+movement_from+movement_where+''' ORDER BY m.stock_movement_id DESC LIMIT ? OFFSET ?''',
            (*movement_params, movement_size, (movement_page - 1) * movement_size)).fetchall()
        return jsonify(summary=totals,
            categories=sorted(categories.values(), key=lambda item: item['category_name'].casefold()),
            products=products[(product_page - 1) * product_size:product_page * product_size],
            product_total=len(products), product_page=product_page, product_page_size=product_size,
            movements=[dict(row) for row in movements], movement_total=movement_total,
            movement_page=movement_page, movement_page_size=movement_size,
            timezone=bazaar['timezone'],currency_code=bazaar['currency_code'])

    def get_ticket(tid, enforce_owner=True):
        ticket = db().execute('SELECT * FROM purchase_tickets WHERE purchase_ticket_id=?', (tid,)).fetchone()
        require(ticket, 'Ticket not found.', 404)
        if enforce_owner:
            require(ticket['owner_user_id'] == g.user['user_id'] and ticket['terminal_id'] == g.terminal['terminal_id'], 'This ticket belongs to another cashier or laptop.', 403)
        return ticket

    @app.get('/api/discount')
    @signed_in()
    def discount_get():
        manager = g.user['role'] in ('manager', 'it_admin')
        return jsonify(rates=[dict(row) for row in db().execute(
            'SELECT discount_rate_id,percent_bp,active,created_at,disabled_at FROM discount_rates' +
            ('' if manager else ' WHERE active=1') + ' ORDER BY active DESC,percent_bp')])

    @app.post('/api/discount')
    @signed_in(True)
    def discount_add():
        data = payload()
        reauth(data)
        percent = integer(data, 'discount_percent_bp', 1, 9900)
        with transaction(db()):
            require(not db().execute('SELECT 1 FROM discount_rates WHERE percent_bp=?', (percent,)).fetchone(),
                    'This discount rate already exists.', 409)
            rate_id = db().execute('INSERT INTO discount_rates(percent_bp,created_by_user_id,created_at) VALUES(?,?,?)',
                                   (percent,g.user['user_id'],now())).lastrowid
            event('discount.rate_added', 'discount_rates', rate_id,
                  after={'discount_percent_bp': percent}, approved=g.user['user_id'])
        return jsonify(discount_rate_id=rate_id,discount_percent_bp=percent)

    @app.put('/api/discount/<int:rate_id>')
    @signed_in(True)
    def discount_set_active(rate_id):
        data = payload()
        reauth(data)
        active = data.get('active')
        require(type(active) is bool, 'Choose whether the discount rate is active.')
        with transaction(db()):
            rate = db().execute('SELECT percent_bp,active FROM discount_rates WHERE discount_rate_id=?', (rate_id,)).fetchone()
            require(rate, 'Discount rate not found.', 404)
            require(bool(rate['active']) != active, 'This discount rate is already ' + ('active.' if active else 'disabled.'), 409)
            percent = rate['percent_bp']
            affected = 0
            if not active:
                affected = db().execute("UPDATE purchase_tickets SET discount_percent_bp=0,discount_selected=0,version=version+1,updated_at=? WHERE state='open' AND discount_percent_bp=?",
                                        (now(),percent)).rowcount
            db().execute('UPDATE discount_rates SET active=?,disabled_at=? WHERE discount_rate_id=?',
                         (int(active),None if active else now(),rate_id))
            event('discount.rate_enabled' if active else 'discount.rate_disabled', 'discount_rates', rate_id,
                  before={'discount_percent_bp': percent, 'active': bool(rate['active'])},
                  after={'active': active, 'open_tickets_cleared': affected},
                  approved=g.user['user_id'])
        return jsonify(active=active,open_tickets_cleared=affected)

    def quote(tid):
        t = get_ticket(tid)
        lines = db().execute('''SELECT l.product_id,l.quantity,p.sku,p.description,p.short_description,p.unit,p.active,p.category_id,c.name category_name,
            b.quantity_on_hand,pr.price_id,pr.amount_minor,i.product_image_id FROM ticket_lines l JOIN products p USING(product_id)
            JOIN categories c USING(category_id) JOIN stock_balances b USING(product_id)
            JOIN product_prices pr ON pr.price_id=(SELECT MAX(price_id) FROM product_prices WHERE product_id=p.product_id)
            LEFT JOIN product_images i ON i.product_id=p.product_id AND i.superseded_at IS NULL WHERE l.purchase_ticket_id=? ORDER BY l.product_id''', (tid,)).fetchall()
        rates = [dict(row) for row in db().execute('SELECT discount_rate_id,percent_bp FROM discount_rates WHERE active=1 ORDER BY percent_bp')]
        percent = t['discount_percent_bp'] if t['state'] != 'open' or any(r['percent_bp'] == t['discount_percent_bp'] for r in rates) else 0
        discounts = allocate_discount(lines, percent)
        snapshots = [{**{k:r[k] for k in ('product_id','quantity','sku','description','short_description','unit','active','category_id','category_name','price_id','amount_minor','product_image_id','quantity_on_hand')},
                      'discount_minor': discount, 'line_total_minor': r['quantity'] * r['amount_minor'] - discount}
                     for r, discount in zip(lines, discounts)]
        duplicate=None
        if lines and t['state']=='open':
            cutoff=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(timespec='microseconds')
            signature=[(r['product_id'],r['quantity'],r['amount_minor'],r['discount_minor']) for r in snapshots]
            for candidate in db().execute('SELECT sale_id,receipt_number FROM sales WHERE bazaar_day_id=? AND completed_at>=? ORDER BY sale_id DESC',(t['bazaar_day_id'],cutoff)):
                previous=[tuple(r) for r in db().execute('SELECT product_id,quantity,unit_price_minor,discount_minor FROM sale_lines WHERE sale_id=? ORDER BY product_id',(candidate['sale_id'],))]
                if previous==signature:
                    duplicate=dict(candidate);break
        qhash = digest(json.dumps([tid, t['version'], snapshots, percent, duplicate['sale_id'] if duplicate else None], sort_keys=True))
        sale = db().execute('SELECT sale_id FROM sales WHERE purchase_ticket_id=?', (tid,)).fetchone()
        subtotal = sum(r['quantity'] * r['amount_minor'] for r in lines)
        discount = sum(discounts)
        return {**dict(t), 'lines': snapshots, 'subtotal_minor': subtotal, 'discount_minor': discount,
                'discount_percent_bp': percent, 'discount_rates': rates,
                'total_minor': subtotal - discount, 'quote_hash': qhash,
                'sale_id': sale['sale_id'] if sale else None, 'duplicate_warning': duplicate}

    @app.get('/api/tickets')
    @signed_in()
    def tickets_get():
        return jsonify(tickets=[dict(r) for r in db().execute("SELECT * FROM purchase_tickets WHERE owner_user_id=? AND terminal_id=? AND state='open' ORDER BY purchase_ticket_id DESC", (g.user['user_id'], g.terminal['terminal_id']))])

    @app.post('/api/tickets')
    @signed_in()
    def ticket_create():
        with transaction(db()):
            s = shift()
            # One active ticket per cashier keeps a refresh from spawning a second purchase.
            old = db().execute("SELECT purchase_ticket_id FROM purchase_tickets WHERE owner_user_id=? AND terminal_id=? AND state='open'", (g.user['user_id'],g.terminal['terminal_id'])).fetchone()
            if old:
                return jsonify(quote(old[0]))
            number = 'T-' + secrets.token_hex(5).upper()
            tid = db().execute("INSERT INTO purchase_tickets(bazaar_day_id,ticket_number,owner_user_id,terminal_id,state,created_at,updated_at) VALUES(?,?,?,?,'open',?,?)",
                (s['bazaar_day_id'], number, g.user['user_id'], g.terminal['terminal_id'], now(), now())).lastrowid
            event('ticket.created', 'purchase_tickets', tid, day=s['bazaar_day_id'])
            result = quote(tid)
        return jsonify(result)

    @app.get('/api/tickets/<int:tid>')
    @signed_in()
    def ticket_get(tid):
        return jsonify(quote(tid))

    @app.put('/api/tickets/<int:tid>/discount')
    @signed_in()
    def ticket_discount(tid):
        data = payload()
        percent = integer(data, 'discount_percent_bp', 0, 9900)
        version = integer(data, 'version')
        with transaction(db()):
            shift()
            ticket = get_ticket(tid)
            require(ticket['state'] == 'open' and ticket['version'] == version, 'The ticket changed. Reload it before choosing a discount.', 409)
            require(not percent or db().execute('SELECT 1 FROM discount_rates WHERE percent_bp=? AND active=1', (percent,)).fetchone(),
                    'This discount rate is no longer available. Refresh the order.', 409)
            if ticket['discount_percent_bp'] != percent:
                db().execute('UPDATE purchase_tickets SET discount_percent_bp=?,discount_selected=?,version=version+1,updated_at=? WHERE purchase_ticket_id=?',
                             (percent,int(percent > 0),now(),tid))
                event('ticket.discount_selected', 'purchase_tickets', tid, day=ticket['bazaar_day_id'],
                      before={'discount_percent_bp': ticket['discount_percent_bp']}, after={'discount_percent_bp': percent})
            result = quote(tid)
        return jsonify(result)

    @app.put('/api/tickets/<int:tid>')
    @signed_in()
    def ticket_update(tid):
        data = payload()
        version = integer(data, 'version')
        lines = data.get('lines')
        require(isinstance(lines, list) and len(lines) <= 200, 'Maximum 200 different items per ticket.')
        normalized = [(integer(l, 'product_id', 1), integer(l, 'quantity', 1, 1_000_000)) for l in lines if isinstance(l, dict)]
        require(len(normalized) == len(lines) and len({l[0] for l in normalized}) == len(lines), 'Invalid or duplicate ticket lines.')
        with transaction(db()):
            shift()
            ticket = get_ticket(tid)
            require(ticket['state'] == 'open' and ticket['version'] == version, 'The ticket changed. Reload it before editing.', 409)
            for pid, quantity in normalized:
                require(db().execute('SELECT 1 FROM products WHERE product_id=? AND active=1', (pid,)).fetchone(), 'An item is inactive or missing.', 409)
            db().execute('DELETE FROM ticket_lines WHERE purchase_ticket_id=?', (tid,))
            db().executemany('INSERT INTO ticket_lines(purchase_ticket_id,product_id,quantity) VALUES(?,?,?)', [(tid,*l) for l in normalized])
            db().execute('UPDATE purchase_tickets SET version=version+1,updated_at=? WHERE purchase_ticket_id=?', (now(), tid))
            event('ticket.updated', 'purchase_tickets', tid, day=ticket['bazaar_day_id'], after={'lines': normalized})
            result = quote(tid)
        return jsonify(result)

    @app.post('/api/tickets/<int:tid>/cancel')
    @signed_in()
    def ticket_cancel(tid):
        data = payload()
        reason = text_field(data, 'reason', 300)
        with transaction(db()):
            ticket = get_ticket(tid)
            require(ticket['state'] == 'open', 'Only an open ticket can be cancelled.', 409)
            require(ticket['version'] == integer(data, 'version'), 'The ticket changed. Reload it first.', 409)
            db().execute("UPDATE purchase_tickets SET state='cancelled',version=version+1,updated_at=? WHERE purchase_ticket_id=?", (now(),tid))
            event('ticket.cancelled', 'purchase_tickets', tid, day=ticket['bazaar_day_id'], reason=reason)
        return jsonify(ok=True)

    @app.post('/api/tickets/<int:tid>/transfer')
    @signed_in()
    def ticket_transfer(tid):
        data = payload()
        target = integer(data, 'target_user_id', 1)
        reason = text_field(data, 'reason', 300)
        with transaction(db()):
            ticket = get_ticket(tid)
            require(ticket['state'] == 'open' and ticket['version'] == integer(data,'version'), 'The ticket changed. Reload it first.', 409)
            s = db().execute("SELECT * FROM shifts WHERE cashier_user_id=? AND status='open'", (target,)).fetchone()
            require(s and s['bazaar_day_id'] == ticket['bazaar_day_id'], 'The receiving cashier needs an open shift for this day.', 409)
            require(not db().execute("SELECT 1 FROM purchase_tickets WHERE owner_user_id=? AND state='open'", (target,)).fetchone(), 'The receiving cashier already has an open ticket.', 409)
            db().execute('UPDATE purchase_tickets SET owner_user_id=?,terminal_id=?,version=version+1,updated_at=? WHERE purchase_ticket_id=?', (target,s['terminal_id'],now(),tid))
            event('ticket.transferred', 'purchase_tickets', tid, day=ticket['bazaar_day_id'], before={'owner_user_id': ticket['owner_user_id']}, after={'owner_user_id': target}, reason=reason)
        return jsonify(ok=True)

    @app.post('/api/checkout')
    @signed_in()
    def checkout():
        data = payload()
        tid, tendered, key = integer(data, 'purchase_ticket_id', 1), integer(data, 'tendered_minor', 1), request_key(data)
        qhash = text_field(data,'quote_hash',64)
        version = integer(data,'version')
        fingerprint = digest(json.dumps([tid,tendered,qhash,version,bool(data.get('duplicate_reviewed',False))]))
        with transaction(db()):
            ticket = get_ticket(tid)
            old = db().execute('SELECT * FROM checkout_requests WHERE request_key=?', (key,)).fetchone()
            if old:
                require(old['request_hash'] == fingerprint and old['purchase_ticket_id'] == tid, 'This request key has different contents. Check the existing ticket.', 409)
                return jsonify(sale_id=old['sale_id'], replayed=True)
            sale = db().execute('SELECT sale_id FROM sales WHERE purchase_ticket_id=?', (tid,)).fetchone()
            if sale:
                return jsonify(sale_id=sale['sale_id'], replayed=True)
            s, bazaar = shift(), active_bazaar()
            require(ticket['state'] == 'open' and ticket['bazaar_day_id'] == s['bazaar_day_id'], 'This ticket cannot be checked out.', 409)
            q = quote(tid)
            require(q['version'] == version and secrets.compare_digest(q['quote_hash'],qhash), 'The cart or price changed. Review the new total before taking payment.', 409)
            require(not q['duplicate_warning'] or data.get('duplicate_reviewed') is True,'A matching sale was just saved. Confirm this is a separate customer purchase.',409)
            require(q['lines'], 'Add an item before checkout.')
            require(tendered >= q['total_minor'], 'The amount paid is less than the total.')
            for line in q['lines']:
                require(line['active'] and line['quantity_on_hand'] >= line['quantity'], f'Insufficient stock or inactive item: {line["description"]}.', 409)
            stamp = now()
            # The ticket ID is globally unique, so the receipt cannot collide across days.
            number = f'SQI-{ticket["bazaar_day_id"]:03d}-{tid:06d}'
            sid = db().execute('''INSERT INTO sales(purchase_ticket_id,receipt_number,bazaar_day_id,shift_id,cashier_user_id,terminal_id,subtotal_minor,discount_minor,discount_percent_bp,total_minor,completed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (tid,number,s['bazaar_day_id'],s['shift_id'],g.user['user_id'],g.terminal['terminal_id'],q['subtotal_minor'],q['discount_minor'],q['discount_percent_bp'],q['total_minor'],stamp)).lastrowid
            for l in q['lines']:
                lid = db().execute('''INSERT INTO sale_lines(sale_id,product_id,price_id,product_image_id,sku_snapshot,description_snapshot,short_description_snapshot,category_id_snapshot,category_name_snapshot,
                    unit_snapshot,quantity,unit_price_minor,discount_minor,line_total_minor) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (sid,l['product_id'],l['price_id'],l['product_image_id'],l['sku'],l['description'],l['short_description'],l['category_id'],l['category_name'],l['unit'],l['quantity'],l['amount_minor'],l['discount_minor'],l['line_total_minor'])).lastrowid
                db().execute('INSERT INTO stock_movements(bazaar_id,bazaar_day_id,product_id,quantity_change,sale_line_id,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                    (bazaar['bazaar_id'],s['bazaar_day_id'],l['product_id'],-l['quantity'],lid,g.user['user_id'],stamp))
            db().execute("INSERT INTO payments(sale_id,direction,method,amount_minor,tendered_minor,change_minor,recorded_at) VALUES(?,'in','cash',?,?,?,?)", (sid,q['total_minor'],tendered,tendered-q['total_minor'],stamp))
            db().execute("UPDATE purchase_tickets SET state='completed',version=version+1,updated_at=? WHERE purchase_ticket_id=?", (stamp,tid))
            db().execute("INSERT INTO checkout_requests(request_key,purchase_ticket_id,request_hash,status,sale_id,created_at,finished_at) VALUES(?,?,?,'completed',?,?,?)", (key,tid,fingerprint,sid,stamp,stamp))
            db().execute("INSERT INTO receipt_events(sale_id,event_type,output_format,performed_by_user_id,terminal_id,created_at) VALUES(?,'issued','screen',?,?,?)", (sid,g.user['user_id'],g.terminal['terminal_id'],stamp))
            event('sale.completed', 'sales', sid, day=s['bazaar_day_id'], after={'subtotal_minor': q['subtotal_minor'], 'discount_minor': q['discount_minor'], 'total_minor':q['total_minor'],'receipt_number':number})
            printer = db().execute('SELECT * FROM receipt_printers WHERE terminal_id=? AND enabled=1', (g.terminal['terminal_id'],)).fetchone()
            if printer:
                print_job = db().execute('''INSERT INTO receipt_print_jobs(sale_id,terminal_id,job_kind,printer_name,paper_width_mm,paper_size,requested_by_user_id,created_at)
                    VALUES(?,?,'automatic',?,?,?,?,?)''', (sid,g.terminal['terminal_id'],printer['printer_name'],printer['paper_width_mm'],printer['paper_size'],g.user['user_id'],stamp)).lastrowid
                event('receipt.automatic_queued', 'receipt_print_jobs', print_job, after={'sale_id':sid,'printer_name':printer['printer_name']})
        return jsonify(sale_id=sid, replayed=False)

    def sale_access(sid):
        sale = db().execute('''SELECT s.*,u.display_name,d.day_number,d.business_date,b.bazaar_id event_id,
            b.name bazaar_name,b.currency_code,b.timezone
            FROM sales s JOIN users u ON u.user_id=s.cashier_user_id JOIN bazaar_days d USING(bazaar_day_id) JOIN bazaars b USING(bazaar_id) WHERE s.sale_id=?''', (sid,)).fetchone()
        require(sale, 'Sale not found.', 404)
        require(g.user['role'] in ('manager', 'it_admin') or sale['cashier_user_id'] == g.user['user_id'], 'You can view only your own receipts.', 403)
        return sale

    from .printing import register_printing
    register_printing(app, db, transaction, signed_in, require, payload, integer, text_field, event, sale_access)

    @app.get('/api/sales/<int:sid>')
    @signed_in()
    def sale_get(sid):
        sale = sale_access(sid)
        lines = db().execute('''SELECT l.*,COALESCE((SELECT SUM(c.quantity) FROM correction_lines c WHERE c.sale_line_id=l.sale_line_id),0) returned_quantity
            FROM sale_lines l WHERE l.sale_id=?''', (sid,)).fetchall()
        corrections = db().execute('SELECT * FROM sale_corrections WHERE original_sale_id=? ORDER BY sale_correction_id', (sid,)).fetchall()
        return jsonify(sale=dict(sale), lines=[dict(r) for r in lines], payment=dict(db().execute('SELECT * FROM payments WHERE sale_id=?', (sid,)).fetchone()), corrections=[dict(r) for r in corrections])

    @app.post('/api/sales/<int:sid>/reprint')
    @signed_in()
    def reprint(sid):
        data = payload()
        copy_type = data.get('copy_type', 'customer')
        require(copy_type in ('customer', 'store'), 'Choose Customer Copy or Store Copy.')
        require(copy_type != 'store' or g.user['role'] in ('manager', 'it_admin'), 'Manager access is required for Store Copy.', 403)
        reason = text_field(data, 'reason', 300, optional=True) or copy_type.title() + ' copy'
        with transaction(db()):
            sale = sale_access(sid)
            require(not db().execute("SELECT 1 FROM receipt_print_jobs WHERE sale_id=? AND status IN ('queued','claimed')", (sid,)).fetchone(),
                    'This receipt already has a pending print job. Check the printer and resolve its print record in Settings before making another copy.', 409)
            db().execute("INSERT INTO receipt_events(sale_id,event_type,output_format,performed_by_user_id,terminal_id,reason,created_at) VALUES(?,'reprint','browser',?,?,?,?)", (sid,g.user['user_id'],g.terminal['terminal_id'],reason,now()))
            event('receipt.print_requested', 'sales', sid, day=sale['bazaar_day_id'], reason=reason)
        return jsonify(ok=True)

    @app.post('/api/sales/<int:sid>/corrections')
    @signed_in(True)
    def correction(sid):
        data = payload()
        reauth(data)
        key, reason = request_key(data), text_field(data,'reason',300)
        kind = data.get('correction_type')
        require(kind in ('return','void'), 'Choose return or void.')
        lines = data.get('lines')
        require(isinstance(lines,list) and 1 <= len(lines) <= 200, 'Select items to return.')
        normalized=[]
        for line in lines:
            require(isinstance(line,dict), 'Invalid correction line.')
            normalized.append((integer(line,'sale_line_id',1),integer(line,'quantity',1,1_000_000),integer(line,'restock_quantity',0,1_000_000)))
        require(len({l[0] for l in normalized}) == len(normalized), 'Duplicate correction line.')
        fingerprint=digest(json.dumps([sid,kind,sorted(normalized),reason]))
        with transaction(db()):
            sale=sale_access(sid)
            require(sale['event_id']==active_bazaar()['bazaar_id'],
                    'This receipt belongs to a finished event and cannot be returned or voided in the current event.',409)
            old = db().execute('SELECT * FROM sale_corrections WHERE request_key=?',(key,)).fetchone()
            if old:
                a=db().execute("SELECT after_json FROM audit_events WHERE action='sale.corrected' AND entity_key=?",(str(old['sale_correction_id']),)).fetchone()
                require(a and json.loads(a[0])['request_hash']==fingerprint and old['created_by_user_id']==g.user['user_id'], 'This refund request key has different contents.',409)
                return jsonify(sale_correction_id=old['sale_correction_id'])
            s,bazaar=shift(),active_bazaar()
            remaining={}
            for l in db().execute('SELECT * FROM sale_lines WHERE sale_id=?',(sid,)):
                returned=db().execute('SELECT COALESCE(SUM(quantity),0) FROM correction_lines WHERE sale_line_id=?',(l['sale_line_id'],)).fetchone()[0]
                remaining[l['sale_line_id']]=(l,l['quantity']-returned,returned)
            refund_lines=[]
            for lid,qty,restock in normalized:
                require(lid in remaining and qty<=remaining[lid][1] and restock<=qty, 'Return quantity exceeds the remaining sold quantity.',409)
                l=remaining[lid][0]
                refund_lines.append((lid,qty,restock,refund_for_quantity(l,remaining[lid][2],qty),l['product_id']))
            if kind=='void':
                require(not db().execute('SELECT 1 FROM sale_corrections WHERE original_sale_id=?',(sid,)).fetchone(), 'A partially returned sale cannot be voided.',409)
                require({lid:qty for lid,qty,restock in normalized}=={lid:r[1] for lid,r in remaining.items()}, 'A void must reverse the whole sale.',409)
            total=sum(l[3] for l in refund_lines)
            require(cash_expected(s['shift_id'])>=total,'Refund exceeds expected cash in this drawer. Record an approved cash-in first.',409)
            cid=db().execute('''INSERT INTO sale_corrections(original_sale_id,bazaar_day_id,shift_id,correction_type,reason,request_key,refund_total_minor,created_by_user_id,approved_by_user_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(sid,s['bazaar_day_id'],s['shift_id'],kind,reason,key,total,g.user['user_id'],g.user['user_id'],now())).lastrowid
            for lid,qty,restock,amount,pid in refund_lines:
                clid=db().execute('INSERT INTO correction_lines(sale_correction_id,sale_line_id,quantity,refund_minor,restock_quantity) VALUES(?,?,?,?,?)',(cid,lid,qty,amount,restock)).lastrowid
                if restock:
                    db().execute('INSERT INTO stock_movements(bazaar_id,bazaar_day_id,product_id,quantity_change,correction_line_id,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',(bazaar['bazaar_id'],s['bazaar_day_id'],pid,restock,clid,g.user['user_id'],now()))
            db().execute("INSERT INTO payments(sale_correction_id,direction,method,amount_minor,tendered_minor,change_minor,recorded_at) VALUES(?,'out','cash',?,?,0,?)",(cid,total,total,now()))
            event('sale.corrected','sale_corrections',cid,day=s['bazaar_day_id'],after={'request_hash':fingerprint,'sale_id':sid,'refund_minor':total},reason=reason,approved=g.user['user_id'])
        return jsonify(sale_correction_id=cid,refund_minor=total)

    @app.get('/api/team')
    @signed_in(True)
    def team_get():
        return jsonify(users=[dict(r) for r in db().execute('SELECT user_id,username,display_name,role,active,created_at FROM users ORDER BY user_id')])

    @app.post('/api/users')
    @app.put('/api/users/<int:uid>')
    @signed_in(True)
    def user_save(uid=None):
        data=payload()
        reauth(data)
        name=text_field(data,'display_name',80)
        role=data.get('role')
        require(role in ('cashier','manager','it_admin'),'Invalid account role.')
        require(type(data.get('active',True)) is bool,'Invalid account status.')
        password=data.get('password','')
        require(isinstance(password,str) and (not password or 12<=len(password)<=1024),'Use a password of at least 12 characters.')
        with transaction(db()):
            if uid:
                old=db().execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
                require(old,'Account not found.',404)
                if old['username'].lower() == 'ginflorita':
                    require(uid == g.user['user_id'], 'Only ginflorita can update the IT System Administrator account.', 403)
                    require(role == 'it_admin' and data.get('active',True), 'The IT System Administrator role and active status are locked.', 403)
                else:
                    require(role != 'it_admin', 'Only ginflorita can have the IT System Administrator role.', 403)
                require(uid!=g.user['user_id'] or (role in ('manager','it_admin') and data.get('active',True)), 'You cannot remove your own manager access.')
                if not data.get('active',True):
                    require(not db().execute("SELECT 1 FROM shifts WHERE cashier_user_id=? AND status='open'",(uid,)).fetchone(),'Close this user’s shift before deactivation.',409)
                db().execute('UPDATE users SET display_name=?,role=?,active=?,disabled_at=? WHERE user_id=?',(name,role,int(data.get('active',True)),None if data.get('active',True) else now(),uid))
                if password:
                    db().execute('UPDATE users SET password_hash=? WHERE user_id=?',(generate_password_hash(password,method='scrypt'),uid))
                db().execute('DELETE FROM auth_sessions WHERE user_id=? AND auth_session_id<>?',(uid,g.auth_session))
            else:
                username=text_field(data,'username',50).lower()
                require(bool(re.fullmatch(r'[a-z0-9_.-]{3,50}',username)) and password,'Enter a valid username and a password of at least 12 characters.')
                require(username != 'ginflorita' and role != 'it_admin', 'The IT System Administrator account cannot be created here.', 403)
                uid=db().execute('INSERT INTO users(username,display_name,password_hash,role,active,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',(username,name,generate_password_hash(password,method='scrypt'),role,int(data.get('active',True)),g.user['user_id'],now())).lastrowid
            event('account.saved','users',uid,after={'display_name':name,'role':role,'active':data.get('active',True),'password_changed':bool(password)},approved=g.user['user_id'])
        return jsonify(user_id=uid)

    @app.get('/api/filters')
    @signed_in()
    def filters():
        current=report_bazaar()
        return jsonify(days=[dict(r) for r in db().execute(
                           'SELECT * FROM bazaar_days WHERE bazaar_id=? ORDER BY day_number DESC',
                           (current['bazaar_id'] if current else -1,))],
                       users=[dict(r) for r in db().execute('SELECT user_id,display_name FROM users ORDER BY display_name')],
                       terminals=[dict(r) for r in db().execute('SELECT terminal_id,name FROM terminals ORDER BY terminal_id')])

    def report_filters(sale_alias='s', line_alias='l', day_alias='d', correction=False):
        current=report_bazaar()
        clauses,params=[f'{day_alias}.bazaar_id=?'],[current['bazaar_id'] if current else -1]
        for arg,column in [('day_id',f'{day_alias}.bazaar_day_id'),('user_id',f'{sale_alias}.created_by_user_id' if correction else f'{sale_alias}.cashier_user_id'),
                           ('product_id',f'{line_alias}.product_id'),('category_id',f'{line_alias}.category_id_snapshot')]:
            value=request.args.get(arg)
            if value:
                require(value.isdigit(),'Invalid report filter.')
                clauses.append(column+'=?'); params.append(int(value))
        for arg,op in [('from','>='),('to','<=')]:
            value=request.args.get(arg)
            if value:
                try: parsed=date.fromisoformat(value)
                except ValueError: raise Problem('Invalid report date.')
                require(value==parsed.isoformat(),'Use YYYY-MM-DD for report dates.')
                clauses.append(f'{day_alias}.business_date{op}?'); params.append(value)
        if request.args.get('terminal_id'):
            value=request.args['terminal_id']
            require(value.isdigit(),'Invalid terminal filter.')
            column='sh.terminal_id' if correction else f'{sale_alias}.terminal_id'
            clauses.append(column+'=?'); params.append(int(value))
        if g.user['role'] not in ('manager', 'it_admin'):
            clauses.append((f'{sale_alias}.created_by_user_id' if correction else f'{sale_alias}.cashier_user_id')+'=?'); params.append(g.user['user_id'])
        return (' WHERE '+' AND '.join(clauses) if clauses else ''),params

    @app.get('/api/sales')
    @signed_in()
    def sales_get():
        where,params=report_filters()
        search=request.args.get('q','').strip()[:120]
        if search:
            where+=(' AND ' if where else ' WHERE ')+'''(
                instr(lower(s.receipt_number),lower(?))>0 OR
                instr(lower(replace(s.receipt_number,'BZ-','SQI-')),lower(?))>0 OR
                instr(lower(u.display_name),lower(?))>0 OR
                instr(lower(u.username),lower(?))>0 OR
                instr(lower(l.sku_snapshot),lower(?))>0 OR
                instr(lower(l.description_snapshot),lower(?))>0 OR
                instr(lower(l.short_description_snapshot),lower(?))>0)'''
            params.extend([search]*7)
        page_arg,size_arg=request.args.get('page','1'),request.args.get('page_size','10')
        require(page_arg.isdecimal() and len(page_arg)<=8 and int(page_arg)>0,'Invalid sales page.')
        require(size_arg.isdecimal() and len(size_arg)<=3 and 1<=int(size_arg)<=50,'Invalid sales page size.')
        page,page_size=int(page_arg),int(size_arg)
        source=''' FROM sales s JOIN sale_lines l USING(sale_id) JOIN bazaar_days d USING(bazaar_day_id)
            JOIN users u ON u.user_id=s.cashier_user_id'''+where
        total=db().execute('SELECT COUNT(DISTINCT s.sale_id)'+source,params).fetchone()[0]
        page=min(page,max(1,(total+page_size-1)//page_size))
        rows=db().execute('''SELECT DISTINCT s.*,u.display_name,d.day_number,d.business_date,
            COALESCE((SELECT SUM(refund_total_minor) FROM sale_corrections WHERE original_sale_id=s.sale_id),0) refunded_minor'''
            +source+' ORDER BY s.sale_id DESC LIMIT ? OFFSET ?',params+[page_size,(page-1)*page_size]).fetchall()
        return jsonify(sales=[dict(r) for r in rows],total=total,page=page,page_size=page_size)

    @app.get('/api/reports')
    @signed_in(True)
    def reports():
        where,params=report_filters()
        sales_rows=db().execute('''SELECT s.sale_id,s.cashier_user_id,s.terminal_id,s.completed_at,d.day_number,d.business_date,u.display_name,
            l.* FROM sales s JOIN sale_lines l USING(sale_id) JOIN bazaar_days d USING(bazaar_day_id)
            JOIN users u ON u.user_id=s.cashier_user_id'''+where+' ORDER BY s.sale_id,l.sale_line_id',params).fetchall()
        cw,cp=report_filters('c','l','d',True)
        refunds=db().execute('''SELECT c.*,cl.quantity,cl.refund_minor,l.product_id,l.sku_snapshot,l.description_snapshot,l.category_name_snapshot,
            u.display_name,d.day_number,d.business_date,sh.terminal_id FROM sale_corrections c JOIN correction_lines cl USING(sale_correction_id)
            JOIN sale_lines l USING(sale_line_id) JOIN bazaar_days d ON d.bazaar_day_id=c.bazaar_day_id
            JOIN users u ON u.user_id=c.created_by_user_id JOIN shifts sh ON sh.shift_id=c.shift_id'''+cw+' ORDER BY c.sale_correction_id,cl.correction_line_id',cp).fetchall()
        gross=sum(r['quantity']*r['unit_price_minor'] for r in sales_rows)
        total=sum(r['line_total_minor'] for r in sales_rows)
        refund=sum(r['refund_minor'] for r in refunds)
        groups={k:{} for k in ('items','categories','cashiers','days')}
        def accumulate(group,key,label,amount=0,returned=0,units=0,returned_units=0,business_date=None):
            row=groups[group].setdefault(str(key),{'key':key,'label':label,'sales_minor':0,'refunds_minor':0,'units':0,'returned_units':0})
            row['sales_minor']+=amount;row['refunds_minor']+=returned;row['units']+=units;row['returned_units']+=returned_units
            if business_date:
                daily=row.setdefault('daily',{}).setdefault(business_date,{'sales_minor':0,'refunds_minor':0})
                daily['sales_minor']+=amount;daily['refunds_minor']+=returned
        for r in sales_rows:
            for group,key,label in [('items',r['product_id'],r['description_snapshot']+' · '+r['sku_snapshot']),('categories',r['category_name_snapshot'],r['category_name_snapshot']),('cashiers',r['cashier_user_id'],r['display_name']),('days',r['business_date'],f'Day {r["day_number"]} · {r["business_date"]}')]:
                accumulate(group,key,label,amount=r['line_total_minor'],units=r['quantity'],business_date=r['business_date'])
        for r in refunds:
            for group,key,label in [('items',r['product_id'],r['description_snapshot']+' · '+r['sku_snapshot']),('categories',r['category_name_snapshot'],r['category_name_snapshot']),('cashiers',r['created_by_user_id'],r['display_name']),('days',r['business_date'],f'Day {r["day_number"]} · {r["business_date"]}')]:
                accumulate(group,key,label,returned=r['refund_minor'],returned_units=r['quantity'],business_date=r['business_date'])
        for group in groups:
            groups[group]=sorted(groups[group].values(),key=lambda r:r['sales_minor']-r['refunds_minor'],reverse=True)
        result={'summary':{'transactions':len({r['sale_id'] for r in sales_rows}),'units':sum(r['quantity'] for r in sales_rows),'returned_units':sum(r['quantity'] for r in refunds),'gross_minor':gross,'discount_minor':sum(r['discount_minor'] for r in sales_rows),'tax_minor':sum(r['tax_minor'] for r in sales_rows),'sales_minor':total,'refunds_minor':refund,'net_minor':total-refund},**groups}
        start_arg,end_arg=request.args.get('from'),request.args.get('to')
        require(not (start_arg and end_arg and start_arg>end_arg),'Report start date must be on or before the end date.')
        selected=report_bazaar()
        day_clauses=['bazaar_id=?'];day_params=[selected['bazaar_id'] if selected else -1]
        if request.args.get('day_id'):
            day_clauses.append('bazaar_day_id=?');day_params.append(int(request.args['day_id']))
        if start_arg:
            day_clauses.append('business_date>=?');day_params.append(start_arg)
        if end_arg:
            day_clauses.append('business_date<=?');day_params.append(end_arg)
        business_days=db().execute('SELECT day_number,business_date FROM bazaar_days'+(' WHERE '+' AND '.join(day_clauses) if day_clauses else '')+' ORDER BY business_date',day_params).fetchall()
        result['business_days']=[dict(day) for day in business_days]
        bazaar=selected or db().execute('SELECT bazaar_id,event_name,currency_code,timezone FROM bazaars ORDER BY bazaar_id DESC LIMIT 1').fetchone()
        result['currency_code']=bazaar['currency_code']
        result['event_name']=bazaar['event_name']
        listed_dates=[r['business_date'] for r in business_days]
        listed_dates.extend(r['business_date'] for r in sales_rows)
        listed_dates.extend(r['business_date'] for r in refunds)
        today=datetime.now(ZoneInfo(bazaar['timezone'])).date().isoformat()
        first=min(listed_dates) if listed_dates else today
        last=max(listed_dates) if listed_dates else today
        start=start_arg or min(first,end_arg or first)
        end=end_arg or max(last,start_arg or last)
        filename=f'SQI-POS-Event-{bazaar["bazaar_id"]:03d}-({start}-to-{end})'
        if request.args.get('format')=='xlsx':
            scope=[]
            for key,table,id_column,label_column,prefix in (
                ('day_id','bazaar_days','bazaar_day_id','day_number','Day'),
                ('user_id','users','user_id','display_name','Cashier'),
                ('category_id','categories','category_id','name','Category'),
                ('product_id','products','product_id','sku','Item')):
                if value:=request.args.get(key):
                    record=db().execute(f'SELECT {label_column} FROM {table} WHERE {id_column}=?',(int(value),)).fetchone()
                    scope.append(f'{prefix}: {record[label_column] if record else value}')
            report_file=export_report(result,sales_rows,refunds,business_days,start,end,bazaar['currency_code'],' · '.join(scope) if scope else 'All sales')
            return send_file(report_file,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',as_attachment=True,download_name=filename+'.xlsx')
        if request.args.get('format')=='csv':
            out=io.StringIO(newline='');writer=csv.writer(out)
            writer.writerow(['Group','Description','Units sold','Units returned','Sales (minor units)','Refunds (minor units)','Net (minor units)'])
            for group in groups:
                for r in groups[group]:
                    label=r['label']
                    if label.startswith(('=','+','-','@','\t','\r')): label="'"+label
                    writer.writerow([group,label,r['units'],r['returned_units'],r['sales_minor'],r['refunds_minor'],r['sales_minor']-r['refunds_minor']])
            response=make_response('\ufeff'+out.getvalue());response.mimetype='text/csv';response.headers['Content-Disposition']=f'attachment; filename="{filename}.csv"'
            return response
        return jsonify(result)

    @app.get('/api/audit')
    @signed_in(True)
    def audit_get():
        current=report_bazaar()
        rows=db().execute('''SELECT a.*,u.display_name,t.name terminal_name,subject.display_name subject_display_name FROM audit_events a
            LEFT JOIN users u ON u.user_id=a.actor_user_id LEFT JOIN terminals t USING(terminal_id)
            LEFT JOIN shifts s ON a.entity_type='shifts' AND s.shift_id=CAST(a.entity_key AS INTEGER)
            LEFT JOIN users subject ON subject.user_id=s.cashier_user_id
            WHERE a.bazaar_id=? ORDER BY audit_event_id DESC LIMIT 500''',
            (current['bazaar_id'] if current else -1,)).fetchall()
        return jsonify(events=[dict(r) for r in rows])

    def perform_backup(actor=None):
        if not backup_lock.acquire(blocking=False):
            return {'status':'running','error':'A backup is already running. Wait for it to finish.'}
        connection=None;run_id=None;temp=None
        try:
            connection=connect(app.config['DATABASE'])
            with transaction(connection):
                run_id=connection.execute("INSERT INTO backup_runs(started_at,status) VALUES(?,'running')",(now(),)).lastrowid
            directory=Path(app.config['BACKUP_DIR']);directory.mkdir(parents=True,exist_ok=True)
            target=directory/f'pos-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{run_id}.sqlite3'
            require(target.resolve()!=Path(app.config['DATABASE']).resolve(),'Backup must not overwrite the live database.')
            temp=target.with_suffix('.tmp')
            destination=sqlite3.connect(temp)
            try:
                connection.backup(destination)
                require(destination.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not destination.execute('PRAGMA foreign_key_check').fetchone(),'Backup verification failed.',503)
            finally:
                destination.close()
            temp.replace(target)
            with target.open('rb') as stream:
                checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            with transaction(connection):
                connection.execute("UPDATE backup_runs SET finished_at=?,status='verified',destination=?,file_hash=?,verified_at=? WHERE backup_run_id=?",(now(),str(target),checksum,now(),run_id))
                audit(connection,'backup.verified','backup_runs',run_id,actor=actor,after={'file':target.name,'sha256':checksum})
            return {'status':'verified','filename':target.name,'backup_run_id':run_id}
        except Exception as error:
            if connection and run_id:
                with transaction(connection):
                    connection.execute("UPDATE backup_runs SET status='failed',finished_at=?,error_message=? WHERE backup_run_id=?",(now(),str(error)[:300],run_id))
                    audit(connection,'backup.failed','backup_runs',run_id,actor=actor,reason=str(error)[:300])
            app.logger.error('Backup failed: %s',error)
            return {'status':'failed','error':'Backup failed. Check the backup folder and available storage.'}
        finally:
            if connection: connection.close()
            if temp and temp.exists(): temp.unlink()
            backup_lock.release()

    app.perform_backup=perform_backup

    @app.post('/api/backups')
    @signed_in(True)
    def backup_create():
        reauth(payload())
        result=perform_backup(g.user['user_id'])
        return jsonify(result),200 if result['status']=='verified' else 503

    @app.get('/api/backups')
    @signed_in(True)
    def backup_get():
        return jsonify(backups=[dict(r) for r in db().execute('SELECT * FROM backup_runs ORDER BY backup_run_id DESC LIMIT 50')],directory=app.config['BACKUP_DIR'])

    return app
