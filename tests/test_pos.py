import io
import json
import sqlite3
import subprocess
import sys
import shutil
import uuid
import threading
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from PIL import Image

from pos.app import create_app
from pos.build import build_id
from pos.db import connect, initialize
from pos.printing import receipt_image, receipt_item_name

PASSWORD='Counter-test-password-42'


class POSTest(unittest.TestCase):
    def setUp(self):
        self.test_root=Path(__file__).resolve().parent.parent/'.test-runs'
        self.folder=self.test_root/str(uuid.uuid4())
        self.folder.mkdir(parents=True)
        self.database=self.folder/'pos.sqlite3'
        self.app=create_app(self.database,self.folder/'backups',testing=True)
        self.client=self.app.test_client()
        self.csrf=self.client.get('/api/state').json['csrf']
        self.call('/setup',{'username':'owner','password':PASSWORD,'display_name':'Owner','bazaar_name':'Test Bazaar','timezone':'Asia/Manila','currency_code':'PHP'})
        self.category=self.call('/categories',{'name':'Handmade'}).json['category_id']
        self.product=self.call('/products',{'sku':'TEST-01','barcode':'12345678','description':'Test product','category_id':self.category,'unit':'pc','amount_minor':12550,'active':True}).json['product_id']
        self.call('/stock',{'document_type':'opening','request_key':'opening-request-0001','reference_no':'TEST','manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':10}]})
        self.call('/days/open',{'business_date':'2026-10-19','manager_password':PASSWORD})
        self.call('/shifts/open',{'opening_cash_minor':100000})

    def tearDown(self):
        if self.folder.resolve().is_relative_to(self.test_root.resolve()):
            shutil.rmtree(self.folder)

    def test_server_info_detects_changed_application_files(self):
        current = self.client.get('/api/server-info')
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json['build'], build_id())
        self.assertFalse(current.json['restart_needed'])
        with patch('pos.app.build_id', return_value='files-replaced'):
            stale = self.client.get('/api/server-info')
        self.assertEqual(stale.json['build'], current.json['build'])
        self.assertTrue(stale.json['restart_needed'])

    def call(self,path,data=None,method='POST',client=None,csrf=None,expected=200):
        client=client or self.client
        response=client.open('/api'+path,method=method,json=data,headers={'X-CSRF-Token':csrf or self.csrf})
        if expected is not None:
            self.assertEqual(response.status_code,expected,response.get_data(as_text=True))
        return response

    def ticket(self,quantity=1,client=None,csrf=None):
        t=self.call('/tickets',{},client=client,csrf=csrf).json
        return self.call('/tickets/'+str(t['purchase_ticket_id']),{'version':t['version'],'lines':[{'product_id':self.product,'quantity':quantity}]},'PUT',client,csrf).json

    def checkout_body(self,t,key='checkout-request-0001',tendered=20000):
        return {'purchase_ticket_id':t['purchase_ticket_id'],'version':t['version'],'quote_hash':t['quote_hash'],'tendered_minor':tendered,'request_key':key}

    def scalar(self,sql):
        db=connect(self.database)
        try:return db.execute(sql).fetchone()[0]
        finally:db.close()

    def upload_products(self,rows,headers=('ITEM CODE','DESCRIPTION','CATEGORY','PRICE','TOTAL (PCS)'),preview=False):
        workbook=Workbook();sheet=workbook.active;sheet.title='Inventory'
        sheet.append(['SQI Product List and Inventory']);sheet.append(['Only the selected columns are imported.'])
        sheet.append(list(headers))
        for row in rows:sheet.append(list(row))
        content=io.BytesIO();workbook.save(content);workbook.close();content.seek(0)
        path='/api/products/import/preview' if preview else '/api/products/import'
        return self.client.post(path,data={'workbook':(content,'products.xlsx')},
            headers={'X-CSRF-Token':self.csrf},content_type='multipart/form-data')

    def second_cashier(self):
        uid=self.call('/users',{'username':'cashier2','display_name':'Second cashier','role':'cashier','active':True,'password':PASSWORD,'manager_password':PASSWORD}).json['user_id']
        second=self.app.test_client();csrf=second.get('/api/state').json['csrf']
        self.call('/login',{'username':'cashier2','password':PASSWORD},client=second,csrf=csrf)
        state=second.get('/api/state').json
        self.assertEqual(state['user']['username'],'cashier2')
        self.assertNotIn('approved',state['terminal'])
        self.assertEqual(second.get('/api/catalog').status_code,200)
        self.call('/shifts/open',{'opening_cash_minor':50000},client=second,csrf=csrf)
        return second,csrf,uid

    def test_existing_pending_browser_uses_account_access(self):
        second,csrf,uid=self.second_cashier()
        terminal_id=second.get('/api/state').json['terminal']['terminal_id']
        connection=sqlite3.connect(self.database)
        try:
            connection.execute('UPDATE terminals SET approved=0 WHERE terminal_id=?',(terminal_id,))
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(second.get('/api/catalog').status_code,200)
        self.assertEqual(second.get('/api/state').json['user']['user_id'],uid)
        self.call('/shifts/close',{'counted_cash_minor':50000},client=second,csrf=csrf)

    def test_one_sale_on_double_submit_and_response_loss(self):
        ticket=self.ticket()
        body=self.checkout_body(ticket)
        first=self.call('/checkout',body).json
        retry=self.call('/checkout',body).json
        other_key=self.call('/checkout',{**body,'request_key':'another-request-key-1'}).json
        self.assertEqual(first['sale_id'],retry['sale_id'])
        self.assertEqual(first['sale_id'],other_key['sale_id'])
        self.assertTrue(retry['replayed'])
        for table in ('sales','payments','sale_lines'):
            self.assertEqual(self.scalar(f'SELECT COUNT(*) FROM {table}'),1)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),9)
        receipt=self.client.get('/api/sales/'+str(first['sale_id'])).json
        self.assertEqual(receipt['sale']['receipt_number'],'SQI-001-000001')
        self.assertEqual(receipt['payment']['change_minor'],7450)

    def test_sales_search_and_pagination(self):
        other=self.call('/products',{'sku':'TEST-02','description':'Another test item','category_id':self.category,
            'unit':'pc','amount_minor':5000,'active':True}).json['product_id']
        self.call('/stock',{'document_type':'in','request_key':'sales-page-other-stock','reference_no':'TEST-2',
            'manager_password':PASSWORD,'lines':[{'product_id':other,'quantity':2}]})
        for index in range(2):
            ticket=self.ticket(index+1)
            if index==0:
                ticket=self.call('/tickets/'+str(ticket['purchase_ticket_id']),{'version':ticket['version'],
                    'lines':[{'product_id':self.product,'quantity':1},{'product_id':other,'quantity':1}]},'PUT').json
            self.call('/checkout',self.checkout_body(ticket,key=f'sales-page-request-{index:04d}',tendered=40000))
        first=self.client.get('/api/sales?page_size=1').json
        self.assertEqual((first['total'],first['page'],first['page_size']),(2,1,1))
        self.assertEqual(first['sales'][0]['receipt_number'],'SQI-001-000002')
        second=self.client.get('/api/sales?page=2&page_size=1').json
        self.assertEqual(second['sales'][0]['receipt_number'],'SQI-001-000001')
        self.assertEqual(self.client.get('/api/sales?page=99&page_size=1').json['page'],2)
        self.assertEqual(self.client.get('/api/sales?q=sqi-001-000002').json['total'],1)
        self.assertEqual(self.client.get('/api/sales?q=TEST-01').json['total'],2)
        self.assertEqual(self.client.get('/api/sales?q=TEST').json['total'],2)
        self.assertEqual(self.client.get('/api/sales?q=owner').json['total'],2)
        self.assertEqual(self.client.get('/api/sales?q=missing').json['total'],0)
        self.assertEqual(self.client.get('/api/sales?page_size=0').status_code,400)

    def test_event_end_archive_and_fresh_start(self):
        first=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        first_details=self.client.get(f'/api/sales/{first}').json
        first_receipt=first_details['sale']['receipt_number']
        self.assertEqual(self.client.get('/api/events').status_code,403)
        self.assertEqual(self.client.get('/api/reports?event_id=1').status_code,403)
        self.call('/events/end',{'manager_password':PASSWORD},expected=403)
        self.call('/shifts/close',{'counted_cash_minor':112550})
        self.call('/days/close',{'manager_password':PASSWORD})
        self.call('/logout',{})
        connection=sqlite3.connect(self.database)
        try:
            connection.execute("UPDATE users SET username='ginflorita',role='it_admin' WHERE username='owner'")
            connection.commit()
        finally:
            connection.close()
        self.call('/login',{'username':'ginflorita','password':PASSWORD})
        terminal_id=self.client.get('/api/state').json['terminal']['terminal_id']
        connection=sqlite3.connect(self.database)
        try:
            connection.execute('''INSERT INTO receipt_print_jobs(sale_id,terminal_id,job_kind,printer_name,
                paper_width_mm,status,requested_by_user_id,created_at)
                VALUES(?,?,'automatic','Test printer',80,'queued',1,'2026-10-19')''',(first,terminal_id))
            connection.commit()
        finally:
            connection.close()
        self.call('/events/end',{'manager_password':PASSWORD},expected=409)
        connection=sqlite3.connect(self.database)
        try:
            connection.execute("UPDATE receipt_print_jobs SET status='failed' WHERE sale_id=?",(first,))
            connection.commit()
        finally:
            connection.close()
        blocked=self.folder/'blocked-backup-directory'
        blocked.write_text('This is a file, not a folder.',encoding='utf-8')
        self.app.config['BACKUP_DIR']=str(blocked)
        self.call('/events/end',{'manager_password':PASSWORD},expected=503)
        self.assertIsNone(self.client.get('/api/events').json['events'][0]['archive_backup'])
        self.call('/events/start',{'event_name':'Too early','manager_password':PASSWORD},expected=409)
        self.app.config['BACKUP_DIR']=str(self.folder/'backups')
        self.call('/events/archive',{'manager_password':PASSWORD})
        archived=self.client.get('/api/events').json['events'][0]
        self.assertEqual(archived['status'],'closed')
        self.assertTrue(archived['archive_backup'])
        self.assertTrue((self.folder/'backups'/archived['archive_backup']).is_file())
        self.assertEqual(self.client.get('/api/reports?event_id=1').json['summary']['transactions'],1)
        self.assertEqual(self.client.get('/api/reports').json['summary']['transactions'],0)
        self.assertEqual(self.client.get('/api/sales').json['total'],0)
        self.assertEqual(self.client.get('/api/audit').json['events'],[])
        self.call('/events/start',{'event_name':'Next event','manager_password':PASSWORD})
        state=self.client.get('/api/state').json
        self.assertEqual(state['bazaar']['event_name'],'Next event')
        self.assertIsNone(state['day'])
        self.assertEqual(self.client.get('/api/catalog').json['products'][0]['quantity_on_hand'],0)
        self.assertEqual(self.client.get('/api/inventory').json['summary']['closing'],0)
        self.assertEqual(self.client.get('/api/inventory?event_id=1').json['summary']['closing'],9)
        self.assertEqual(self.client.get('/api/reports').json['summary']['transactions'],0)
        self.assertEqual(self.client.get('/api/reports?event_id=1&format=xlsx').status_code,200)
        self.assertTrue(any(row['action']=='event.started' for row in self.client.get('/api/audit').json['events']))
        initialize(self.database)
        self.call('/days/open',{'business_date':'2026-10-20','manager_password':PASSWORD})
        self.call('/shifts/open',{'opening_cash_minor':0})
        self.call(f'/sales/{first}/corrections',{'manager_password':PASSWORD,
            'request_key':'closed-event-refund-request','reason':'Old event correction','correction_type':'return',
            'lines':[{'sale_line_id':first_details['lines'][0]['sale_line_id'],'quantity':1,'restock_quantity':0}]},expected=409)
        self.call('/stock',{'document_type':'opening','request_key':'new-event-opening-stock','reference_no':'NEXT',
            'manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':2}]})
        second=self.call('/checkout',self.checkout_body(self.ticket(),key='new-event-checkout-request')).json['sale_id']
        second_receipt=self.client.get(f'/api/sales/{second}').json['sale']['receipt_number']
        self.assertNotEqual(first_receipt,second_receipt)
        self.assertEqual(self.client.get('/api/reports').json['summary']['transactions'],1)
        self.assertEqual(self.client.get('/api/reports?event_id=1').json['summary']['transactions'],1)

    def test_inventory_balances_filters_and_posting_dates(self):
        other_category=self.call('/categories',{'name':'Other'}).json['category_id']
        other_product=self.call('/products',{'sku':'OTHER-01','description':'Other item','category_id':other_category,'unit':'pc','amount_minor':5000,'active':True}).json['product_id']
        self.call('/stock',{'document_type':'opening','request_key':'other-opening-stock','manager_password':PASSWORD,
            'lines':[{'product_id':other_product,'quantity':3}]})
        self.call('/stock',{'document_type':'in','request_key':'receipt-stock-0001','reference_no':'DEL-1',
            'manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':4}]})
        self.call('/checkout',self.checkout_body(self.ticket(2),tendered=30000))
        report=self.client.get('/api/inventory').json
        self.assertEqual({key:report['summary'][key] for key in ('products','opening','added','sold','restocked','closing')},
                         {'products':2,'opening':0,'added':17,'sold':2,'restocked':0,'closing':15})
        self.assertEqual(report['movement_total'],4)
        self.assertEqual(report['movements'][0]['movement_type'],'sale')
        self.assertEqual(report['movements'][0]['quantity_change'],-2)
        self.assertEqual(next(p for p in report['products'] if p['product_id']==self.product)['closing'],12)
        filtered=self.client.get(f'/api/inventory?category_id={other_category}').json
        self.assertEqual(filtered['summary']['closing'],3)
        self.assertEqual(filtered['product_total'],1)
        self.assertEqual(filtered['movement_total'],1)
        searched=self.client.get('/api/inventory?q=TEST-01').json
        self.assertEqual(searched['product_total'],1)
        self.assertEqual(searched['summary']['sold'],2)
        future=(datetime.now(ZoneInfo('Asia/Manila')).date()+timedelta(days=1)).isoformat()
        future_report=self.client.get('/api/inventory?from='+future).json
        self.assertEqual(future_report['summary']['opening'],15)
        self.assertEqual(future_report['summary']['closing'],15)
        self.assertEqual(future_report['summary']['added'],0)
        self.assertEqual(future_report['movement_total'],0)
        self.assertEqual(self.client.get('/api/inventory?from=2026-02-31').status_code,400)
        self.assertEqual(self.client.get('/api/inventory?from=2026-11-12&to=2026-11-11').status_code,400)
        second,_,_=self.second_cashier()
        self.assertEqual(second.get('/api/inventory').status_code,403)

    def test_inventory_movement_pages_do_not_repeat_records(self):
        for index in range(16):
            self.call('/stock',{'document_type':'in','request_key':f'paged-stock-receipt-{index:02d}',
                'manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':1}]})
        first=self.client.get('/api/inventory?movement_page=1').json
        second=self.client.get('/api/inventory?movement_page=2').json
        self.assertEqual(first['movement_total'],17)
        self.assertEqual(len(first['movements']),15)
        self.assertEqual(len(second['movements']),2)
        self.assertTrue({m['stock_movement_id'] for m in first['movements']}.isdisjoint(
            {m['stock_movement_id'] for m in second['movements']}))
        self.assertEqual(self.client.get('/api/inventory?movement_page=999').json['movement_page'],2)

    def test_concurrent_duplicate_requests(self):
        body=self.checkout_body(self.ticket())
        cookies={name:self.client.get_cookie(name).value for name in self.app.config['POS_COOKIE_NAMES']}
        barrier=threading.Barrier(2)
        def submit(_):
            c=self.app.test_client()
            for name,value in cookies.items():c.set_cookie(name,value)
            barrier.wait()
            return self.call('/checkout',body,client=c).json
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(submit,range(2)))
        self.assertEqual(results[0]['sale_id'],results[1]['sale_id'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),1)

    def test_last_unit_only_one_cashier_succeeds(self):
        self.product=self.call('/products',{'sku':'LAST-01','description':'Last unit','category_id':self.category,'unit':'pc','amount_minor':12550,'active':True}).json['product_id']
        self.call('/stock',{'document_type':'opening','request_key':'last-unit-opening-01','manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':1}]})
        second,csrf,_=self.second_cashier()
        a=self.checkout_body(self.ticket(),key='cashier-one-checkout')
        b=self.checkout_body(self.ticket(client=second,csrf=csrf),key='cashier-two-checkout')
        barrier=threading.Barrier(2)
        def submit(args):
            c,token,body=args;barrier.wait()
            return self.call('/checkout',body,client=c,csrf=token,expected=None).status_code
        with ThreadPoolExecutor(2) as pool:statuses=list(pool.map(submit,[(self.client,self.csrf,a),(second,csrf,b)]))
        self.assertEqual(sorted(statuses),[200,409])
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances WHERE product_id='+str(self.product)),0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),1)

    def test_changed_payload_cannot_reuse_key(self):
        body=self.checkout_body(self.ticket())
        self.call('/checkout',body)
        self.call('/checkout',{**body,'tendered_minor':30000},expected=409)

    def test_price_change_requires_review_and_history_remains(self):
        t=self.ticket();body=self.checkout_body(t)
        product={'sku':'TEST-01','barcode':'12345678','description':'New label','category_id':self.category,'unit':'pc','amount_minor':14000,'reason':'New price','active':True,'manager_password':PASSWORD}
        self.call('/products/'+str(self.product),product,'PUT')
        self.call('/checkout',body,expected=409)
        new=self.client.get('/api/tickets/'+str(t['purchase_ticket_id'])).json
        self.assertEqual(new['total_minor'],14000)
        sid=self.call('/checkout',self.checkout_body(new)).json['sale_id']
        self.call('/products/'+str(self.product),{**product,'description':'Changed again','amount_minor':16000},'PUT')
        receipt=self.client.get('/api/sales/'+str(sid)).json
        self.assertEqual(receipt['lines'][0]['description_snapshot'],'New label')
        self.assertEqual(receipt['lines'][0]['unit_price_minor'],14000)

    def test_receipt_uses_short_description_saved_at_sale(self):
        product={'sku':'TEST-01','barcode':'12345678','description':'Long catalog description',
                 'short_description':'Short receipt name','category_id':self.category,
                 'unit':'pc','amount_minor':12550,'active':True}
        self.call('/products/'+str(self.product),product,'PUT')
        sid=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        self.call('/products/'+str(self.product),{**product,'short_description':'Changed later'},'PUT')
        line=self.client.get('/api/sales/'+str(sid)).json['lines'][0]
        self.assertEqual(line['description_snapshot'],'Long catalog description')
        self.assertEqual(line['short_description_snapshot'],'Short receipt name')
        self.assertEqual(receipt_item_name(line),'Short receipt name')
        self.assertEqual(receipt_item_name({'short_description_snapshot':'',
                                            'description_snapshot':'Older receipt name'}),'Older receipt name')

    def test_unit_price_is_locked_while_selling_price_controls_checkout(self):
        data={'sku':'DUAL-PRICE','description':'Two prices','category_id':self.category,'unit':'pc',
              'unit_price_minor':5000,'selling_price_minor':6500,'quantity':3,
              'request_key':'dual-price-opening-0001','active':True}
        pid=self.call('/products',data).json['product_id']
        product=next(p for p in self.client.get('/api/catalog').json['products'] if p['product_id']==pid)
        self.assertEqual((product['unit_price_minor'],product['selling_price_minor']),(5000,6500))
        ticket=self.call('/tickets',{}).json
        ticket=self.call('/tickets/'+str(ticket['purchase_ticket_id']),
                         {'version':ticket['version'],'lines':[{'product_id':pid,'quantity':1}]},'PUT').json
        self.assertEqual(ticket['total_minor'],6500)
        self.call('/products/'+str(pid),{**data,'selling_price_minor':7200,'reason':'Retail adjustment'},'PUT')
        updated=self.client.get('/api/tickets/'+str(ticket['purchase_ticket_id'])).json
        self.assertEqual(updated['total_minor'],7200)
        self.call('/products/'+str(pid),{**data,'unit_price_minor':5500,
            'selling_price_minor':7200,'reason':'Attempted base price change'},'PUT',expected=409)
        connection=connect(self.database)
        try:
            self.assertEqual(connection.execute('SELECT unit_price_minor FROM products WHERE product_id=?',
                                                (pid,)).fetchone()[0],5000)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM product_prices WHERE product_id=?',
                                                (pid,)).fetchone()[0],2)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Unit price is locked'):
                connection.execute('UPDATE products SET unit_price_minor=5500 WHERE product_id=?',(pid,))
        finally:connection.close()

    def test_manager_creates_and_edits_catalog_without_reason_or_password(self):
        data={'sku':'TEST-02','description':'New item','category_id':self.category,'unit':'pc','amount_minor':8500,'active':True}
        pid=self.call('/products',data).json['product_id']
        self.call('/products/'+str(pid),{**data,'description':'Updated description','barcode':'987654321'},'PUT')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_prices WHERE product_id='+str(pid)),1)
        self.assertEqual(self.scalar('SELECT reason FROM product_prices WHERE product_id='+str(pid)),'Initial selling price')
        connection=connect(self.database)
        try:
            events=connection.execute("SELECT * FROM audit_events WHERE entity_type='products' AND entity_key=? ORDER BY audit_event_id",(str(pid),)).fetchall()
            self.assertEqual([r['action'] for r in events],['product.created','product.updated'])
            self.assertTrue(all(r['actor_user_id']==1 and r['terminal_id'] is not None for r in events))
            self.assertEqual(json.loads(events[-1]['before_json'])['description'],'New item')
            self.assertEqual(json.loads(events[-1]['after_json'])['description'],'Updated description')
            self.assertIsNone(events[-1]['reason'])
        finally:connection.close()

    def test_bulk_product_upload_imports_only_sku_and_description_as_drafts(self):
        rows=[
            ('TEST-01','Existing product','Existing category',999,500),
            ('NEW-01','First imported product','Ignored category',125,900),
            (188,'Numeric item code','Ignored category',85,42),
            ('NEW-01','Repeated item code','Different category',300,12),
            ('MISSING-DESCRIPTION','','Ignored category',50,1),
        ]
        preview=self.upload_products(rows,preview=True)
        self.assertEqual(preview.status_code,200,preview.get_data(as_text=True))
        self.assertEqual((preview.json['ready'],preview.json['existing'],preview.json['duplicate_rows'],preview.json['rejected_rows']),(2,1,1,1))
        self.assertEqual({product['sku'] for product in preview.json['products']},{'NEW-01','188'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_import_drafts'),0)
        response=self.upload_products(rows)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        result=response.json
        self.assertEqual((result['imported'],result['existing'],result['duplicate_rows'],result['rejected_rows']),(2,1,1,1))
        catalog=self.client.get('/api/catalog').json
        self.assertEqual({draft['sku'] for draft in catalog['drafts']},{'NEW-01','188'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM products'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_prices'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_balances'),1)
        draft=next(draft for draft in catalog['drafts'] if draft['sku']=='NEW-01')
        completed={'draft_id':draft['product_import_draft_id'],'sku':draft['sku'],'description':draft['description'],
                   'category_id':self.category,'unit':'pc','amount_minor':12500,'quantity':7,
                   'request_key':'product-opening-stock-0001','active':True}
        self.call('/products',completed)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_import_drafts'),1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM products WHERE sku='NEW-01'"),1)
        self.assertEqual(self.scalar("SELECT quantity_on_hand FROM stock_balances JOIN products USING(product_id) WHERE sku='NEW-01'"),7)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM stock_movements JOIN products USING(product_id) WHERE sku='NEW-01' AND quantity_change=7"),1)

    def test_bulk_product_upload_requires_expected_headers(self):
        response=self.upload_products([('A-1','Description')],headers=('SKU','PRODUCT NAME'))
        self.assertEqual(response.status_code,400)
        self.assertIn('ITEM CODE and DESCRIPTION',response.json['error'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_import_drafts'),0)

    def test_product_keeps_distinct_long_short_and_unit_descriptions(self):
        data={'sku':'PAINT-01','barcode':'0001234567890','description':'Acrylic paint 100 mL bottle in blue',
              'short_description':'Blue acrylic paint','category_id':self.category,'unit':'BTL',
              'unit_description':'bottle','amount_minor':6500,'active':True}
        product_id=self.call('/products',data).json['product_id']
        product=next(p for p in self.client.get('/api/catalog').json['products'] if p['product_id']==product_id)
        for key in ('sku','barcode','description','short_description','unit','unit_description'):
            self.assertEqual(product[key],data[key])
        self.call('/products/'+str(product_id),{**data,'short_description':'Paint blue',
            'unit_description':'100 mL bottle'},'PUT')
        self.assertEqual(self.scalar("SELECT short_description FROM products WHERE sku='PAINT-01'"),'Paint blue')
        self.assertEqual(self.scalar("SELECT unit_description FROM products WHERE sku='PAINT-01'"),'100 mL bottle')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_prices'),2)

    def test_only_existing_price_changes_require_a_reason(self):
        data={'sku':'TEST-01','barcode':'12345678','description':'Should roll back','category_id':self.category,'unit':'pc','amount_minor':15000,'active':True}
        self.call('/products/'+str(self.product),data,'PUT',expected=400)
        self.call('/products/'+str(self.product),{**data,'reason':'   '},'PUT',expected=400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_prices'),1)
        self.assertEqual(self.scalar('SELECT description FROM products'),'Test product')
        self.call('/products/'+str(self.product),{**data,'reason':'Supplier cost changed'},'PUT')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_prices'),2)
        connection=connect(self.database)
        try:
            event=connection.execute("SELECT * FROM audit_events WHERE action='product.updated' ORDER BY audit_event_id DESC LIMIT 1").fetchone()
            self.assertEqual(event['reason'],'Supplier cost changed')
            self.assertEqual(json.loads(event['before_json'])['amount_minor'],12550)
            self.assertEqual(json.loads(event['after_json'])['amount_minor'],15000)
        finally:connection.close()

    def test_catalog_session_access_does_not_grant_cashier_or_anonymous_writes(self):
        data={'sku':'TEST-02','description':'Not permitted','category_id':self.category,'unit':'pc','amount_minor':8500,'active':True}
        second,csrf,_=self.second_cashier()
        self.call('/products',data,client=second,csrf=csrf,expected=403)
        self.call('/products/'+str(self.product),data,'PUT',client=second,csrf=csrf,expected=403)
        response=second.post('/api/products/'+str(self.product)+'/image',data={},headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,403)
        anonymous=self.app.test_client()
        token=anonymous.get('/api/state').json['csrf']
        self.call('/products',data,client=anonymous,csrf=token,expected=401)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM products'),1)

    def test_sensitive_changes_still_require_manager_password(self):
        self.call('/users',{'username':'newuser','display_name':'New user','role':'cashier','active':True,'password':PASSWORD},expected=403)
        self.call('/stock',{'document_type':'in','request_key':'missing-approval-001','reference_no':'IN','reason':'Delivery','lines':[{'product_id':self.product,'quantity':2}]},expected=403)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),10)

    def test_it_admin_keeps_manager_access_and_only_self_can_update(self):
        admin_db=self.folder/'admin.sqlite3'
        admin_app=create_app(admin_db,self.folder/'admin-backups',testing=True)
        admin=admin_app.test_client();admin_csrf=admin.get('/api/state').json['csrf']
        self.call('/setup',{'username':'ginflorita','password':PASSWORD,'display_name':'IT Owner',
            'bazaar_name':'Admin Test','timezone':'Asia/Manila','currency_code':'PHP'},client=admin,csrf=admin_csrf)
        account=admin.get('/api/state').json['user']
        self.assertEqual(account['role'],'it_admin')
        self.assertEqual(admin.get('/api/team').status_code,200)
        manager_id=self.call('/users',{'username':'manager2','display_name':'Other manager','role':'manager',
            'active':True,'password':PASSWORD,'manager_password':PASSWORD},client=admin,csrf=admin_csrf).json['user_id']
        other=admin_app.test_client();other_csrf=other.get('/api/state').json['csrf']
        self.call('/login',{'username':'manager2','password':PASSWORD},client=other,csrf=other_csrf)
        update={'display_name':'Changed by other manager','role':'it_admin','active':True,
            'password':'','manager_password':PASSWORD}
        self.call('/users/'+str(account['user_id']),update,'PUT',other,other_csrf,expected=403)
        self.call('/users/'+str(account['user_id']),{**update,'role':'manager'},'PUT',admin,admin_csrf,expected=403)
        self.call('/users/'+str(account['user_id']),{**update,'active':False},'PUT',admin,admin_csrf,expected=403)
        self.call('/users',{'username':'another-admin','display_name':'Another admin','role':'it_admin',
            'active':True,'password':PASSWORD,'manager_password':PASSWORD},client=admin,csrf=admin_csrf,expected=403)
        self.call('/users/'+str(account['user_id']),{**update,'display_name':'Updated by ginflorita'},
            'PUT',admin,admin_csrf)
        connection=connect(admin_db)
        try:
            saved=connection.execute('SELECT display_name,role,active FROM users WHERE user_id=?',
                (account['user_id'],)).fetchone()
            self.assertEqual(tuple(saved),('Updated by ginflorita','it_admin',1))
            self.assertEqual(connection.execute('SELECT role FROM users WHERE user_id=?',(manager_id,)).fetchone()[0],'manager')
        finally:connection.close()

    def test_existing_ginflorita_account_upgrades_without_losing_user_ids(self):
        legacy_db=self.folder/'legacy.sqlite3'
        legacy_schema=Path(__file__).resolve().parent.parent.joinpath('pos','schema.sql').read_text(encoding='utf-8')
        legacy_schema=legacy_schema.replace("role IN ('it_admin','manager','cashier')",
            "role IN ('manager','cashier')").replace('PRAGMA user_version=10;','PRAGMA user_version=8;')
        connection=sqlite3.connect(legacy_db)
        try:
            connection.executescript(legacy_schema)
            connection.execute("INSERT INTO users(user_id,username,display_name,password_hash,role,created_at) VALUES(1,'ginflorita','IT Owner','hash','manager','2026-01-01')")
            connection.execute("INSERT INTO users(user_id,username,display_name,password_hash,role,created_by_user_id,created_at) VALUES(2,'cashier1','Cashier','hash','cashier',1,'2026-01-01')")
            connection.commit()
        finally:connection.close()
        initialize(legacy_db)
        connection=connect(legacy_db)
        try:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],10)
            self.assertEqual([tuple(row) for row in connection.execute('SELECT user_id,role FROM users ORDER BY user_id')],[(1,'it_admin'),(2,'cashier')])
            self.assertEqual(connection.execute('SELECT created_by_user_id FROM users WHERE user_id=2').fetchone()[0],1)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally:connection.close()

    def test_cashier_roles_receipt_scope_and_csrf(self):
        sid=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        second,csrf,_=self.second_cashier()
        self.call('/products',{},client=second,csrf=csrf,expected=403)
        self.assertEqual(second.get('/api/reports').status_code,403)
        self.assertEqual(second.get('/api/sales/'+str(sid)).status_code,403)
        self.call('/sales/'+str(sid)+'/reprint',{},client=second,csrf=csrf,expected=403)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM receipt_events'),1)
        response=self.client.post('/api/tickets',json={})
        self.assertEqual(response.status_code,403)
        response=self.client.post('/api/tickets',json={},headers={'X-CSRF-Token':self.csrf,'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)

    def test_stale_ticket_and_transfer_ownership(self):
        t=self.ticket()
        self.call('/tickets/'+str(t['purchase_ticket_id']),{'version':0,'lines':[]},'PUT',expected=409)
        second,csrf,uid=self.second_cashier()
        self.call('/tickets/'+str(t['purchase_ticket_id'])+'/transfer',{'version':t['version'],'target_user_id':uid,'reason':'Hand to second counter'})
        self.call('/checkout',self.checkout_body(t),expected=403)
        transferred=second.get('/api/tickets/'+str(t['purchase_ticket_id'])).json
        result=self.call('/checkout',self.checkout_body(transferred),client=second,csrf=csrf)
        self.assertTrue(result.json['sale_id'])

    def test_stock_and_return_requests_are_idempotent(self):
        data={'document_type':'in','request_key':'stock-in-request-001','reference_no':'IN-01','reason':'Delivery','manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':3}]}
        first=self.call('/stock',data).json
        self.assertEqual(first,self.call('/stock',data).json)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),13)
        self.call('/stock',{**data,'lines':[{'product_id':self.product,'quantity':4}]},expected=409)
        sid=self.call('/checkout',self.checkout_body(self.ticket(quantity=2),tendered=30000)).json['sale_id']
        lid=self.client.get('/api/sales/'+str(sid)).json['lines'][0]['sale_line_id']
        correction={'request_key':'return-request-0001','correction_type':'return','reason':'Customer return','manager_password':PASSWORD,'lines':[{'sale_line_id':lid,'quantity':1,'restock_quantity':1}]}
        a=self.call('/sales/'+str(sid)+'/corrections',correction).json
        b=self.call('/sales/'+str(sid)+'/corrections',correction).json
        self.assertEqual(a['sale_correction_id'],b['sale_correction_id'])
        self.call('/sales/'+str(sid)+'/corrections',{**correction,'request_key':'return-request-0002','lines':[{'sale_line_id':lid,'quantity':2,'restock_quantity':2}]},expected=409)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sale_corrections'),1)

    def test_stock_in_defaults_reason_and_keeps_audit_and_retry_protection(self):
        self.assertEqual(self.scalar('SELECT reason FROM stock_documents'),'Opening stock')
        data={'document_type':'in','request_key':'stock-optional-reason-01','manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':5}]}
        first=self.call('/stock',data).json
        self.assertEqual(first,self.call('/stock',{**data,'reason':'   '}).json)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),15)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_documents'),2)
        self.assertEqual(self.scalar('SELECT reason FROM stock_documents ORDER BY stock_document_id DESC LIMIT 1'),'Stock received')
        connection=connect(self.database)
        try:
            event=connection.execute("SELECT * FROM audit_events WHERE action='stock.posted' ORDER BY audit_event_id DESC LIMIT 1").fetchone()
            self.assertEqual(event['reason'],'Stock received')
            self.assertEqual(event['actor_user_id'],1)
            self.assertIsNotNone(event['terminal_id'])
        finally:connection.close()
        self.call('/stock',{**data,'reason':'Different delivery'},expected=409)
        self.call('/stock',{**data,'request_key':'stock-optional-reason-02','reason':'Supplier delivery'})
        self.assertEqual(self.scalar('SELECT reason FROM stock_documents ORDER BY stock_document_id DESC LIMIT 1'),'Supplier delivery')

    def test_bulk_stock_posts_all_items_once_or_rolls_back_together(self):
        second=self.call('/products',{'sku':'TEST-02','description':'Second product','category_id':self.category,
            'unit':'pc','amount_minor':5000,'active':True}).json['product_id']
        catalog={p['product_id']:p for p in self.client.get('/api/catalog').json['products']}
        self.assertEqual(catalog[self.product]['has_stock_history'],1)
        self.assertEqual(catalog[second]['has_stock_history'],0)
        body={'document_type':'in','request_key':'bulk-stock-receipt-0001','reference_no':'DELIVERY-1',
            'manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':3},
                {'product_id':second,'quantity':7}]}
        result=self.call('/stock',body).json
        self.assertEqual(result,self.call('/stock',body).json)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_documents'),2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_document_lines'),3)
        db=connect(self.database)
        try:
            balances=dict(db.execute('SELECT product_id,quantity_on_hand FROM stock_balances'))
            self.assertEqual(balances[self.product],13)
            self.assertEqual(balances[second],7)
        finally:db.close()
        self.call('/stock',{**body,'request_key':'bulk-stock-invalid-0002',
            'lines':[{'product_id':self.product,'quantity':5},{'product_id':999999,'quantity':1}]},expected=404)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_documents'),2)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances WHERE product_id=1'),13)

    def test_manual_stock_removals_and_resets_are_blocked(self):
        for kind in ('out','count','adjustment'):
            with self.subTest(kind=kind):
                data={'document_type':kind,'request_key':'stock-disabled-'+kind,'manager_password':PASSWORD,'reason':'Manual change','lines':[{'product_id':self.product,'quantity':1}]}
                self.call('/stock',data,expected=400)
        db=connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""INSERT INTO stock_documents(bazaar_id,bazaar_day_id,document_type,reference_no,reason,request_key,status,created_by_user_id,approved_by_user_id,created_at,approved_at)
                    VALUES(1,1,'count','','Manual change','direct-count-disabled','posted',1,1,'2026-10-19','2026-10-19')""")
        finally:db.close()
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),10)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_documents'),1)

    def test_stock_receipts_require_positive_quantity(self):
        for quantity in (0,-1):
            with self.subTest(quantity=quantity):
                self.call('/stock',{'document_type':'in','request_key':'invalid-receipt-'+str(quantity),'manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':quantity}]},expected=400)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),10)

    def test_cashier_selects_manager_discount_and_refunds_paid_amount(self):
        rate_id=self.call('/discount',{'discount_percent_bp':1250,'manager_password':PASSWORD}).json['discount_rate_id']
        cashier,csrf,_=self.second_cashier()
        ticket=self.ticket(quantity=3,client=cashier,csrf=csrf)
        quote=self.call('/tickets/'+str(ticket['purchase_ticket_id'])+'/discount',
                        {'version':ticket['version'],'discount_percent_bp':1250},'PUT',cashier,csrf).json
        self.assertEqual(quote['subtotal_minor'],37650)
        self.assertEqual(quote['discount_minor'],4706)
        self.assertEqual(quote['total_minor'],32944)
        sale_id=self.call('/checkout',self.checkout_body(quote,tendered=33000),client=cashier,csrf=csrf).json['sale_id']
        sale=self.client.get('/api/sales/'+str(sale_id)).json
        self.assertEqual(sale['sale']['discount_percent_bp'],1250)
        self.assertEqual(sale['sale']['total_minor'],32944)
        self.assertEqual(sale['payment']['change_minor'],56)
        self.call('/discount/'+str(rate_id),{'manager_password':PASSWORD},'DELETE')
        self.assertEqual(self.client.get('/api/sales/'+str(sale_id)).json['sale']['discount_percent_bp'],1250)
        line=sale['lines'][0]
        self.assertEqual(line['discount_minor'],4706)
        self.assertEqual(line['line_total_minor'],32944)
        connection=connect(self.database)
        try:
            with Image.open(io.BytesIO(receipt_image(connection,sale_id,'roll_80'))) as artwork:
                self.assertGreater(artwork.height,300)
        finally:connection.close()
        report=self.client.get('/api/reports').json['summary']
        self.assertEqual(report['gross_minor'],37650)
        self.assertEqual(report['discount_minor'],4706)
        self.assertEqual(report['sales_minor'],32944)
        export=self.client.get('/api/reports?format=xlsx')
        self.assertEqual(export.status_code,200)
        workbook=load_workbook(io.BytesIO(export.data),read_only=True,data_only=True)
        try:
            self.assertEqual(workbook['Summary']['B11'].value,47.06)
            self.assertEqual(workbook['Days']['H8'].value,47.06)
        finally:workbook.close()
        for number,expected_refund in ((1,10981),(2,10981),(3,10982)):
            result=self.call('/sales/'+str(sale_id)+'/corrections',
                {'request_key':f'discount-refund-{number:02d}-0001','correction_type':'return',
                 'reason':'Customer return','manager_password':PASSWORD,
                 'lines':[{'sale_line_id':line['sale_line_id'],'quantity':1,'restock_quantity':1}]}).json
            self.assertEqual(result['refund_minor'],expected_refund)
        self.assertEqual(self.scalar('SELECT SUM(refund_minor) FROM correction_lines'),32944)
        self.assertEqual(self.client.get('/api/reports').json['summary']['net_minor'],0)

    def test_discount_changes_invalidate_open_quotes_and_require_manager(self):
        cashier,csrf,_=self.second_cashier()
        first=self.call('/discount',{'discount_percent_bp':1000,'manager_password':PASSWORD}).json['discount_rate_id']
        second=self.call('/discount',{'discount_percent_bp':2000,'manager_password':PASSWORD}).json['discount_rate_id']
        self.assertEqual([rate['percent_bp'] for rate in self.client.get('/api/discount').json['rates']],[1000,2000])
        self.call('/discount',{'discount_percent_bp':1000,'manager_password':PASSWORD},expected=409)
        ticket=self.ticket(client=cashier,csrf=csrf)
        quote=self.call('/tickets/'+str(ticket['purchase_ticket_id'])+'/discount',
                        {'version':ticket['version'],'discount_percent_bp':1000},'PUT',cashier,csrf).json
        self.assertEqual(quote['total_minor'],11295)
        self.call('/discount',{'discount_percent_bp':3000,'manager_password':PASSWORD},client=cashier,csrf=csrf,expected=403)
        self.call('/discount',{'discount_percent_bp':3000},expected=403)
        self.call('/discount/'+str(first),{'manager_password':PASSWORD},'DELETE',cashier,csrf,expected=403)
        self.call('/discount/'+str(first),{},'DELETE',expected=403)
        self.call('/discount/'+str(first),{'manager_password':PASSWORD},'DELETE')
        self.call('/checkout',self.checkout_body(quote),client=cashier,csrf=csrf,expected=409)
        refreshed=self.call('/tickets/'+str(ticket['purchase_ticket_id']),method='GET',client=cashier,csrf=csrf).json
        self.assertEqual(refreshed['total_minor'],12550)
        self.assertEqual(refreshed['discount_percent_bp'],0)
        self.assertNotEqual(refreshed['quote_hash'],quote['quote_hash'])
        selected=self.call('/tickets/'+str(ticket['purchase_ticket_id'])+'/discount',
                           {'version':refreshed['version'],'discount_percent_bp':2000},'PUT',cashier,csrf).json
        self.assertEqual(selected['total_minor'],10040)
        self.call('/discount/'+str(second),{'manager_password':PASSWORD},'DELETE')
        disabled=self.call('/tickets/'+str(ticket['purchase_ticket_id']),method='GET',client=cashier,csrf=csrf).json
        self.assertEqual(disabled['discount_selected'],0)
        self.assertEqual(disabled['total_minor'],12550)
        self.call('/tickets/'+str(ticket['purchase_ticket_id'])+'/discount',
                  {'version':disabled['version'],'discount_percent_bp':2000},'PUT',cashier,csrf,expected=409)
        self.assertEqual(self.client.get('/api/discount').json['rates'],[])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),0)

    def test_existing_single_discount_migrates_with_open_ticket(self):
        ticket=self.ticket()
        connection=connect(self.database)
        try:
            connection.execute('DROP TABLE discount_rates')
            connection.execute('ALTER TABLE purchase_tickets DROP COLUMN discount_percent_bp')
            connection.execute('UPDATE system_settings SET discount_percent_bp=1500 WHERE system_setting_id=1')
            connection.execute('UPDATE purchase_tickets SET discount_selected=1 WHERE purchase_ticket_id=?',
                               (ticket['purchase_ticket_id'],))
            connection.execute('PRAGMA user_version=4')
        finally:connection.close()
        initialize(self.database)
        self.assertEqual(self.scalar('PRAGMA user_version'),10)
        self.assertEqual([r['percent_bp'] for r in self.client.get('/api/discount').json['rates']],[1500])
        restored=self.call('/tickets/'+str(ticket['purchase_ticket_id']),method='GET').json
        self.assertEqual(restored['discount_percent_bp'],1500)
        self.assertEqual(restored['total_minor'],10667)

    def test_day_two_refund_does_not_rewrite_day_one(self):
        sid=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        lid=self.client.get('/api/sales/'+str(sid)).json['lines'][0]['sale_line_id']
        self.call('/shifts/close',{'counted_cash_minor':112550})
        self.call('/days/close',{'manager_password':PASSWORD})
        self.call('/days/open',{'business_date':'2026-10-20','manager_password':PASSWORD})
        self.call('/shifts/open',{'opening_cash_minor':100000})
        self.call('/sales/'+str(sid)+'/corrections',{'request_key':'day-two-return-0001','correction_type':'return','reason':'Returned next day','manager_password':PASSWORD,'lines':[{'sale_line_id':lid,'quantity':1,'restock_quantity':0}]})
        day1=self.client.get('/api/reports?from=2026-10-19&to=2026-10-19').json['summary']
        day2=self.client.get('/api/reports?from=2026-10-20&to=2026-10-20').json['summary']
        self.assertEqual(day1['net_minor'],12550);self.assertEqual(day1['refunds_minor'],0)
        self.assertEqual(day2['net_minor'],-12550)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),9)
        response=self.client.get('/api/reports?format=xlsx&from=2026-10-19&to=2026-10-20')
        self.assertEqual(response.status_code,200)
        self.assertIn('SQI-POS-Event-001-(2026-10-19-to-2026-10-20).xlsx',response.headers['Content-Disposition'])
        workbook=load_workbook(io.BytesIO(response.data),read_only=False,data_only=True)
        try:
            self.assertEqual(workbook.sheetnames,['Summary','Days','Items','Category','Cashier'])
            self.assertEqual(workbook['Summary']['B15'].value,0)
            self.assertEqual(workbook['Days']['J8'].value,125.5)
            self.assertEqual(workbook['Days']['L9'].value,-125.5)
            self.assertEqual(workbook['Days']['L10'].value,0)
            self.assertEqual(workbook['Items']['G8'].value,0)
            self.assertEqual(workbook['Category']['F8'].value,0)
            self.assertEqual(workbook['Cashier']['H8'].value,0)
            self.assertEqual(workbook['Days'].freeze_panes,'B8')
        finally:workbook.close()

    def test_failed_checkout_rolls_back_everything(self):
        self.call('/checkout',self.checkout_body(self.ticket(),tendered=1),expected=400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM payments'),0)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),10)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_tickets WHERE state='open'"),1)

    def test_immutable_history_and_negative_stock(self):
        self.call('/checkout',self.checkout_body(self.ticket()))
        db=connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM sales')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE audit_events SET action='tampered'")
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE stock_balances SET quantity_on_hand=-1')
        finally:db.close()

    def test_image_versions_and_backup_integrity(self):
        for color in ('red','green'):
            image=io.BytesIO();Image.new('RGB',(40,40),color).save(image,'PNG');image.seek(0)
            response=self.client.post('/api/products/'+str(self.product)+'/image',data={'image':(image,'test.png')},headers={'X-CSRF-Token':self.csrf})
            self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_images'),2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM product_images WHERE superseded_at IS NULL'),1)
        result=self.call('/backups',{'manager_password':PASSWORD}).json
        self.assertEqual(result['status'],'verified')
        backup=next((self.folder/'backups').glob('*.sqlite3'))
        db=sqlite3.connect(backup)
        try:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM product_images').fetchone()[0],2)
        finally:db.close()

    def test_login_throttling_and_disabled_sessions(self):
        second,csrf,uid=self.second_cashier()
        for _ in range(5):self.call('/login',{'username':'cashier2','password':'wrong'},client=second,csrf=csrf,expected=401)
        self.call('/login',{'username':'cashier2','password':PASSWORD},client=second,csrf=csrf,expected=429)
        self.call('/shifts/close',{'counted_cash_minor':50000},client=second,csrf=csrf)
        self.call('/users/'+str(uid),{'display_name':'Second cashier','role':'cashier','active':False,'password':'','manager_password':PASSWORD},'PUT')
        self.assertEqual(second.get('/api/catalog').status_code,401)

    def test_automatic_receipt_print_job_is_unique_and_terminal_scoped(self):
        token=self.call('/receipt-printer/pair',{}).json['pairing_token']
        agent=self.app.test_client()
        def poll(token=token):
            return agent.post('/api/print-agent/poll',json={'printers':['USB Receipt']},headers={'Authorization':'Bearer '+token})
        self.assertEqual(poll('x'*43).status_code,403)
        self.assertEqual(agent.post('/api/print-agent/poll',json={'printers':[]},headers={'Authorization':'Bearer '+token,'Origin':'http://localhost'}).status_code,403)
        self.assertEqual(poll().status_code,200)
        self.call('/receipt-printer',{'printer_name':'Other laptop printer','paper_width_mm':80,'enabled':True},'PUT',expected=409)
        self.call('/receipt-printer',{'printer_name':'USB Receipt','paper_width_mm':80,'enabled':True},'PUT')
        body=self.checkout_body(self.ticket())
        sale=self.call('/checkout',body).json['sale_id']
        self.call('/checkout',body)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM receipt_print_jobs'),1)
        self.call('/sales/'+str(sale)+'/reprint',{},expected=409)
        second,csrf,uid=self.second_cashier()
        self.call('/receipt-printer/pair',{},client=second,csrf=csrf,expected=403)
        self.assertEqual(second.get('/api/receipt-printer').json['jobs'],[])
        claimed=poll().json['job']
        self.assertEqual(claimed['printer_name'],'USB Receipt')
        import base64
        image=Image.open(io.BytesIO(base64.b64decode(claimed['image_base64'])))
        self.assertEqual(image.width,576)
        self.assertIsNone(poll().json['job'])  # Lost response or helper crash never prints again.
        self.call('/sales/'+str(sale)+'/printer-copy',{},expected=409)
        result={'receipt_print_job_id':claimed['receipt_print_job_id'],'status':'failed','error_message':'USB disconnected: check queue'}
        for _ in range(2):
            self.assertEqual(agent.post('/api/print-agent/result',json=result,headers={'Authorization':'Bearer '+token}).status_code,200)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events WHERE action='receipt.print_failed'"),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM payments'),1)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),9)
        self.call('/sales/'+str(sale)+'/printer-copy',{})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM receipt_print_jobs'),2)
        copy=poll().json['job']
        self.call('/receipt-printer/jobs/'+str(copy['receipt_print_job_id'])+'/resolve',{'reason':'Stopped helper and checked Windows queue'})
        self.call('/receipt-printer/pair',{})
        self.assertEqual(poll().status_code,403)  # Re-pair revokes the old token.

    def test_disconnect_printer_revokes_pairing_and_cancels_waiting_receipt(self):
        token=self.call('/receipt-printer/pair',{}).json['pairing_token']
        agent=self.app.test_client()
        def poll():
            return agent.post('/api/print-agent/poll',json={'printers':['USB Receipt']},
                              headers={'Authorization':'Bearer '+token})
        self.assertEqual(poll().status_code,200)
        self.call('/receipt-printer',{'printer_name':'USB Receipt','paper_width_mm':80,'enabled':True},'PUT')
        self.call('/checkout',self.checkout_body(self.ticket()))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM receipt_print_jobs WHERE status='queued'"),1)
        second,csrf,_=self.second_cashier()
        self.call('/receipt-printer',{},'DELETE',client=second,csrf=csrf,expected=403)
        result=self.call('/receipt-printer',{},'DELETE').json
        self.assertEqual(result['cancelled_jobs'],1)
        self.assertIsNone(self.client.get('/api/receipt-printer').json['printer'])
        self.assertEqual(poll().status_code,403)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM receipt_print_jobs WHERE status='failed'"),1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events WHERE action='printer.disconnected'"),1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events WHERE action='receipt.print_cancelled'"),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),1)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),9)

    def test_disconnect_printer_waits_for_claimed_job_review(self):
        token=self.call('/receipt-printer/pair',{}).json['pairing_token']
        agent=self.app.test_client()
        headers={'Authorization':'Bearer '+token}
        agent.post('/api/print-agent/poll',json={'printers':['USB Receipt']},headers=headers)
        self.call('/receipt-printer',{'printer_name':'USB Receipt','paper_width_mm':58,'enabled':True},'PUT')
        self.call('/checkout',self.checkout_body(self.ticket()))
        job=agent.post('/api/print-agent/poll',json={'printers':['USB Receipt']},headers=headers).json['job']
        self.call('/receipt-printer',{},'DELETE',expected=409)
        self.assertIsNotNone(self.client.get('/api/receipt-printer').json['printer'])
        self.call('/receipt-printer/jobs/'+str(job['receipt_print_job_id'])+'/resolve',
                  {'reason':'Checked Windows printer queue'})
        self.assertEqual(self.call('/receipt-printer',{},'DELETE').json['cancelled_jobs'],0)

    def test_printer_settings_shows_pending_job_older_than_recent_history(self):
        sid=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        terminal_id=self.client.get('/api/state').json['terminal']['terminal_id']
        user_id=self.client.get('/api/state').json['user']['user_id']
        connection=connect(self.database)
        try:
            for status in ['queued']+['submitted']*16:
                connection.execute('''INSERT INTO receipt_print_jobs(sale_id,terminal_id,job_kind,printer_name,
                    paper_width_mm,status,requested_by_user_id,created_at) VALUES(?,?,'copy','Test printer',80,?,?,?)''',
                    (sid,terminal_id,status,user_id,'2026-10-19T00:00:00+00:00'))
        finally:connection.close()
        jobs=self.client.get('/api/receipt-printer').json['jobs']
        self.assertEqual(len([j for j in jobs if j['status']=='queued']),1)
        self.assertEqual(len([j for j in jobs if j['status']=='submitted']),15)

    def test_cashier_can_start_saved_print_helper_without_manager_password(self):
        token=self.call('/receipt-printer/pair',{}).json['pairing_token']
        config=self.folder/'print-helper.json'
        config.write_text(json.dumps({'url':'http://localhost:8765','token':token,'certificate':''}),encoding='utf-8')
        launched=[]
        self.app.config['PRINT_HELPER_CONFIG']=str(config)
        self.app.config['PRINT_HELPER_LAUNCHER']=lambda path:launched.append(path)
        db=connect(self.database)
        try:db.execute("UPDATE users SET role='cashier' WHERE username='owner'")
        finally:db.close()
        response=self.call('/receipt-printer/start-helper',{})
        self.assertEqual(response.json['status'],'starting')
        self.assertEqual(launched,[config.resolve()])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events WHERE action='printer.helper_started'"),1)

    def test_letter_paper_is_saved_and_snapshotted_for_automatic_printing(self):
        token=self.call('/receipt-printer/pair',{}).json['pairing_token']
        agent=self.app.test_client()
        agent.post('/api/print-agent/poll',json={'printers':['Office Laser']},headers={'Authorization':'Bearer '+token})
        self.call('/receipt-printer',{'printer_name':'Office Laser','paper_size':'letter','enabled':True},'PUT')
        sale=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        job=agent.post('/api/print-agent/poll',json={'printers':['Office Laser']},headers={'Authorization':'Bearer '+token}).json['job']
        self.assertEqual(job['paper_size'],'letter')
        import base64
        image=Image.open(io.BytesIO(base64.b64decode(job['image_base64'])))
        self.assertEqual(image.width,576)  # Letter keeps the 80 mm receipt artwork.
        self.assertEqual(self.scalar(f"SELECT COUNT(*) FROM receipt_print_jobs WHERE sale_id={sale} AND paper_size='letter'"),1)

    def test_print_failure_does_not_make_a_second_sale(self):
        sid=self.call('/checkout',self.checkout_body(self.ticket())).json['sale_id']
        self.call('/sales/'+str(sid)+'/reprint',{})
        self.call('/sales/'+str(sid)+'/reprint',{'reason':'   '})
        self.call('/sales/'+str(sid)+'/reprint',{'reason':'Printer was disconnected'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM payments'),1)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),9)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM receipt_events'),4)
        connection=connect(self.database)
        try:
            copies=connection.execute("SELECT * FROM receipt_events WHERE event_type='reprint' ORDER BY receipt_event_id").fetchall()
            self.assertEqual([r['reason'] for r in copies],['Customer copy','Customer copy','Printer was disconnected'])
            self.assertTrue(all(r['performed_by_user_id']==1 and r['terminal_id'] is not None and r['created_at'] for r in copies))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='receipt.print_requested'").fetchone()[0],3)
        finally:connection.close()

    def test_report_filters_and_csv_formula_safety(self):
        c=self.call('/categories',{'name':'=UNSAFE()'}).json['category_id']
        self.call('/products/'+str(self.product),{'sku':'TEST-01','description':'Test product','category_id':c,'unit':'pc','amount_minor':12550,'reason':'Category','active':True,'manager_password':PASSWORD},'PUT')
        self.call('/checkout',self.checkout_body(self.ticket()))
        self.assertEqual(self.client.get('/api/reports?category_id='+str(self.category)).json['summary']['transactions'],0)
        csv=self.client.get('/api/reports?format=csv').get_data(as_text=True)
        self.assertIn("'=UNSAFE()",csv)
        response=self.client.get('/api/reports?format=xlsx&category_id='+str(c))
        self.assertIn('SQI-POS-Event-001-(2026-10-19-to-2026-10-19).xlsx',response.headers['Content-Disposition'])
        workbook=load_workbook(io.BytesIO(response.data))
        try:
            self.assertEqual(workbook['Category']['A8'].value,"'=UNSAFE()")
            self.assertEqual(workbook['Category']['A8'].data_type,'s')
            self.assertIn('Category: =UNSAFE()',workbook['Summary']['B5'].value)
        finally:workbook.close()
        self.assertEqual(self.client.get('/api/reports?format=xlsx&from=2026-10-20&to=2026-10-19').status_code,400)
        self.assertEqual(self.client.get('/api/reports?format=xlsx&from=20261019').status_code,400)
        empty=self.client.get('/api/reports?format=xlsx&from=2026-11-01&to=2026-11-02')
        empty_book=load_workbook(io.BytesIO(empty.data),data_only=True)
        try:
            self.assertEqual(empty_book['Summary']['B15'].value,0)
            self.assertEqual(empty_book['Days']['A8'].value,'No matching sales or refunds.')
        finally:empty_book.close()

    def test_near_duplicate_requires_a_separate_purchase_review(self):
        self.call('/checkout',self.checkout_body(self.ticket()))
        next_ticket=self.ticket()
        self.assertIsNotNone(next_ticket['duplicate_warning'])
        body=self.checkout_body(next_ticket,key='different-purchase-002')
        self.call('/checkout',body,expected=409)
        self.call('/checkout',{**body,'duplicate_reviewed':True})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),2)

    def test_background_state_poll_does_not_extend_idle_session(self):
        db=connect(self.database)
        try:db.execute('UPDATE auth_sessions SET last_seen_at=last_seen_at-90')
        finally:db.close()
        before=self.scalar('SELECT last_seen_at FROM auth_sessions')
        self.client.get('/api/state')
        self.assertEqual(self.scalar('SELECT last_seen_at FROM auth_sessions'),before)
        self.assertEqual(self.client.get('/api/catalog?background=1').status_code,200)
        self.assertEqual(self.scalar('SELECT last_seen_at FROM auth_sessions'),before)
        self.assertEqual(self.client.get('/api/state',headers={'Host':'attacker.example'}).status_code,400)

    def test_session_revoked_after_request_start_blocks_checkout(self):
        body=self.checkout_body(self.ticket())
        from flask import request
        def revoke_after_initial_auth():
            if request.path=='/api/checkout':
                connection=connect(self.database)
                try:connection.execute('DELETE FROM auth_sessions')
                finally:connection.close()
        self.app.before_request_funcs[None].append(revoke_after_initial_auth)
        self.call('/checkout',body,expected=403)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),0)

    def test_instance_cookies_are_isolated_and_secure_on_https(self):
        other=create_app(self.folder/'other'/'pos.sqlite3',self.folder/'other-backups',testing=True)
        self.assertNotEqual(self.app.config['POS_COOKIE_NAMES'],other.config['POS_COOKIE_NAMES'])
        secure_app=create_app(self.database,self.folder/'backups',testing=True,secure=True)
        self.assertEqual(secure_app.config['POS_COOKIE_NAMES'],self.app.config['POS_COOKIE_NAMES'])
        response=secure_app.test_client().get('/api/state',base_url='https://localhost')
        cookie=response.headers['Set-Cookie']
        self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)

    def test_manager_recovery_closes_other_shift_with_reviewed_unpaid_order(self):
        second,csrf,_=self.second_cashier()
        ticket=self.ticket(client=second,csrf=csrf)
        target=second.get('/api/state').json['shift']['shift_id']
        data={'manager_password':PASSWORD,'counted_cash_minor':50000,'reason':'Laptop unavailable; drawer counted'}
        self.call('/shifts/'+str(target)+'/close',data,expected=409)
        self.call('/shifts/'+str(target)+'/close',{**data,'cancel_open_order':True,'purchase_ticket_id':ticket['purchase_ticket_id'],'ticket_version':ticket['version']})
        self.assertIsNone(second.get('/api/state').json['shift'])
        self.call('/checkout',self.checkout_body(ticket),client=second,csrf=csrf,expected=409)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events WHERE action='shift.closed_by_manager'"),1)
        event=next(a for a in self.client.get('/api/audit').json['events'] if a['action']=='shift.closed_by_manager')
        self.assertEqual(event['subject_display_name'],'Second cashier')
        self.assertEqual(event['reason'],data['reason'])

    def test_shift_history_pages_and_open_shifts_are_separate(self):
        for _ in range(3):
            self.call('/shifts/close',{'counted_cash_minor':100000})
            self.call('/shifts/open',{'opening_cash_minor':100000})
        open_data=self.client.get('/api/shifts?status=open').json
        first=self.client.get('/api/shifts?status=closed&page=1&page_size=2').json
        second=self.client.get('/api/shifts?status=closed&page=2&page_size=2').json
        self.assertEqual(open_data['total'],1)
        self.assertEqual(len(open_data['shifts']),1)
        self.assertEqual(first['total'],3)
        self.assertEqual([s['shift_id'] for s in first['shifts']],[3,2])
        self.assertEqual([s['shift_id'] for s in second['shifts']],[1])
        self.assertEqual(self.client.get('/api/shifts?status=closed&page=0').status_code,400)

    def test_verified_restore_to_new_directory_keeps_live_data(self):
        token=self.call('/receipt-printer/pair',{}).json['pairing_token']
        self.client.post('/api/print-agent/poll',json={'printers':['USB Receipt']},headers={'Authorization':'Bearer '+token})
        self.call('/receipt-printer',{'printer_name':'USB Receipt','paper_width_mm':58,'enabled':True},'PUT')
        self.call('/checkout',self.checkout_body(self.ticket()))
        self.call('/backups',{'manager_password':PASSWORD})
        backup=next((self.folder/'backups').glob('*.sqlite3'))
        output=self.folder/'restored'
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parent.parent/'tools'/'restore.py'),str(backup),'--output',str(output)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales'),1)
        restored=create_app(output/'pos.sqlite3',self.folder/'restored-backups',testing=True)
        self.assertEqual(restored.config['POS_COOKIE_NAMES'],self.app.config['POS_COOKIE_NAMES'])
        self.assertFalse(restored.test_client().get('/api/state').json['setup_required'])
        connection=connect(output/'pos.sqlite3')
        try:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM sales').fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM auth_sessions').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM receipt_printers').fetchone()[0],0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM receipt_print_jobs WHERE status='failed'").fetchone()[0],1)
            self.assertEqual(self.scalar("SELECT COUNT(*) FROM receipt_print_jobs WHERE status='queued'"),1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='backup.restored'").fetchone()[0],1)
        finally:connection.close()
        recovered_client=restored.test_client()
        for name in self.app.config['POS_COOKIE_NAMES']:
            recovered_client.set_cookie(name,self.client.get_cookie(name).value)
        recovered_csrf=recovered_client.get('/api/state').json['csrf']
        login=recovered_client.post('/api/login',json={'username':'owner','password':PASSWORD},headers={'X-CSRF-Token':recovered_csrf})
        self.assertEqual(login.status_code,200,login.get_data(as_text=True))
        self.assertEqual(recovered_client.get('/api/state').json['user']['username'],'owner')


if __name__=='__main__':unittest.main()
