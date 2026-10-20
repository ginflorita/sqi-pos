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
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, has_request_context, jsonify, make_response, render_template, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

from .db import audit, connect, digest, initialize, now, transaction as database_transaction


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def require(condition, message, status=400):
    if not condition:
        raise Problem(message, status)


def text_field(data, name, limit=200, optional=False):
    value = data.get(name, '')
    require(isinstance(value, str), f'{name.replace("_", " ")} must be text.')
    value = value.strip()
    require((optional or bool(value)) and len(value) <= limit, f'Enter {name.replace("_", " ")} (maximum {limit} characters).')
    require(not any(ord(c) < 32 for c in value), 'Control characters are not allowed.')
    return value


def integer(data, name, minimum=0, maximum=100_000_000_00):
    value = data.get(name)
    require(type(value) is int and minimum <= value <= maximum, f'Invalid {name.replace("_", " ")}.')
    return value


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
            require(g.terminal['approved'], 'This laptop is waiting for manager approval.', 403)
            require(not manager or g.user['role'] == 'manager', 'Manager access is required.', 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def create_app(database=None, backups=None, secure=False, testing=False):
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
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
            # Recheck access after acquiring the write lock. A user or laptop may
            # have been disabled while this request was waiting for another sale.
            if has_request_context() and connection is getattr(g, 'db', None) and g.user and request.path not in ('/api/login','/api/setup','/api/logout'):
                live=connection.execute('''SELECT u.active,u.role,u.password_hash,t.approved,a.expires_at,a.last_seen_at
                    FROM auth_sessions a JOIN users u USING(user_id) JOIN terminals t USING(terminal_id)
                    WHERE a.auth_session_id=? AND a.user_id=? AND a.terminal_id=?''',
                    (g.auth_session,g.user['user_id'],g.terminal['terminal_id'])).fetchone()
                epoch=int(time.time())
                require(live and live['active'] and live['approved'] and live['role']==g.user['role']
                        and live['expires_at']>epoch and epoch-live['last_seen_at']<1800,
                        'Your account or laptop access changed. Sign in again before continuing.',403)
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
        require(row, 'Create the bazaar on the host laptop first.', 409)
        return row

    def active_day():
        row = db().execute("SELECT * FROM bazaar_days WHERE status='open'").fetchone()
        require(row, 'A manager must open a bazaar day first.', 409)
        return row

    def shift():
        row = db().execute("SELECT * FROM shifts WHERE cashier_user_id=? AND terminal_id=? AND status='open'",
                           (g.user['user_id'], g.terminal['terminal_id'])).fetchone()
        require(row, 'Open a cashier shift on this laptop first.', 409)
        require(row['bazaar_day_id'] == active_day()['bazaar_day_id'], 'This shift does not belong to the open day.', 409)
        return row

    def reauth(data):
        require(g.user and g.user['role'] == 'manager', 'Manager access is required.', 403)
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
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            require(request.headers.get('Origin') in (None, request.host_url.rstrip('/')), 'Request origin rejected.', 403)
            require(bool(csrf) and secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), g.csrf), 'Refresh the page and try again.', 403)
        token = request.cookies.get(session_cookie, '')
        if token:
            row = db().execute('''SELECT a.*,u.username,u.display_name,u.password_hash,u.role,u.active,
                t.name terminal_name,t.approved,t.device_key_hash FROM auth_sessions a JOIN users u USING(user_id)
                JOIN terminals t USING(terminal_id) WHERE a.token_hash=?''', (digest(token),)).fetchone()
            epoch = int(time.time())
            device = request.cookies.get(device_cookie, '')
            if row and row['active'] and row['expires_at'] > epoch and epoch - row['last_seen_at'] < 1800 and secrets.compare_digest(row['device_key_hash'], digest(device)):
                g.user = dict(row)
                g.terminal = {'terminal_id': row['terminal_id'], 'name': row['terminal_name'], 'approved': row['approved']}
                g.auth_session = row['auth_session_id']
                if request.path != '/api/state' and epoch - row['last_seen_at'] >= 30:
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
        return jsonify(error='The image is too large. Maximum upload size is 5 MB.'), 413

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/state')
    def state():
        result = {'setup_required': not bool(db().execute('SELECT 1 FROM users LIMIT 1').fetchone()), 'csrf': g.csrf,
                  'user': None, 'terminal': g.terminal, 'bazaar': None, 'day': None, 'shift': None}
        if g.user:
            result['user'] = {k: g.user[k] for k in ('user_id', 'username', 'display_name', 'role')}
            if g.terminal['approved']:
                bazaar = db().execute("SELECT * FROM bazaars WHERE status='active'").fetchone()
                day = db().execute("SELECT * FROM bazaar_days WHERE status='open'").fetchone()
                s = db().execute("SELECT * FROM shifts WHERE cashier_user_id=? AND terminal_id=? AND status='open'", (g.user['user_id'], g.terminal['terminal_id'])).fetchone()
                result.update(bazaar=dict(bazaar) if bazaar else None, day=dict(day) if day else None, shift=dict(s) if s else None)
                result['backup'] = dict(r) if (r := db().execute('SELECT * FROM backup_runs ORDER BY backup_run_id DESC LIMIT 1').fetchone()) else None
        return jsonify(result)

    def establish(user_id, terminal_name, approve=False):
        device = request.cookies.get(device_cookie) or secrets.token_urlsafe(32)
        row = db().execute('SELECT * FROM terminals WHERE device_key_hash=?', (digest(device),)).fetchone()
        if not row:
            tid = db().execute('INSERT INTO terminals(name,device_key_hash,approved,approved_by_user_id,last_seen_at) VALUES(?,?,?,?,?)',
                               (terminal_name, digest(device), int(approve), user_id if approve else None, now())).lastrowid
            audit(db(), 'terminal.registered', 'terminals', tid, actor=user_id, terminal=tid, after={'approved': approve, 'name': terminal_name})
        else:
            tid = row['terminal_id']
            db().execute('UPDATE terminals SET last_seen_at=? WHERE terminal_id=?',(now(),tid))
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
        name = text_field(data, 'bazaar_name', 120)
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
                               (username, display, generate_password_hash(password, method='scrypt'), 'manager', now())).lastrowid
            bid = db().execute('INSERT INTO bazaars(name,starts_on,timezone,currency_code,status,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                               (name, datetime.now(ZoneInfo(tz)).date().isoformat(), tz, currency, 'active', uid, now())).lastrowid
            audit(db(), 'setup.completed', 'bazaars', bid, actor=uid, after={'name': name, 'currency': currency, 'timezone': tz})
            response = establish(uid, 'Host laptop', True)
        return response

    @app.post('/api/login')
    def login():
        data = payload()
        username = text_field(data, 'username', 50).lower()
        password = data.get('password', '')
        require(isinstance(password, str) and len(password) <= 1024, 'Invalid sign-in details.')
        terminal_name = text_field(data, 'terminal_name', 80)
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
                response = establish(user['user_id'], terminal_name)
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
            i.product_image_id FROM products p JOIN categories c USING(category_id) JOIN stock_balances b USING(product_id)
            LEFT JOIN product_prices pr ON pr.price_id=(SELECT MAX(price_id) FROM product_prices WHERE product_id=p.product_id)
            LEFT JOIN product_images i ON i.product_id=p.product_id AND i.superseded_at IS NULL ORDER BY p.description''').fetchall()
        return jsonify(products=[dict(r) for r in products], categories=[dict(r) for r in db().execute('SELECT * FROM categories ORDER BY name')])

    @app.post('/api/categories')
    @signed_in(True)
    def category_create():
        data = payload()
        name = text_field(data, 'name', 80)
        with transaction(db()):
            cid = db().execute('INSERT INTO categories(name) VALUES(?)', (name,)).lastrowid
            event('category.created', 'categories', cid, after={'name': name})
        return jsonify(category_id=cid)

    @app.post('/api/products')
    @app.put('/api/products/<int:product_id>')
    @signed_in(True)
    def product_save(product_id=None):
        data = payload()
        reauth(data)
        fields = [text_field(data, 'sku', 60), text_field(data, 'barcode', 80, True) or None,
                  text_field(data, 'description', 200), integer(data, 'category_id', 1), text_field(data, 'unit', 20)]
        require(type(data.get('active', True)) is bool, 'Invalid product status.')
        amount, reason = integer(data, 'amount_minor', 1), text_field(data, 'reason', 300)
        with transaction(db()):
            require(db().execute('SELECT 1 FROM categories WHERE category_id=? AND active=1', (fields[3],)).fetchone(), 'Choose an active category.')
            before = None
            if product_id:
                old = db().execute('SELECT * FROM products WHERE product_id=?', (product_id,)).fetchone()
                require(old, 'Product not found.', 404)
                before = dict(old)
                db().execute('UPDATE products SET sku=?,barcode=?,description=?,category_id=?,unit=?,active=? WHERE product_id=?', (*fields, int(data.get('active', True)), product_id))
            else:
                product_id = db().execute('INSERT INTO products(sku,barcode,description,category_id,unit,active) VALUES(?,?,?,?,?,?)', (*fields, int(data.get('active', True)))).lastrowid
            current = db().execute('SELECT amount_minor FROM product_prices WHERE product_id=? ORDER BY price_id DESC LIMIT 1', (product_id,)).fetchone()
            if not current or current[0] != amount:
                db().execute('INSERT INTO product_prices(product_id,amount_minor,effective_at,changed_by_user_id,reason) VALUES(?,?,?,?,?)',
                             (product_id, amount, now(), g.user['user_id'], reason))
            event('product.updated' if before else 'product.created', 'products', product_id, before=before,
                  after={**dict(zip(('sku','barcode','description','category_id','unit'), fields)), 'active': data.get('active', True), 'amount_minor': amount},
                  reason=reason, approved=g.user['user_id'])
        return jsonify(product_id=product_id)

    @app.post('/api/products/<int:product_id>/image')
    @signed_in(True)
    def image_upload(product_id):
        reauth(request.form)
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
            require(not db().execute("SELECT 1 FROM shifts WHERE status='open'").fetchone(), 'Close all cashier shifts first.', 409)
            require(not db().execute("SELECT 1 FROM purchase_tickets WHERE state='open'").fetchone(), 'Complete or cancel all open tickets first.', 409)
            db().execute("UPDATE bazaar_days SET status='closed',closed_at=?,closed_by_user_id=? WHERE bazaar_day_id=?", (now(), g.user['user_id'], day['bazaar_day_id']))
            event('day.closed', 'bazaar_days', day['bazaar_day_id'], day=day['bazaar_day_id'], approved=g.user['user_id'])
        backup = perform_backup(g.user['user_id'])
        return jsonify(ok=True, backup=backup)

    def cash_expected(sid):
        opening = db().execute('SELECT opening_cash_minor FROM shifts WHERE shift_id=?', (sid,)).fetchone()[0]
        incoming = db().execute('SELECT COALESCE(SUM(p.amount_minor),0) FROM payments p JOIN sales s USING(sale_id) WHERE s.shift_id=?', (sid,)).fetchone()[0]
        outgoing = db().execute('SELECT COALESCE(SUM(p.amount_minor),0) FROM payments p JOIN sale_corrections c USING(sale_correction_id) WHERE c.shift_id=?', (sid,)).fetchone()[0]
        other = db().execute("SELECT COALESCE(SUM(CASE direction WHEN 'in' THEN amount_minor ELSE -amount_minor END),0) FROM cash_movements WHERE shift_id=?", (sid,)).fetchone()[0]
        return opening + incoming - outgoing + other

    @app.get('/api/shifts')
    @signed_in()
    def shifts_get():
        clause, params = ('', ()) if g.user['role'] == 'manager' else (' WHERE s.cashier_user_id=?', (g.user['user_id'],))
        rows = db().execute('SELECT s.*,u.display_name,t.name terminal_name,d.day_number FROM shifts s JOIN users u ON u.user_id=s.cashier_user_id JOIN terminals t USING(terminal_id) JOIN bazaar_days d USING(bazaar_day_id)' + clause + ' ORDER BY s.shift_id DESC LIMIT 200', params).fetchall()
        result=[]
        for row in rows:
            ticket=db().execute("SELECT purchase_ticket_id,ticket_number,version FROM purchase_tickets WHERE owner_user_id=? AND state='open'",(row['cashier_user_id'],)).fetchone() if row['status']=='open' else None
            order=None
            if ticket:
                order={**dict(ticket),'lines':[dict(l) for l in db().execute('SELECT p.description,l.quantity FROM ticket_lines l JOIN products p USING(product_id) WHERE purchase_ticket_id=?',(ticket['purchase_ticket_id'],))]}
            result.append({**dict(row),'live_expected_minor':cash_expected(row['shift_id']),'open_ticket':order})
        return jsonify(shifts=result)

    @app.post('/api/shifts/open')
    @signed_in()
    def shift_open():
        data = payload()
        opening = integer(data, 'opening_cash_minor')
        with transaction(db()):
            day = active_day()
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
        key, reason = request_key(data), text_field(data, 'reason', 300)
        kind, lines = data.get('document_type'), data.get('lines')
        reference = text_field(data, 'reference_no', 80, True)
        require(kind in ('opening','in','out','count','adjustment'), 'Invalid stock document type.')
        require(isinstance(lines, list) and 1 <= len(lines) <= 200, 'Enter 1–200 stock lines.')
        normalized = []
        for line in lines:
            require(isinstance(line, dict), 'Invalid stock line.')
            pid = integer(line, 'product_id', 1)
            quantity = integer(line, 'quantity', -1_000_000 if kind == 'adjustment' else 0, 1_000_000)
            require(kind == 'count' or quantity != 0, 'Enter a nonzero quantity.')
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
            require(kind == 'opening' or day, 'Open a bazaar day before posting stock movements.', 409)
            did = day['bazaar_day_id'] if day else None
            sid = db().execute("INSERT INTO stock_documents(bazaar_id,bazaar_day_id,document_type,reference_no,reason,request_key,status,created_by_user_id,approved_by_user_id,created_at,approved_at) VALUES(?,?,?,?,?,?,'posted',?,?,?,?)",
                (bazaar['bazaar_id'], did, kind, reference, reason, key, g.user['user_id'], g.user['user_id'], now(), now())).lastrowid
            for line in normalized:
                balance = db().execute('SELECT * FROM stock_balances WHERE product_id=?', (line['product_id'],)).fetchone()
                require(balance, 'Stock item not found.', 404)
                if kind == 'opening':
                    require(not db().execute('SELECT 1 FROM stock_movements WHERE product_id=? LIMIT 1', (line['product_id'],)).fetchone(), 'Opening stock is only allowed before an item has any movements.', 409)
                change = line['quantity']-balance['quantity_on_hand'] if kind == 'count' else (-line['quantity'] if kind == 'out' else line['quantity'])
                require(balance['quantity_on_hand']+change >= 0, 'Stock cannot become negative.', 409)
                lid = db().execute('INSERT INTO stock_document_lines(stock_document_id,product_id,quantity_change,expected_quantity,counted_quantity) VALUES(?,?,?,?,?)',
                    (sid, line['product_id'], change, balance['quantity_on_hand'] if kind == 'count' else None, line['quantity'] if kind == 'count' else None)).lastrowid
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
            LEFT JOIN stock_documents sd USING(stock_document_id) ORDER BY m.stock_movement_id DESC LIMIT 500''').fetchall()
        return jsonify(movements=[dict(r) for r in rows])

    def get_ticket(tid, enforce_owner=True):
        ticket = db().execute('SELECT * FROM purchase_tickets WHERE purchase_ticket_id=?', (tid,)).fetchone()
        require(ticket, 'Ticket not found.', 404)
        if enforce_owner:
            require(ticket['owner_user_id'] == g.user['user_id'] and ticket['terminal_id'] == g.terminal['terminal_id'], 'This ticket belongs to another cashier or laptop.', 403)
        return ticket

    def quote(tid):
        t = get_ticket(tid)
        lines = db().execute('''SELECT l.product_id,l.quantity,p.sku,p.description,p.unit,p.active,p.category_id,c.name category_name,
            b.quantity_on_hand,pr.price_id,pr.amount_minor,i.product_image_id FROM ticket_lines l JOIN products p USING(product_id)
            JOIN categories c USING(category_id) JOIN stock_balances b USING(product_id)
            JOIN product_prices pr ON pr.price_id=(SELECT MAX(price_id) FROM product_prices WHERE product_id=p.product_id)
            LEFT JOIN product_images i ON i.product_id=p.product_id AND i.superseded_at IS NULL WHERE l.purchase_ticket_id=? ORDER BY l.product_id''', (tid,)).fetchall()
        snapshots = [{k:r[k] for k in ('product_id','quantity','sku','description','unit','active','category_id','category_name','price_id','amount_minor','product_image_id')} for r in lines]
        duplicate=None
        if lines and t['state']=='open':
            cutoff=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(timespec='microseconds')
            signature=[(r['product_id'],r['quantity'],r['amount_minor']) for r in lines]
            for candidate in db().execute('SELECT sale_id,receipt_number FROM sales WHERE bazaar_day_id=? AND completed_at>=? ORDER BY sale_id DESC',(t['bazaar_day_id'],cutoff)):
                previous=[tuple(r) for r in db().execute('SELECT product_id,quantity,unit_price_minor FROM sale_lines WHERE sale_id=? ORDER BY product_id',(candidate['sale_id'],))]
                if previous==signature:
                    duplicate=dict(candidate);break
        qhash = digest(json.dumps([tid, t['version'], snapshots, duplicate['sale_id'] if duplicate else None], sort_keys=True))
        sale = db().execute('SELECT sale_id FROM sales WHERE purchase_ticket_id=?', (tid,)).fetchone()
        return {**dict(t), 'lines': [dict(r) for r in lines], 'total_minor': sum(r['quantity']*r['amount_minor'] for r in lines),
                'quote_hash': qhash, 'sale_id': sale['sale_id'] if sale else None, 'duplicate_warning':duplicate}

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
            number = f'BZ-{ticket["bazaar_day_id"]:03d}-{tid:06d}'
            sid = db().execute('''INSERT INTO sales(purchase_ticket_id,receipt_number,bazaar_day_id,shift_id,cashier_user_id,terminal_id,subtotal_minor,total_minor,completed_at)
                VALUES(?,?,?,?,?,?,?,?,?)''', (tid,number,s['bazaar_day_id'],s['shift_id'],g.user['user_id'],g.terminal['terminal_id'],q['total_minor'],q['total_minor'],stamp)).lastrowid
            for l in q['lines']:
                lid = db().execute('''INSERT INTO sale_lines(sale_id,product_id,price_id,product_image_id,sku_snapshot,description_snapshot,category_id_snapshot,category_name_snapshot,
                    unit_snapshot,quantity,unit_price_minor,line_total_minor) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (sid,l['product_id'],l['price_id'],l['product_image_id'],l['sku'],l['description'],l['category_id'],l['category_name'],l['unit'],l['quantity'],l['amount_minor'],l['quantity']*l['amount_minor'])).lastrowid
                db().execute('INSERT INTO stock_movements(bazaar_id,bazaar_day_id,product_id,quantity_change,sale_line_id,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                    (bazaar['bazaar_id'],s['bazaar_day_id'],l['product_id'],-l['quantity'],lid,g.user['user_id'],stamp))
            db().execute("INSERT INTO payments(sale_id,direction,method,amount_minor,tendered_minor,change_minor,recorded_at) VALUES(?,'in','cash',?,?,?,?)", (sid,q['total_minor'],tendered,tendered-q['total_minor'],stamp))
            db().execute("UPDATE purchase_tickets SET state='completed',version=version+1,updated_at=? WHERE purchase_ticket_id=?", (stamp,tid))
            db().execute("INSERT INTO checkout_requests(request_key,purchase_ticket_id,request_hash,status,sale_id,created_at,finished_at) VALUES(?,?,?,'completed',?,?,?)", (key,tid,fingerprint,sid,stamp,stamp))
            db().execute("INSERT INTO receipt_events(sale_id,event_type,output_format,performed_by_user_id,terminal_id,created_at) VALUES(?,'issued','screen',?,?,?)", (sid,g.user['user_id'],g.terminal['terminal_id'],stamp))
            event('sale.completed', 'sales', sid, day=s['bazaar_day_id'], after={'total_minor':q['total_minor'],'receipt_number':number})
        return jsonify(sale_id=sid, replayed=False)

    def sale_access(sid):
        sale = db().execute('''SELECT s.*,u.display_name,d.day_number,d.business_date,b.name bazaar_name,b.currency_code,b.timezone
            FROM sales s JOIN users u ON u.user_id=s.cashier_user_id JOIN bazaar_days d USING(bazaar_day_id) JOIN bazaars b USING(bazaar_id) WHERE s.sale_id=?''', (sid,)).fetchone()
        require(sale, 'Sale not found.', 404)
        require(g.user['role'] == 'manager' or sale['cashier_user_id'] == g.user['user_id'], 'You can view only your own receipts.', 403)
        return sale

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
        reason = text_field(data, 'reason', 300)
        with transaction(db()):
            sale = sale_access(sid)
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
            sale_access(sid)
            old = db().execute('SELECT * FROM sale_corrections WHERE request_key=?',(key,)).fetchone()
            if old:
                a=db().execute("SELECT after_json FROM audit_events WHERE action='sale.corrected' AND entity_key=?",(str(old['sale_correction_id']),)).fetchone()
                require(a and json.loads(a[0])['request_hash']==fingerprint and old['created_by_user_id']==g.user['user_id'], 'This refund request key has different contents.',409)
                return jsonify(sale_correction_id=old['sale_correction_id'])
            s,bazaar=shift(),active_bazaar()
            remaining={}
            for l in db().execute('SELECT * FROM sale_lines WHERE sale_id=?',(sid,)):
                returned=db().execute('SELECT COALESCE(SUM(quantity),0) FROM correction_lines WHERE sale_line_id=?',(l['sale_line_id'],)).fetchone()[0]
                remaining[l['sale_line_id']]=(l,l['quantity']-returned)
            refund_lines=[]
            for lid,qty,restock in normalized:
                require(lid in remaining and qty<=remaining[lid][1] and restock<=qty, 'Return quantity exceeds the remaining sold quantity.',409)
                l=remaining[lid][0]
                refund_lines.append((lid,qty,restock,qty*l['unit_price_minor'],l['product_id']))
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
        return jsonify(users=[dict(r) for r in db().execute('SELECT user_id,username,display_name,role,active,created_at FROM users ORDER BY user_id')],
                       terminals=[dict(r) for r in db().execute('SELECT terminal_id,name,approved,last_seen_at FROM terminals ORDER BY terminal_id')])

    @app.post('/api/users')
    @app.put('/api/users/<int:uid>')
    @signed_in(True)
    def user_save(uid=None):
        data=payload()
        reauth(data)
        name=text_field(data,'display_name',80)
        role=data.get('role')
        require(role in ('cashier','manager'),'Invalid account role.')
        require(type(data.get('active',True)) is bool,'Invalid account status.')
        password=data.get('password','')
        require(isinstance(password,str) and (not password or 12<=len(password)<=1024),'Use a password of at least 12 characters.')
        with transaction(db()):
            if uid:
                old=db().execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
                require(old,'Account not found.',404)
                require(uid!=g.user['user_id'] or (role=='manager' and data.get('active',True)), 'You cannot remove your own manager access.')
                if not data.get('active',True):
                    require(not db().execute("SELECT 1 FROM shifts WHERE cashier_user_id=? AND status='open'",(uid,)).fetchone(),'Close this user’s shift before deactivation.',409)
                db().execute('UPDATE users SET display_name=?,role=?,active=?,disabled_at=? WHERE user_id=?',(name,role,int(data.get('active',True)),None if data.get('active',True) else now(),uid))
                if password:
                    db().execute('UPDATE users SET password_hash=? WHERE user_id=?',(generate_password_hash(password,method='scrypt'),uid))
                db().execute('DELETE FROM auth_sessions WHERE user_id=? AND auth_session_id<>?',(uid,g.auth_session))
            else:
                username=text_field(data,'username',50).lower()
                require(bool(re.fullmatch(r'[a-z0-9_.-]{3,50}',username)) and password,'Enter a valid username and a password of at least 12 characters.')
                uid=db().execute('INSERT INTO users(username,display_name,password_hash,role,active,created_by_user_id,created_at) VALUES(?,?,?,?,?,?,?)',(username,name,generate_password_hash(password,method='scrypt'),role,int(data.get('active',True)),g.user['user_id'],now())).lastrowid
            event('account.saved','users',uid,after={'display_name':name,'role':role,'active':data.get('active',True),'password_changed':bool(password)},approved=g.user['user_id'])
        return jsonify(user_id=uid)

    @app.put('/api/terminals/<int:tid>')
    @signed_in(True)
    def terminal_save(tid):
        data=payload()
        reauth(data)
        require(type(data.get('approved')) is bool,'Invalid terminal approval.')
        name=text_field(data,'name',80)
        with transaction(db()):
            require(db().execute('SELECT 1 FROM terminals WHERE terminal_id=?',(tid,)).fetchone(),'Terminal not found.',404)
            require(tid!=g.terminal['terminal_id'] or data['approved'],'You cannot revoke the laptop you are using.')
            if not data['approved']:
                require(not db().execute("SELECT 1 FROM shifts WHERE terminal_id=? AND status='open'",(tid,)).fetchone(),'Close this laptop’s shift before revoking it.',409)
            db().execute('UPDATE terminals SET name=?,approved=?,approved_by_user_id=? WHERE terminal_id=?',(name,int(data['approved']),g.user['user_id'],tid))
            event('terminal.approval_changed','terminals',tid,after={'name':name,'approved':data['approved']},approved=g.user['user_id'])
        return jsonify(ok=True)

    @app.get('/api/filters')
    @signed_in()
    def filters():
        return jsonify(days=[dict(r) for r in db().execute('SELECT * FROM bazaar_days ORDER BY day_number DESC')],
                       users=[dict(r) for r in db().execute('SELECT user_id,display_name FROM users ORDER BY display_name')],
                       terminals=[dict(r) for r in db().execute('SELECT terminal_id,name FROM terminals ORDER BY terminal_id')])

    def report_filters(sale_alias='s', line_alias='l', day_alias='d', correction=False):
        clauses,params=[],[]
        for arg,column in [('day_id',f'{day_alias}.bazaar_day_id'),('user_id',f'{sale_alias}.created_by_user_id' if correction else f'{sale_alias}.cashier_user_id'),
                           ('product_id',f'{line_alias}.product_id'),('category_id',f'{line_alias}.category_id_snapshot')]:
            value=request.args.get(arg)
            if value:
                require(value.isdigit(),'Invalid report filter.')
                clauses.append(column+'=?'); params.append(int(value))
        for arg,op in [('from','>='),('to','<=')]:
            value=request.args.get(arg)
            if value:
                try: date.fromisoformat(value)
                except ValueError: raise Problem('Invalid report date.')
                clauses.append(f'{day_alias}.business_date{op}?'); params.append(value)
        if request.args.get('terminal_id'):
            value=request.args['terminal_id']
            require(value.isdigit(),'Invalid terminal filter.')
            column='sh.terminal_id' if correction else f'{sale_alias}.terminal_id'
            clauses.append(column+'=?'); params.append(int(value))
        if g.user['role']!='manager':
            clauses.append((f'{sale_alias}.created_by_user_id' if correction else f'{sale_alias}.cashier_user_id')+'=?'); params.append(g.user['user_id'])
        return (' WHERE '+' AND '.join(clauses) if clauses else ''),params

    @app.get('/api/sales')
    @signed_in()
    def sales_get():
        where,params=report_filters()
        rows=db().execute('''SELECT DISTINCT s.*,u.display_name,d.day_number,d.business_date,
            COALESCE((SELECT SUM(refund_total_minor) FROM sale_corrections WHERE original_sale_id=s.sale_id),0) refunded_minor
            FROM sales s JOIN sale_lines l USING(sale_id) JOIN bazaar_days d USING(bazaar_day_id)
            JOIN users u ON u.user_id=s.cashier_user_id'''+where+' ORDER BY s.sale_id DESC LIMIT 500',params).fetchall()
        return jsonify(sales=[dict(r) for r in rows])

    @app.get('/api/reports')
    @signed_in(True)
    def reports():
        where,params=report_filters()
        sales_rows=db().execute('''SELECT s.sale_id,s.cashier_user_id,s.terminal_id,s.completed_at,d.day_number,d.business_date,u.display_name,
            l.* FROM sales s JOIN sale_lines l USING(sale_id) JOIN bazaar_days d USING(bazaar_day_id)
            JOIN users u ON u.user_id=s.cashier_user_id'''+where,params).fetchall()
        cw,cp=report_filters('c','l','d',True)
        refunds=db().execute('''SELECT c.*,cl.quantity,cl.refund_minor,l.product_id,l.sku_snapshot,l.description_snapshot,l.category_name_snapshot,
            u.display_name,d.day_number,d.business_date,sh.terminal_id FROM sale_corrections c JOIN correction_lines cl USING(sale_correction_id)
            JOIN sale_lines l USING(sale_line_id) JOIN bazaar_days d ON d.bazaar_day_id=c.bazaar_day_id
            JOIN users u ON u.user_id=c.created_by_user_id JOIN shifts sh ON sh.shift_id=c.shift_id'''+cw,cp).fetchall()
        gross=sum(r['quantity']*r['unit_price_minor'] for r in sales_rows)
        total=sum(r['line_total_minor'] for r in sales_rows)
        refund=sum(r['refund_minor'] for r in refunds)
        groups={k:{} for k in ('items','categories','cashiers','days')}
        def accumulate(group,key,label,amount=0,returned=0,units=0,returned_units=0):
            row=groups[group].setdefault(str(key),{'key':key,'label':label,'sales_minor':0,'refunds_minor':0,'units':0,'returned_units':0})
            row['sales_minor']+=amount;row['refunds_minor']+=returned;row['units']+=units;row['returned_units']+=returned_units
        for r in sales_rows:
            for group,key,label in [('items',r['product_id'],r['description_snapshot']+' · '+r['sku_snapshot']),('categories',r['category_name_snapshot'],r['category_name_snapshot']),('cashiers',r['cashier_user_id'],r['display_name']),('days',r['business_date'],f'Day {r["day_number"]} · {r["business_date"]}')]:
                accumulate(group,key,label,amount=r['line_total_minor'],units=r['quantity'])
        for r in refunds:
            for group,key,label in [('items',r['product_id'],r['description_snapshot']+' · '+r['sku_snapshot']),('categories',r['category_name_snapshot'],r['category_name_snapshot']),('cashiers',r['created_by_user_id'],r['display_name']),('days',r['business_date'],f'Day {r["day_number"]} · {r["business_date"]}')]:
                accumulate(group,key,label,returned=r['refund_minor'],returned_units=r['quantity'])
        for group in groups:
            groups[group]=sorted(groups[group].values(),key=lambda r:r['sales_minor']-r['refunds_minor'],reverse=True)
        result={'summary':{'transactions':len({r['sale_id'] for r in sales_rows}),'units':sum(r['quantity'] for r in sales_rows),'returned_units':sum(r['quantity'] for r in refunds),'gross_minor':gross,'discount_minor':sum(r['discount_minor'] for r in sales_rows),'tax_minor':sum(r['tax_minor'] for r in sales_rows),'sales_minor':total,'refunds_minor':refund,'net_minor':total-refund},**groups}
        if request.args.get('format')=='csv':
            out=io.StringIO(newline='');writer=csv.writer(out)
            writer.writerow(['Group','Description','Units sold','Units returned','Sales (minor units)','Refunds (minor units)','Net (minor units)'])
            for group in groups:
                for r in groups[group]:
                    label=r['label']
                    if label.startswith(('=','+','-','@','\t','\r')): label="'"+label
                    writer.writerow([group,label,r['units'],r['returned_units'],r['sales_minor'],r['refunds_minor'],r['sales_minor']-r['refunds_minor']])
            response=make_response('\ufeff'+out.getvalue());response.mimetype='text/csv';response.headers['Content-Disposition']='attachment; filename=bazaar-report.csv'
            return response
        return jsonify(result)

    @app.get('/api/audit')
    @signed_in(True)
    def audit_get():
        rows=db().execute('''SELECT a.*,u.display_name,t.name terminal_name FROM audit_events a
            LEFT JOIN users u ON u.user_id=a.actor_user_id LEFT JOIN terminals t USING(terminal_id)
            ORDER BY audit_event_id DESC LIMIT 500''').fetchall()
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
