"""Check the local POS endpoint without relying on Windows certificate stores."""
import argparse
import http.client
import json
import ssl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cert', help='Trusted POS certificate for HTTPS mode')
    args = parser.parse_args()
    try:
        if args.cert:
            context = ssl.create_default_context(cafile=args.cert)
            connection = http.client.HTTPSConnection('127.0.0.1', 8765, timeout=3, context=context)
        else:
            connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=3)
        try:
            connection.request('GET', '/api/state', headers={'Connection': 'close'})
            response = connection.getresponse()
            state = json.load(response)
            return 0 if response.status == 200 and isinstance(state, dict) and 'setup_required' in state else 1
        finally:
            connection.close()
    except (OSError, ValueError, json.JSONDecodeError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
