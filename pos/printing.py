"""Per-terminal printing. Helpers pull jobs; no browser-to-localhost exception needed."""
import base64
import io
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from flask import g, jsonify, request
from .db import digest, now, transaction as raw_transaction


def receipt_image(db, sale_id, width_mm):
    sale = db.execute('''SELECT s.*,u.display_name,d.business_date FROM sales s
        JOIN users u ON u.user_id=s.cashier_user_id JOIN bazaar_days d USING(bazaar_day_id)
        WHERE sale_id=?''', (sale_id,)).fetchone()
    payment = db.execute("SELECT * FROM payments WHERE sale_id=? AND direction='in'", (sale_id,)).fetchone()
    lines = db.execute('SELECT * FROM sale_lines WHERE sale_id=? ORDER BY sale_line_id', (sale_id,)).fetchall()
    width = 384 if width_mm == 58 else 576
    font = None
    font_path = None
    for path in ('C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(path).exists():
            font_path = path
            font = ImageFont.truetype(path, 20 if width_mm == 58 else 23)
            break
    font = font or ImageFont.load_default(size=20)
    rows = []
    def add(text):
        # Pixel-based wrapping preserves arbitrary descriptions without clipping.
        line = ''
        for char in str(text):
            if font.getlength(line + char) > width - 28:
                rows.append(line)
                line = ''
            line += char
        rows.append(line)
    def amount(n):
        return f'PHP {n / 100:,.2f}'
    add("SQI Group Int'l. Corp - Philippines")
    add('ACKNOWLEDGEMENT RECEIPT')
    add(sale['receipt_number'].replace('BZ-', 'SQI-', 1))
    add('Date: ' + sale['business_date'])
    add('Cashier: ' + sale['display_name'])
    add('-' * (27 if width_mm == 58 else 39))
    for line in lines:
        add(line['sku_snapshot'] + ' ' + line['description_snapshot'])
        add(f"{line['quantity']} x {amount(line['unit_price_minor'])} = {amount(line['line_total_minor'])}")
    add('-' * (27 if width_mm == 58 else 39))
    add('TOTAL: ' + amount(sale['total_minor']))
    add('Cash paid: ' + amount(payment['tendered_minor']))
    add('Change: ' + amount(payment['change_minor']))
    add('Thank you for your purchase.')
    add('Head office: 18 Pineapple Rd, Malabon, 1475 Metro Manila, Philippines')
    logo = Image.open(Path(__file__).resolve().parent.parent / 'static/sqi-logo.png').convert('RGBA')
    logo.thumbnail((180, 100))
    step = 30
    image = Image.new('RGB', (width, 125 + step * len(rows) + 100), 'white')
    image.paste(logo, ((width - logo.width) // 2, 8), logo)
    draw = ImageDraw.Draw(image)
    for i, row in enumerate(rows):
        draw.text((14, 120 + i * step), row, font=font, fill='black')
    footer_font = ImageFont.truetype(font_path, 12 if width_mm == 58 else 17) if font_path else font
    footer_y = 125 + step * len(rows)
    for offset, pair in enumerate((('Tel: 8-364-7561','Website: https://sqigroup.ph'),
                                   ('Office Hours: 9:00 AM – 6:00 PM','Monday – Saturday'))):
        for column, text in enumerate(pair):
            draw.text((14 + column * (width // 2), footer_y + offset * 28), text, font=footer_font, fill='black')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def register_printing(app, db, transaction, signed_in, require, payload, integer, text_field, event, sale_access):
    def public_setting(row):
        if not row:
            return None
        result = dict(row)
        result.pop('token_hash', None)
        result['available_printers'] = json.loads(result.pop('available_printers_json'))
        result['online'] = bool(row['last_seen_at'] and (datetime.now(timezone.utc) - datetime.fromisoformat(row['last_seen_at'])).total_seconds() < 30)
        return result

    def helper():
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        require(40 <= len(token) <= 100, 'Printer helper authentication required.', 403)
        row = db().execute('''SELECT p.* FROM receipt_printers p JOIN terminals t USING(terminal_id)
            WHERE token_hash=? AND t.approved=1''', (digest(token),)).fetchone()
        require(row, 'Printer pairing was revoked or the laptop is not approved.', 403)
        return row

    @app.get('/api/receipt-printer')
    @signed_in()
    def settings_get():
        row = db().execute('SELECT * FROM receipt_printers WHERE terminal_id=?', (g.terminal['terminal_id'],)).fetchone()
        sid = request.args.get('sale_id', type=int)
        if sid is not None:
            sale_access(sid)
        jobs = db().execute('''SELECT j.*,s.receipt_number FROM receipt_print_jobs j JOIN sales s USING(sale_id)
            WHERE j.terminal_id=? AND (? IS NULL OR j.sale_id=?) ORDER BY receipt_print_job_id DESC LIMIT 15''', (g.terminal['terminal_id'],sid,sid)).fetchall()
        return jsonify(printer=public_setting(row), jobs=[dict(j) for j in jobs])

    @app.post('/api/receipt-printer/pair')
    @signed_in(True)
    def pair():
        token = secrets.token_urlsafe(32)
        with transaction(db()):
            existing = db().execute('SELECT 1 FROM receipt_print_jobs WHERE terminal_id=? AND status IN (\'queued\',\'claimed\')', (g.terminal['terminal_id'],)).fetchone()
            require(not existing, 'Resolve pending print jobs before replacing this pairing.', 409)
            db().execute('''INSERT INTO receipt_printers(terminal_id,token_hash,configured_by_user_id,updated_at)
                VALUES(?,?,?,?) ON CONFLICT(terminal_id) DO UPDATE SET token_hash=excluded.token_hash,
                enabled=0,printer_name='',last_seen_at=NULL,available_printers_json='[]',
                configured_by_user_id=excluded.configured_by_user_id,updated_at=excluded.updated_at''',
                (g.terminal['terminal_id'],digest(token),g.user['user_id'],now()))
            event('printer.paired', 'terminals', g.terminal['terminal_id'])
        return jsonify(pairing_token=token)

    @app.put('/api/receipt-printer')
    @signed_in(True)
    def settings_put():
        data = payload()
        name = text_field(data, 'printer_name', 200, optional=True)
        width = integer(data, 'paper_width_mm', 58, 80)
        require(width in (58,80), 'Choose 58 mm or 80 mm paper.')
        require(type(data.get('enabled')) is bool, 'Invalid automatic printing option.')
        with transaction(db()):
            row = db().execute('SELECT * FROM receipt_printers WHERE terminal_id=?', (g.terminal['terminal_id'],)).fetchone()
            require(row, 'Pair the print helper on this laptop first.', 409)
            if data['enabled']:
                require(public_setting(row)['online'], 'Start this laptop\'s print helper first.', 409)
                require(name in json.loads(row['available_printers_json']), 'Choose a printer detected on this laptop.', 409)
                require(not any(v in name.lower() for v in ('pdf','xps','onenote','fax')), 'Choose a physical receipt printer; virtual printers may open a file dialog.')
            db().execute('UPDATE receipt_printers SET printer_name=?,paper_width_mm=?,enabled=?,configured_by_user_id=?,updated_at=? WHERE terminal_id=?',
                         (name,width,int(data['enabled']),g.user['user_id'],now(),g.terminal['terminal_id']))
            event('printer.configured','terminals',g.terminal['terminal_id'],after={'printer_name':name,'paper_width_mm':width,'enabled':data['enabled']})
        return jsonify(ok=True)

    @app.post('/api/sales/<int:sid>/printer-copy')
    @signed_in()
    def copy(sid):
        with transaction(db()):
            sale_access(sid)
            row = db().execute('SELECT * FROM receipt_printers WHERE terminal_id=? AND enabled=1', (g.terminal['terminal_id'],)).fetchone()
            require(row, 'An administrator must set up this laptop\'s printer first.', 409)
            pending = db().execute("SELECT 1 FROM receipt_print_jobs WHERE sale_id=? AND status IN ('queued','claimed')", (sid,)).fetchone()
            require(not pending, 'This receipt already has a pending print job. Check print history before making a copy.', 409)
            job = db().execute('''INSERT INTO receipt_print_jobs(sale_id,terminal_id,job_kind,printer_name,paper_width_mm,requested_by_user_id,created_at)
                VALUES(?,?,'copy',?,?,?,?)''', (sid,g.terminal['terminal_id'],row['printer_name'],row['paper_width_mm'],g.user['user_id'],now())).lastrowid
            db().execute("INSERT INTO receipt_events(sale_id,event_type,output_format,performed_by_user_id,terminal_id,reason,created_at) VALUES(?,'reprint','windows',?,?,?,?)", (sid,g.user['user_id'],g.terminal['terminal_id'],'Requested another printer copy',now()))
            event('receipt.copy_queued','receipt_print_jobs',job,after={'sale_id':sid})
        return jsonify(ok=True)

    @app.post('/api/receipt-printer/jobs/<int:job_id>/resolve')
    @signed_in(True)
    def resolve(job_id):
        data = payload()
        reason = text_field(data, 'reason', 300)
        with transaction(db()):
            row = db().execute('SELECT * FROM receipt_print_jobs WHERE receipt_print_job_id=? AND terminal_id=?', (job_id,g.terminal['terminal_id'])).fetchone()
            require(row and row['status'] in ('queued','claimed'), 'This job is no longer pending.', 409)
            db().execute("UPDATE receipt_print_jobs SET status='failed',finished_at=?,error_message=? WHERE receipt_print_job_id=?", (now(),'Administrator closed: '+reason,job_id))
            event('receipt.print_resolved','receipt_print_jobs',job_id,reason=reason)
        return jsonify(ok=True)

    @app.post('/api/print-agent/poll')
    def poll():
        data = payload()
        printers = data.get('printers', [])
        require(isinstance(printers,list) and len(printers) <= 100 and all(isinstance(n,str) and 0 < len(n) <= 200 for n in printers), 'Invalid printer list.')
        job = None
        with raw_transaction(db()):
            p = helper()
            db().execute('UPDATE receipt_printers SET available_printers_json=?,last_seen_at=? WHERE receipt_printer_id=?', (json.dumps(printers),now(),p['receipt_printer_id']))
            # A claimed job is never automatically claimed again: a crash may follow physical output.
            if p['enabled']:
                job = db().execute("SELECT * FROM receipt_print_jobs WHERE terminal_id=? AND status='queued' ORDER BY receipt_print_job_id LIMIT 1", (p['terminal_id'],)).fetchone()
                if job:
                    db().execute("UPDATE receipt_print_jobs SET status='claimed',claimed_at=? WHERE receipt_print_job_id=?", (now(),job['receipt_print_job_id']))
        if not job:
            return jsonify(job=None)
        try:
            image = receipt_image(db(),job['sale_id'],job['paper_width_mm'])
        except Exception:
            db().execute("UPDATE receipt_print_jobs SET status='failed',error_message='Receipt rendering failed',finished_at=? WHERE receipt_print_job_id=?", (now(),job['receipt_print_job_id']))
            raise
        return jsonify(job={'receipt_print_job_id':job['receipt_print_job_id'],'printer_name':job['printer_name'],
                            'paper_width_mm':job['paper_width_mm'],'image_base64':base64.b64encode(image).decode()})

    @app.post('/api/print-agent/result')
    def result():
        data = payload()
        job_id = integer(data, 'receipt_print_job_id', 1)
        status = data.get('status')
        require(status in ('submitted','failed'), 'Invalid printer result.')
        message = text_field(data, 'error_message', 300, optional=True)
        with raw_transaction(db()):
            p = helper()
            job = db().execute('SELECT * FROM receipt_print_jobs WHERE receipt_print_job_id=? AND terminal_id=?', (job_id,p['terminal_id'])).fetchone()
            require(job, 'Print job not found.', 404)
            if job['status'] == 'claimed':
                db().execute('UPDATE receipt_print_jobs SET status=?,error_message=?,finished_at=? WHERE receipt_print_job_id=?', (status,message,now(),job_id))
                from .db import audit
                audit(db(),'receipt.print_'+status,'receipt_print_jobs',job_id,terminal=p['terminal_id'],reason=message or None)
            else:
                require(job['status'] == status, 'Print job was already resolved.', 409)
        return jsonify(ok=True)
