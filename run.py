"""Run the local POS. HTTP is restricted to loopback; LAN access requires TLS."""
import argparse
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.vendor'))

from pos.app import create_app


def main():
    parser = argparse.ArgumentParser(description='SQI POS local server')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--lan', action='store_true', help='Listen on the local network (requires certificate and key)')
    parser.add_argument('--cert', type=Path)
    parser.add_argument('--key', type=Path)
    args = parser.parse_args()
    if args.lan and not (args.cert and args.key):
        parser.error('LAN access requires --cert and --key. Run tools/certificate.py first.')
    if bool(args.cert) != bool(args.key):
        parser.error('Supply both --cert and --key.')
    try:
        from cheroot.wsgi import Server
        from cheroot.ssl.builtin import BuiltinSSLAdapter
    except ImportError:
        parser.error('Missing server dependency. Run Install-POS.cmd first.')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    tls = bool(args.cert)
    app = create_app(args.data_dir.resolve() / 'pos.sqlite3', args.backup_dir, secure=tls)
    server = Server(('0.0.0.0' if args.lan else '127.0.0.1', args.port), app, numthreads=16, request_queue_size=30, timeout=15)
    server.keep_alive_conn_limit = 0
    if tls:
        server.ssl_adapter = BuiltinSSLAdapter(str(args.cert.resolve()), str(args.key.resolve()))
    stopped = threading.Event()

    def scheduled_backup():
        while not stopped.wait(900):
            app.perform_backup()

    worker = threading.Thread(target=scheduled_backup, daemon=True, name='pos-backups')
    worker.start()
    scheme = 'https' if tls else 'http'
    print(f'\nSQI POS: {scheme}://localhost:{args.port}')
    print(f'Database: {args.data_dir.resolve() / "pos.sqlite3"}')
    print('Keep this server running while either laptop is selling. Ctrl+C stops it.\n')
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.stop()


if __name__ == '__main__':
    main()
