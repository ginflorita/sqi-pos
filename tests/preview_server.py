"""Development-only browser check against .demo; can lose one successful payment response."""
import argparse
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from pos.app import create_app
from flask import jsonify,request
from cheroot.wsgi import Server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--lose-checkout-response',action='store_true')
    args=parser.parse_args()
    database=ROOT/'.demo'/'pos.sqlite3'
    if not database.exists():parser.error('Run python tools/demo.py first.')
    app=create_app(database,ROOT/'.demo'/'backups')
    lock=threading.Lock()
    remaining=args.lose_checkout_response

    @app.after_request
    def simulate_lost_response(response):
        nonlocal remaining
        with lock:
            if remaining and request.path=='/api/checkout' and request.method=='POST' and response.status_code==200:
                remaining=False
                print('Browser test: payment committed; successful response replaced with HTTP 503.',flush=True)
                response=jsonify(error='Simulated connection failure after payment. Refresh the counter to recover the saved receipt.')
                response.status_code=503
        return response

    server=Server(('127.0.0.1',args.port),app,numthreads=4)
    print(f'DEMO browser test only: http://localhost:{args.port}',flush=True)
    try:server.start()
    except KeyboardInterrupt:pass
    finally:server.stop()


if __name__=='__main__':main()
