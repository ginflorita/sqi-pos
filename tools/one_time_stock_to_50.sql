-- One-time administrative stock reconciliation. Run only after a verified backup.
-- This records the change for every product and restores the receipts-only guard.
-- It intentionally bypasses the normal rule against manual stock resets for this transaction.
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;

CREATE TEMP TABLE _target_stock AS
SELECT product_id, quantity_on_hand AS previous_quantity,
       50 - quantity_on_hand AS quantity_change
FROM stock_balances
WHERE quantity_on_hand <> 50;

CREATE TEMP TABLE _stock_run_key (value TEXT PRIMARY KEY);
INSERT INTO _stock_run_key VALUES ('one-time-stock-50-' || lower(hex(randomblob(16))));

CREATE TEMP TABLE _stock_guard (ok INTEGER CHECK(ok=1));
INSERT INTO _stock_guard
SELECT CASE WHEN
  (SELECT COUNT(*) FROM users WHERE role='manager' AND active=1)=1 AND
  (SELECT COUNT(*) FROM bazaars WHERE status='active')=1 AND
  (SELECT COUNT(*) FROM bazaar_days WHERE status='open')=1
THEN 1 ELSE 0 END;

DROP TRIGGER stock_documents_receipts_only;

INSERT INTO stock_documents
 (bazaar_id,bazaar_day_id,document_type,reference_no,reason,request_key,status,
  created_by_user_id,approved_by_user_id,created_at,approved_at)
SELECT b.bazaar_id,d.bazaar_day_id,'adjustment','One-time target 50',
       'One-time stock reconciliation to 50 pcs per product',r.value,'posted',
       u.user_id,u.user_id,
       strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM bazaars b CROSS JOIN bazaar_days d CROSS JOIN users u CROSS JOIN _stock_run_key r
WHERE b.status='active' AND d.status='open' AND u.role='manager' AND u.active=1
  AND EXISTS(SELECT 1 FROM _target_stock);

CREATE TEMP TABLE _stock_run_doc AS
SELECT stock_document_id FROM stock_documents
WHERE request_key=(SELECT value FROM _stock_run_key);

INSERT INTO stock_document_lines
 (stock_document_id,product_id,quantity_change,expected_quantity,counted_quantity)
SELECT doc.stock_document_id,t.product_id,t.quantity_change,t.previous_quantity,50
FROM _target_stock t CROSS JOIN _stock_run_doc doc;

INSERT INTO stock_movements
 (bazaar_id,bazaar_day_id,product_id,quantity_change,stock_document_line_id,
  created_by_user_id,created_at)
SELECT doc.bazaar_id,doc.bazaar_day_id,line.product_id,line.quantity_change,
       line.stock_document_line_id,doc.created_by_user_id,
       strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM stock_document_lines line
JOIN _stock_run_doc run ON run.stock_document_id=line.stock_document_id
JOIN stock_documents doc ON doc.stock_document_id=run.stock_document_id;

INSERT INTO audit_events
 (bazaar_day_id,actor_user_id,action,entity_type,entity_key,before_json,after_json,
  reason,approved_by_user_id,created_at)
SELECT doc.bazaar_day_id,doc.created_by_user_id,'stock.one_time_reconciled',
       'stock_documents',CAST(doc.stock_document_id AS TEXT),
       json_object('changed_products',(SELECT COUNT(*) FROM _target_stock),
                   'previous_total',(SELECT SUM(previous_quantity) FROM _target_stock)),
       json_object('target_quantity',50,
                   'changed_products',(SELECT COUNT(*) FROM _target_stock),
                   'decreased_products',(SELECT COUNT(*) FROM _target_stock WHERE quantity_change<0)),
       doc.reason,doc.approved_by_user_id,strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM stock_documents doc JOIN _stock_run_doc run USING(stock_document_id);

CREATE TRIGGER stock_documents_receipts_only BEFORE INSERT ON stock_documents
WHEN NEW.document_type NOT IN ('opening','in')
BEGIN SELECT RAISE(ABORT,'Only opening stock and receipts can be posted'); END;

INSERT INTO _stock_guard
SELECT CASE WHEN
  (SELECT COUNT(*) FROM stock_balances WHERE quantity_on_hand<>50)=0 AND
  (SELECT COUNT(*) FROM stock_movements m
   JOIN stock_document_lines line USING(stock_document_line_id)
   JOIN _stock_run_doc run ON run.stock_document_id=line.stock_document_id)
   =(SELECT COUNT(*) FROM _target_stock) AND
  EXISTS(SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='stock_documents_receipts_only')
THEN 1 ELSE 0 END;

DROP TABLE _stock_run_doc;
DROP TABLE _stock_run_key;
DROP TABLE _target_stock;
DROP TABLE _stock_guard;
COMMIT;
