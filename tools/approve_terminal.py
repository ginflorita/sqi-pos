"""Approve a replacement host browser after recovery, using an existing manager password."""
import argparse
import getpass
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import pos
from werkzeug.security import check_password_hash
from pos.db import audit,connect,transaction


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--terminal-id',type=int)
    parser.add_argument('--username',help='Existing active manager username')
    parser.add_argument('--reason',default='Host recovery: replacement browser approval')
    args=parser.parse_args()
    path=args.data_dir.resolve()/'pos.sqlite3'
    if not path.is_file():
        parser.error('No database exists in that folder.')
    connection=connect(path)
    try:
        if args.terminal_id is None:
            rows=connection.execute('SELECT terminal_id,name,approved FROM terminals ORDER BY terminal_id').fetchall()
            for row in rows:
                print(f'{row["terminal_id"]}: {row["name"]} ({"approved" if row["approved"] else "pending"})')
            print('To approve a pending replacement browser, rerun with --terminal-id and --username.')
            return
        if not args.username or not args.reason.strip():
            parser.error('An existing manager --username and nonempty reason are required.')
        password=getpass.getpass('Existing manager password: ')
        with transaction(connection):
            user=connection.execute("SELECT * FROM users WHERE username=? AND active=1 AND role='manager'",(args.username,)).fetchone()
            if not user or not check_password_hash(user['password_hash'],password):
                parser.error('The manager credentials are incorrect.')
            terminal=connection.execute('SELECT * FROM terminals WHERE terminal_id=?',(args.terminal_id,)).fetchone()
            if not terminal or terminal['approved']:
                parser.error('Choose a pending terminal from the list.')
            print(f'Approve terminal {terminal["terminal_id"]}: {terminal["name"]}')
            if input('Type APPROVE to confirm: ').strip()!='APPROVE':
                print('No change made.');return
            connection.execute('UPDATE terminals SET approved=1,approved_by_user_id=? WHERE terminal_id=?',(user['user_id'],args.terminal_id))
            audit(connection,'terminal.recovery_approved','terminals',args.terminal_id,actor=user['user_id'],
                  terminal=args.terminal_id,reason=args.reason.strip(),approved=user['user_id'])
        print('Laptop approved. Restart the host server and sign in again.')
    finally:
        connection.close()


if __name__=='__main__':main()
