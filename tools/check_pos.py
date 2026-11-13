"""Check the local POS endpoint without relying on Windows certificate stores."""
import argparse
import http.client
import json
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pos.build import build_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cert', help='Trusted POS certificate for HTTPS mode')
    parser.add_argument('--check-build', action='store_true', help='Compare the running server with files on this laptop')
    args = parser.parse_args()
    try:
        if args.cert:
            context = ssl.create_default_context(cafile=args.cert)
            connection = http.client.HTTPSConnection('127.0.0.1', 8765, timeout=3, context=context)
        else:
            connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=3)
        try:
            connection.request('GET', '/api/server-info' if args.check_build else '/api/state',
                               headers={'Connection': 'close'})
            response = connection.getresponse()
            if args.check_build and response.status == 404:
                return 2  # Older POS versions have no build endpoint.
            state = json.load(response)
            if args.check_build:
                if response.status != 200 or not isinstance(state, dict) or 'build' not in state:
                    return 1
                return 0 if state['build'] == build_id() else 2
            return 0 if response.status == 200 and isinstance(state, dict) and 'setup_required' in state else 1
        finally:
            connection.close()
    except (OSError, ValueError, json.JSONDecodeError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
