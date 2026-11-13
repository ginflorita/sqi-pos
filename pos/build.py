"""Identity of application files loaded by a POS server process."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ('pos', 'static', 'templates')
SOURCE_SUFFIXES = {'.py', '.sql', '.js', '.css', '.html'}


def build_id():
    digest = hashlib.sha256()
    files = [ROOT / 'run.py']
    for directory in SOURCE_DIRS:
        files.extend(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and path.suffix in SOURCE_SUFFIXES)
    for path in sorted(files, key=lambda item: item.relative_to(ROOT).as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()
