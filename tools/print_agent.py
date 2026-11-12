"""Run on EACH Windows cashier laptop. Pulls only its paired terminal's jobs."""
import argparse
import base64
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def remove_temporary_receipt(path):
    """Best-effort cleanup; a brief Windows/spooler lock must not fail a print."""
    for _ in range(10):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.2)


def powershell(*args):
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                             '-File',str(ROOT/'tools/print_windows.ps1'),*args],
                            capture_output=True, text=True, encoding='utf-8', timeout=90,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Windows printing failed')[-300:])
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description='SQI receipt print helper (one per laptop)')
    parser.add_argument('--config',type=Path,default=ROOT/'.print-helper/config.json')
    parser.add_argument('--setup',action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('The receipt print helper requires Windows.')
    # Hold this lock for the process lifetime. Repeated cashier clicks then
    # cannot create helpers that compete for the same print job.
    import msvcrt
    args.config.parent.mkdir(parents=True, exist_ok=True)
    lock = (args.config.parent / 'agent.lock').open('a+b')
    if lock.seek(0, 2) == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print('SQI print helper is already running.')
        return
    if args.setup or not args.config.exists():
        url = input('POS address (same address used in this laptop browser): ').strip().rstrip('/')
        parts = urlsplit(url)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
            parser.error('Use the POS origin, for example https://192.168.1.10:8765')
        if parts.scheme == 'http' and parts.hostname not in ('localhost','127.0.0.1'):
            parser.error('LAN connections require HTTPS.')
        token = input('Pairing code from Settings on THIS laptop: ').strip()
        if len(token) != 43:
            parser.error('The pairing code is not valid.')
        certificate = input('Trusted POS certificate file (Enter for Windows trust store): ').strip().strip('"')
        if certificate:
            ssl.create_default_context(cafile=certificate)  # Verify before persisting.
        args.config.parent.mkdir(parents=True,exist_ok=True)
        args.config.write_text(json.dumps({'url':url,'token':token,'certificate':certificate}),encoding='utf-8')
    config = json.loads(args.config.read_text(encoding='utf-8'))
    context = ssl.create_default_context(cafile=config.get('certificate') or None)
    def call(path,body):
        req = Request(config['url']+'/api/print-agent/'+path,data=json.dumps(body).encode(),
                      headers={'Content-Type':'application/json','Authorization':'Bearer '+config['token']})
        with urlopen(req,context=context,timeout=20) as response:
            return json.load(response)
    printers = []
    refresh = 0
    print('SQI print helper running. Keep this open while selling. Ctrl+C stops it.')
    result = None
    while True:
        try:
            # Retry acknowledgements only. Never resubmit a physical print after an uncertain response.
            if result:
                call('result',result)
                result = None
            if time.monotonic() >= refresh:
                value = json.loads(powershell('-Mode','list') or '[]')
                printers = value if isinstance(value,list) else [value]
                refresh = time.monotonic()+30
            job = call('poll',{'printers':printers})['job']
            if job:
                result = {'receipt_print_job_id':job['receipt_print_job_id'],'status':'submitted','error_message':''}
                try:
                    if job['printer_name'] not in printers:
                        raise RuntimeError('Saved printer is not installed. Check printer settings.')
                    handle, filename = tempfile.mkstemp(prefix='sqi-receipt-', suffix='.png')
                    os.close(handle)
                    image = Path(filename)
                    try:
                        image.write_bytes(base64.b64decode(job['image_base64'],validate=True))
                        paper_size = job.get('paper_size') or ('roll_58' if job['paper_width_mm'] == 58 else 'roll_80')
                        powershell('-Mode','print','-Printer',job['printer_name'],'-ImagePath',str(image),'-PaperSize',paper_size)
                    finally:
                        remove_temporary_receipt(image)
                    print('Receipt sent to Windows printer queue.')
                except Exception as error:
                    result.update(status='failed',error_message=('Check printer before making a copy: '+str(error))[:300])
                    print(result['error_message'])
        except KeyboardInterrupt:
            break
        except HTTPError as error:
            if error.code == 403:
                print('Printer pairing revoked. Pair this laptop again in POS Settings to reconnect.')
                break
            print('Print helper waiting for connection:', str(error)[:160])
        except Exception as error:
            print('Print helper waiting for connection:', str(error)[:160])
        time.sleep(2)


if __name__ == '__main__':
    main()
