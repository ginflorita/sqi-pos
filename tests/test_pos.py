import io
import json
import sqlite3
import subprocess
import sys
import shutil
import uuid
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from pos.app import create_app
from pos.db import connect

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

    def second_cashier(self):
        uid=self.call('/users',{'username':'cashier2','display_name':'Second cashier','role':'cashier','active':True,'password':PASSWORD,'manager_password':PASSWORD}).json['user_id']
        second=self.app.test_client();csrf=second.get('/api/state').json['csrf']
        self.call('/login',{'username':'cashier2','password':PASSWORD,'terminal_name':'Laptop 2'},client=second,csrf=csrf)
        self.assertFalse(second.get('/api/state').json['terminal']['approved'])
        team=self.client.get('/api/team').json
        terminal=team['terminals'][-1]
        self.call('/terminals/'+str(terminal['terminal_id']),{'name':'Laptop 2','approved':True,'manager_password':PASSWORD},'PUT')
        self.call('/shifts/open',{'opening_cash_minor':50000},client=second,csrf=csrf)
        return second,csrf,uid

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
        self.call('/stock',{'document_type':'count','request_key':'stock-count-request-01','reference_no':'COUNT','reason':'One remains','manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':1}]})
        second,csrf,_=self.second_cashier()
        a=self.checkout_body(self.ticket(),key='cashier-one-checkout')
        b=self.checkout_body(self.ticket(client=second,csrf=csrf),key='cashier-two-checkout')
        barrier=threading.Barrier(2)
        def submit(args):
            c,token,body=args;barrier.wait()
            return self.call('/checkout',body,client=c,csrf=token,expected=None).status_code
        with ThreadPoolExecutor(2) as pool:statuses=list(pool.map(submit,[(self.client,self.csrf,a),(second,csrf,b)]))
        self.assertEqual(sorted(statuses),[200,409])
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),0)
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

    def test_stock_removals_counts_and_adjustments_still_need_reason(self):
        for kind in ('out','count','adjustment'):
            with self.subTest(kind=kind):
                data={'document_type':kind,'request_key':'stock-reason-required-'+kind,'manager_password':PASSWORD,'lines':[{'product_id':self.product,'quantity':1}]}
                self.call('/stock',data,expected=400)
                self.call('/stock',{**data,'reason':'   '},expected=400)
        self.assertEqual(self.scalar('SELECT quantity_on_hand FROM stock_balances'),10)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM stock_documents'),1)

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
        for _ in range(5):self.call('/login',{'username':'cashier2','password':'wrong','terminal_name':'Other'},client=second,csrf=csrf,expected=401)
        self.call('/login',{'username':'cashier2','password':PASSWORD,'terminal_name':'Other'},client=second,csrf=csrf,expected=429)
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
        login=recovered_client.post('/api/login',json={'username':'owner','password':PASSWORD,'terminal_name':'Recovered host'},headers={'X-CSRF-Token':recovered_csrf})
        self.assertEqual(login.status_code,200,login.get_data(as_text=True))
        self.assertTrue(recovered_client.get('/api/state').json['terminal']['approved'])


if __name__=='__main__':unittest.main()
