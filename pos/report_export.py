"""Build the manager's Excel sales report from the same rows as the dashboard."""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


INK = '233047'
ORANGE = 'F66B0E'
PALE = 'FFF1E7'
SOFT = 'F3F6FA'
WHITE = 'FFFFFF'
MUTED = '5E6B7D'
LINE = 'DDE4ED'
MONEY_FORMAT = '#,##0.00;[Red](#,##0.00);0.00'
COUNT_FORMAT = '#,##0;[Red](#,##0);0'


def safe_text(value):
    """Keep database labels as text, even when they resemble Excel formulas."""
    value = ILLEGAL_CHARACTERS_RE.sub('', str(value or ''))
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def amount(minor):
    return (minor or 0) / 100


def build_daily_rows(sales_rows, refunds, business_days):
    days = {
        r['business_date']: {
            'date': r['business_date'], 'day_number': r['day_number'],
            'receipts': set(), 'corrections': set(), 'units': 0,
            'returned_units': 0, 'gross_minor': 0, 'discount_minor': 0,
            'tax_minor': 0, 'sales_minor': 0, 'refunds_minor': 0,
        }
        for r in business_days
    }

    def row_for(record):
        key = record['business_date']
        if key not in days:
            days[key] = {
                'date': key, 'day_number': record['day_number'],
                'receipts': set(), 'corrections': set(), 'units': 0,
                'returned_units': 0, 'gross_minor': 0, 'discount_minor': 0,
                'tax_minor': 0, 'sales_minor': 0, 'refunds_minor': 0,
            }
        return days[key]

    for sale in sales_rows:
        row = row_for(sale)
        row['receipts'].add(sale['sale_id'])
        row['units'] += sale['quantity']
        row['gross_minor'] += sale['quantity'] * sale['unit_price_minor']
        row['discount_minor'] += sale['discount_minor']
        row['tax_minor'] += sale['tax_minor']
        row['sales_minor'] += sale['line_total_minor']
    for refund in refunds:
        row = row_for(refund)
        row['corrections'].add(refund['sale_correction_id'])
        row['returned_units'] += refund['quantity']
        row['refunds_minor'] += refund['refund_minor']
    return [days[key] for key in sorted(days)]


def title_and_context(ws, title, start, end, currency, scope):
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.tabColor = ORANGE if title == 'Sales summary' else INK
    ws['A2'] = title
    ws['A2'].font = Font(name='Aptos', size=15, bold=True, color=INK)
    ws['A3'] = 'Period'
    ws['B3'] = f'{start} to {end}'
    ws['A4'] = 'Currency'
    ws['B4'] = currency
    ws['A5'] = 'Scope'
    ws['B5'] = safe_text(scope)
    for row in (3, 4, 5):
        ws.cell(row, 1).font = Font(name='Aptos', size=10, bold=True, color=MUTED)
        ws.cell(row, 2).font = Font(name='Aptos', size=10, color=INK)
    ws['B5'].alignment = Alignment(wrap_text=False)
    ws.row_dimensions[5].height = 17


def section(ws, row, label, last_col):
    for col in range(1, last_col + 1):
        cell = ws.cell(row, col)
        cell.fill = PatternFill('solid', fgColor=PALE)
        cell.border = Border(bottom=Side(style='thin', color=ORANGE))
    ws.cell(row, 1, label)
    ws.cell(row, 1).font = Font(name='Aptos', size=10, bold=True, color=INK)
    ws.row_dimensions[row].height = 22


def header(ws, row, labels):
    for col, label in enumerate(labels, 1):
        cell = ws.cell(row, col, label)
        cell.fill = PatternFill('solid', fgColor=INK)
        cell.font = Font(name='Aptos', size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = Border(right=Side(style='thin', color=WHITE))
    ws.row_dimensions[row].height = 24


def body_row(ws, row, values, money_cols=(), count_cols=(), date_cols=()):
    for col, value in enumerate(values, 1):
        cell = ws.cell(row, col, safe_text(value) if isinstance(value, str) else value)
        cell.font = Font(name='Aptos', size=10, color=INK)
        cell.alignment = Alignment(vertical='center', horizontal='right' if col in money_cols or col in count_cols else 'left')
        if col in money_cols:
            cell.number_format = MONEY_FORMAT
        elif col in count_cols:
            cell.number_format = COUNT_FORMAT
        elif col in date_cols:
            cell.number_format = 'yyyy-mm-dd'
        if row % 2 == 0:
            cell.fill = PatternFill('solid', fgColor=SOFT)
        cell.border = Border(bottom=Side(style='hair', color=LINE))
    ws.row_dimensions[row].height = 20


def total_row(ws, row, values, money_cols=(), count_cols=()):
    for col, value in enumerate(values, 1):
        cell = ws.cell(row, col, safe_text(value) if isinstance(value, str) else value)
        cell.fill = PatternFill('solid', fgColor=PALE)
        cell.font = Font(name='Aptos', size=10, bold=True, color=INK)
        cell.border = Border(top=Side(style='medium', color=ORANGE))
        cell.alignment = Alignment(horizontal='right' if col in money_cols or col in count_cols else 'left', vertical='center')
        if col in money_cols:
            cell.number_format = MONEY_FORMAT
        elif col in count_cols:
            cell.number_format = COUNT_FORMAT
    ws.row_dimensions[row].height = 24


def detail_sheet(wb, name, start, end, currency, scope, headers, rows, widths, money_cols, count_cols, totals, note=None, date_cols=()):
    ws = wb.create_sheet(name)
    title_and_context(ws, name, start, end, currency, scope)
    header(ws, 7, headers)
    for index, values in enumerate(rows, 8):
        body_row(ws, index, values, money_cols, count_cols, date_cols)
    if not rows:
        ws['A8'] = 'No matching sales or refunds.'
        ws['A8'].font = Font(name='Aptos', size=10, italic=True, color=MUTED)
    total = 8 + len(rows) + (0 if rows else 1)
    total_row(ws, total, totals, money_cols, count_cols)
    if note:
        note_row = total + 2
        ws.cell(note_row, 1, safe_text(note))
        ws.cell(note_row, 1).font = Font(name='Aptos', size=10, italic=True, color=MUTED)
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = 'B8'
    if name == 'Days':
        ws.page_setup.fitToWidth = 2
    if rows:
        ws.auto_filter.ref = f'A7:{get_column_letter(len(headers))}{7 + len(rows)}'
    ws.print_title_rows = '1:7'
    ws.print_options.horizontalCentered = True
    ws.print_area = f'A2:{get_column_letter(len(headers))}{total + (2 if note else 0)}'
    return ws


def export_report(result, sales_rows, refunds, business_days, start, end, currency, scope):
    wb = Workbook()
    summary = wb.active
    summary.title = 'Summary'
    title_and_context(summary, 'Sales summary', start, end, currency, scope)
    daily = build_daily_rows(sales_rows, refunds, business_days)
    s = result['summary']

    section(summary, 7, 'OVERALL SALES', 4)
    metrics = [
        ('Receipts', s['transactions'], False),
        ('Units sold', s['units'], False),
        ('Gross item sales', amount(s['gross_minor']), True),
        ('Discounts', amount(s['discount_minor']), True),
        ('Tax', amount(s['tax_minor']), True),
        ('Sales before refunds', amount(s['sales_minor']), True),
        ('Refunds and voids', amount(s['refunds_minor']), True),
        ('Net sales', amount(s['net_minor']), True),
        ('Average receipt', amount(s['sales_minor']) / s['transactions'] if s['transactions'] else 0, True),
        ('Units returned', s['returned_units'], False),
    ]
    for row, (label, value, is_money) in enumerate(metrics, 8):
        body_row(summary, row, [label, value], (2,) if is_money else (), () if is_money else (2,))
    summary['A15'].font = Font(name='Aptos', size=10, bold=True, color=INK)
    summary['B15'].font = Font(name='Aptos', size=11, bold=True, color=ORANGE)
    section(summary, 20, 'SALES BY BUSINESS DAY', 6)
    header(summary, 21, ['Date', 'Day', 'Receipts', f'Sales ({currency})', f'Refunds ({currency})', f'Net ({currency})'])
    for row_no, item in enumerate(daily, 22):
        body_row(summary, row_no, [date.fromisoformat(item['date']), item['day_number'], len(item['receipts']), amount(item['sales_minor']), amount(item['refunds_minor']), amount(item['sales_minor'] - item['refunds_minor'])], (4, 5, 6), (2, 3), (1,))
    if not daily:
        summary['A22'] = 'No business days in this range.'
    total_row(summary, 22 + len(daily) + (0 if daily else 1), ['TOTAL', '', s['transactions'], amount(s['sales_minor']), amount(s['refunds_minor']), amount(s['net_minor'])], (4, 5, 6), (3,))
    note_row = 25 + len(daily)
    summary.cell(note_row, 1, 'Sales are cash only. Refunds appear on their processing day. Net sales exclude cash in/out and drawer variance.')
    summary.cell(note_row, 1).font = Font(name='Aptos', size=10, italic=True, color=MUTED)
    summary.column_dimensions['A'].width = 36
    summary.column_dimensions['B'].width = 17
    summary.column_dimensions['C'].width = 16
    for col in ('D', 'E', 'F'):
        summary.column_dimensions[col].width = 20
    summary.print_area = f'A2:F{note_row}'

    daily_rows = [[date.fromisoformat(d['date']), d['day_number'], len(d['receipts']), len(d['corrections']), d['units'], d['returned_units'], amount(d['gross_minor']), amount(d['discount_minor']), amount(d['tax_minor']), amount(d['sales_minor']), amount(d['refunds_minor']), amount(d['sales_minor'] - d['refunds_minor']), amount(d['sales_minor']) / len(d['receipts']) if d['receipts'] else 0] for d in daily]
    detail_sheet(wb, 'Days', start, end, currency, scope,
                 ['Business date', 'Day', 'Receipts', 'Returns / voids', 'Units sold', 'Units returned', f'Gross ({currency})', f'Discounts ({currency})', f'Tax ({currency})', f'Sales ({currency})', f'Refunds ({currency})', f'Net ({currency})', f'Avg receipt ({currency})'],
                 daily_rows, [17, 9, 12, 17, 13, 16, 18, 19, 16, 18, 18, 18, 22],
                 (7, 8, 9, 10, 11, 12, 13), (2, 3, 4, 5, 6),
                 ['TOTAL', '', s['transactions'], len({r['sale_correction_id'] for r in refunds}), s['units'], s['returned_units'], amount(s['gross_minor']), amount(s['discount_minor']), amount(s['tax_minor']), amount(s['sales_minor']), amount(s['refunds_minor']), amount(s['net_minor']), amount(s['sales_minor']) / s['transactions'] if s['transactions'] else 0],
                 'Returns and voids are shown on their processing date. Average receipt excludes refunds.', (1,))

    item_meta = {}
    for record in list(sales_rows) + list(refunds):
        item_meta.setdefault(str(record['product_id']), (record['sku_snapshot'], record['description_snapshot']))
    item_rows = []
    for group in result['items']:
        sku, description = item_meta.get(str(group['key']), ('', group['label']))
        item_rows.append([sku, description, group['units'], group['returned_units'], amount(group['sales_minor']), amount(group['refunds_minor']), amount(group['sales_minor'] - group['refunds_minor'])])
    detail_sheet(wb, 'Items', start, end, currency, scope,
                 ['SKU', 'Item', 'Units sold', 'Units returned', f'Sales ({currency})', f'Refunds ({currency})', f'Net ({currency})'],
                 item_rows, [20, 46, 14, 18, 20, 20, 20], (5, 6, 7), (3, 4),
                 ['TOTAL', '', s['units'], s['returned_units'], amount(s['sales_minor']), amount(s['refunds_minor']), amount(s['net_minor'])],
                 'Items use the SKU and description recorded on the first matching sale or return in this report.')

    category_rows = [[g['label'], g['units'], g['returned_units'], amount(g['sales_minor']), amount(g['refunds_minor']), amount(g['sales_minor'] - g['refunds_minor'])] for g in result['categories']]
    detail_sheet(wb, 'Category', start, end, currency, scope,
                 ['Category', 'Units sold', 'Units returned', f'Sales ({currency})', f'Refunds ({currency})', f'Net ({currency})'],
                 category_rows, [40, 16, 19, 20, 20, 20], (4, 5, 6), (2, 3),
                 ['TOTAL', s['units'], s['returned_units'], amount(s['sales_minor']), amount(s['refunds_minor']), amount(s['net_minor'])],
                 'Categories use the name recorded at the time of each sale or return.')

    cashier_receipts = {}
    cashier_corrections = {}
    for r in sales_rows:
        cashier_receipts.setdefault(str(r['cashier_user_id']), set()).add(r['sale_id'])
    for r in refunds:
        cashier_corrections.setdefault(str(r['created_by_user_id']), set()).add(r['sale_correction_id'])
    cashier_rows = [[g['label'], len(cashier_receipts.get(str(g['key']), ())), len(cashier_corrections.get(str(g['key']), ())), g['units'], g['returned_units'], amount(g['sales_minor']), amount(g['refunds_minor']), amount(g['sales_minor'] - g['refunds_minor'])] for g in result['cashiers']]
    detail_sheet(wb, 'Cashier', start, end, currency, scope,
                 ['Cashier', 'Receipts', 'Returns / voids', 'Units sold', 'Units returned', f'Sales ({currency})', f'Refunds ({currency})', f'Net ({currency})'],
                 cashier_rows, [35, 12, 17, 14, 18, 20, 20, 20], (6, 7, 8), (2, 3, 4, 5),
                 ['TOTAL', s['transactions'], len({r['sale_correction_id'] for r in refunds}), s['units'], s['returned_units'], amount(s['sales_minor']), amount(s['refunds_minor']), amount(s['net_minor'])],
                 'Refunds are attributed to the cashier who processed the return or void.')

    output = BytesIO()
    wb.save(output)
    wb.close()
    output.seek(0)
    return output
