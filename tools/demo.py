"""Create a separate demonstration workspace; never writes to data/pos.sqlite3."""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw
from pos.app import create_app

ROOT=Path(__file__).resolve().parent.parent
DEMO_PASSWORD='Bazaar-demo-2026!'


def illustration(kind,color):
    image=Image.new('RGB',(600,460),color)
    d=ImageDraw.Draw(image)
    d.ellipse((125,355,475,400),fill='#0000000d' if False else '#d4d2c3')
    if kind=='bag':
        d.rounded_rectangle((165,155,435,375),radius=14,fill='#c6a477')
        d.arc((225,60,375,240),180,360,fill='#9f7c4f',width=16)
        d.rounded_rectangle((185,170,415,360),radius=8,outline='#b59468',width=2)
        d.text((260,257),'BAZAAR',fill='#5f674b',font_size=21)
    elif kind=='cup':
        d.ellipse((365,170,485,310),fill='#b18468')
        d.ellipse((391,195,460,285),fill=color)
        d.rounded_rectangle((155,155,390,350),radius=45,fill='#cda586')
        d.ellipse((155,135,390,198),fill='#e1c6ab')
        d.ellipse((170,147,375,187),fill='#785b44')
        d.arc((170,160,375,335),0,85,fill='#b78b6b',width=3)
    elif kind=='plant':
        d.line((300,265,300,90),fill='#5c7957',width=8)
        for coords in [(207,145,300,225),(300,85,398,170),(220,70,300,140),(299,190,395,255)]:
            d.ellipse(coords,fill='#7d9b65')
        d.polygon([(215,255),(385,255),(355,375),(245,375)],fill='#ba8060')
        d.rounded_rectangle((205,250,395,278),radius=10,fill='#d49b77')
    elif kind=='candle':
        d.rounded_rectangle((192,140,408,365),radius=24,fill='#bb835b')
        d.ellipse((192,120,408,175),fill='#dec1a0')
        d.ellipse((204,130,396,163),fill='#eee4c5')
        d.line((300,149,300,125),fill='#484237',width=4)
        d.rounded_rectangle((224,213,376,305),radius=1,fill='#f2eede')
        d.text((247,236),'SLOW DAYS',fill='#696b53',font_size=18)
        d.text((263,268),'soy wax',fill='#8b8c78',font_size=15)
    else:
        d.rounded_rectangle((200,90,400,370),radius=22,fill='#ddd5b5')
        d.rectangle((200,130,400,150),fill='#bcae87')
        d.text((239,205),'GOOD\nTHINGS',fill='#676a50',font_size=30,spacing=12)
    output=io.BytesIO();image.save(output,'JPEG',quality=90);output.seek(0);return output


def main():
    directory=ROOT/'.demo'
    if (directory/'pos.sqlite3').exists():
        print('Demo already exists; leaving it unchanged.');return
    app=create_app(directory/'pos.sqlite3',directory/'backups',testing=True)
    client=app.test_client();csrf=client.get('/api/state').json['csrf']
    def call(path,data,method='POST'):
        r=client.open('/api'+path,method=method,json=data,headers={'X-CSRF-Token':csrf})
        if r.status_code!=200:raise RuntimeError(r.get_data(as_text=True))
        return r.json
    call('/setup',{'username':'demo','password':DEMO_PASSWORD,'display_name':'Alex Morgan','bazaar_name':'DEMO · The Weekend Market','timezone':'Asia/Manila','currency_code':'PHP'})
    category_ids={name:call('/categories',{'name':name})['category_id'] for name in ['Everyday goods','Home & living','Plants & greens','Little treats']}
    products=[('Natural canvas tote','Everyday goods',35000,'bag','#eee9dd',25),('Sunday ceramic mug','Home & living',28000,'cup','#ece7df',18),('Little desk plant','Plants & greens',18000,'plant','#e7ecdf',14),('Amber soy candle','Home & living',42000,'candle','#eee6da',22),('Everyday notebook','Everyday goods',15000,'book','#e8e9e1',30),('Oat milk mug','Home & living',32000,'cup','#e9e5dc',12),('Pocket canvas bag','Everyday goods',22000,'bag','#e6e9de',16),('Herb garden starter','Plants & greens',12000,'plant','#e7ebdf',8),('Vanilla jar candle','Little treats',26000,'candle','#eee8db',20),('Field notes journal','Everyday goods',19000,'book','#e8e7de',15),('Mini terracotta plant','Plants & greens',9500,'plant','#eae6da',5),('Market carryall','Everyday goods',48000,'bag','#e4e8de',9)]
    pids=[]
    for i,(name,category,price,kind,color,stock) in enumerate(products,1):
        pid=call('/products',{'sku':f'BAZ-{i:03d}','barcode':f'200000{i:06d}','description':name,'category_id':category_ids[category],'unit':'pc','amount_minor':price,'reason':'Demo catalog','active':True,'manager_password':DEMO_PASSWORD})['product_id'];pids.append(pid)
        upload=illustration(kind,color)
        r=client.post('/api/products/'+str(pid)+'/image',data={'manager_password':DEMO_PASSWORD,'image':(upload,'demo.jpg')},headers={'X-CSRF-Token':csrf})
        if r.status_code!=200:raise RuntimeError(r.get_data(as_text=True))
        call('/stock',{'document_type':'opening','request_key':f'demo-opening-stock-{i:03d}','reference_no':'DEMO','reason':'Demo opening stock','manager_password':DEMO_PASSWORD,'lines':[{'product_id':pid,'quantity':stock}]})
    call('/users',{'username':'cashier','display_name':'Jamie Reyes','role':'cashier','active':True,'password':DEMO_PASSWORD,'manager_password':DEMO_PASSWORD})
    call('/days/open',{'business_date':datetime.now().date().isoformat(),'manager_password':DEMO_PASSWORD})
    call('/shifts/open',{'opening_cash_minor':200000})
    for i in range(8):
        t=call('/tickets',{})
        t=call('/tickets/'+str(t['purchase_ticket_id']),{'version':t['version'],'lines':[{'product_id':pids[i%len(pids)],'quantity':1}]},'PUT')
        call('/checkout',{'purchase_ticket_id':t['purchase_ticket_id'],'version':t['version'],'quote_hash':t['quote_hash'],'tendered_minor':100000,'request_key':f'demo-checkout-request-{i:03d}'})
    app.perform_backup()
    print('Demo created in .demo/. No real catalog or sales were changed.')
    print('Start: python run.py --data-dir .demo --backup-dir .demo/backups --port 8766')
    print('Demo login: demo / '+DEMO_PASSWORD)


if __name__=='__main__':main()
