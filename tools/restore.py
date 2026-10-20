"""Verify a backup and restore into a NEW directory, leaving the live database alone."""
import argparse
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pos.db import audit, connect, initialize, transaction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.backup.is_file() or args.output.exists():
        parser.error('Choose an existing backup and a new output directory that does not exist.')
    with sqlite3.connect(args.backup.resolve().as_uri()+'?mode=ro', uri=True) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or source.execute('PRAGMA foreign_key_check').fetchone():
            parser.error('Backup integrity verification failed.')
        if source.execute('PRAGMA user_version').fetchone()[0] != 1:
            parser.error('This backup needs a different application version.')
    with args.backup.open('rb') as stream:
        checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    args.output.mkdir(parents=True)
    destination=args.output/'pos.sqlite3'
    shutil.copyfile(args.backup,destination)
    initialize(destination)
    connection=connect(destination)
    try:
        with transaction(connection):
            connection.execute('DELETE FROM auth_sessions')
            connection.execute("UPDATE backup_runs SET status='failed',error_message='Snapshot restored; previous in-progress run is no longer active' WHERE status='running'")
            audit(connection,'backup.restored','system',after={'backup':args.backup.name,'sha256':checksum})
    finally:
        connection.close()
    print(f'Verified restore: {destination.resolve()}')
    print(f'Original backup SHA256: {checksum}')
    print('The original live database was not changed. Start the server with --data-dir pointing to this directory.')


if __name__=='__main__':
    main()
