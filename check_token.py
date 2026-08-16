#!/usr/bin/env python3
"""
check_token.py — Check (and optionally change) the bot token inside the
sirzipp .so.

The token lives in the zlib-compressed constant table at chunk 14.
Expected format: <10-digit bot id>:AAG<35-char secret>  (46 chars total)

Usage (Termux / Replit):
    python3 check_token.py sirzipp.cpython-311-x86_64-linux-gnu.so

Output: prints the embedded token and its validity.
Optional change:
    python3 check_token.py file.so --change 8960099014:NEW-TOKEN-HERE
    (new token must be exactly 46 chars; output file = ..._token.so)

Extra (requires internet):
    python3 check_token.py file.so --verify
        Tests the embedded token against the Telegram API (getMe)
        to confirm it is a live, working token.

Python 3 only (zlib built-in, urllib for --verify).
"""
import sys
import zlib
import re
import urllib.request
import json

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548

TOKEN_RE = re.compile(r'^\d{10}:A[A-Za-z0-9_-]{34}$')


def compress_fit(table):
    for wbits in (13, 12, 14, 15):
        co = zlib.compressobj(9, zlib.DEFLATED, wbits)
        cand = co.compress(table) + co.flush()
        if len(cand) <= ZLIB_LEN:
            return cand
    for level in range(9, 0, -1):
        cand = zlib.compress(table, level)
        if len(cand) <= ZLIB_LEN:
            return cand
    comp = zlib.compress(table)
    print(f'WARNING: recompressed size {len(comp)} exceeds {ZLIB_LEN}; writing anyway.')
    return comp


def load_table(so_path):
    data = open(so_path, 'rb').read()
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)
    try:
        return zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN])
    except zlib.error as e:
        print(f'ERROR: cannot decompress the string table ({e}).')
        sys.exit(3)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    so_path = sys.argv[1]
    data = open(so_path, 'rb').read()
    table = load_table(so_path)

    token = table[0x71:0x9f].decode('utf-8', 'replace')   # chunk 14, 46 bytes
    print(f'Embedded token: {token}')
    print(f'Length        : {len(token)} (must be 46)')

    ok = True
    if len(token) != 46:
        print('Status: BAD — length is not 46 characters.')
        ok = False
    elif not TOKEN_RE.match(token):
        print('Status: UNUSUAL — format differs from the standard Telegram token.')
        ok = False
    else:
        print('Status: format looks valid.')

    # --- verify live ---
    if '--verify' in sys.argv:
        url = f'https://api.telegram.org/bot{token}/getMe'
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                resp = json.loads(r.read())
            if resp.get('ok'):
                u = resp['result']
                print(f"API getMe: ok — bot @{u['username']} (id {u['id']})")
            else:
                print(f"API getMe failed: {resp.get('description')}")
                ok = False
        except Exception as e:
            print(f'API check could not run: {e}')
            ok = False

    # --- change ---
    change = None
    if '--change' in sys.argv:
        idx = sys.argv.index('--change')
        if idx + 1 < len(sys.argv):
            change = sys.argv[idx + 1].strip()

    if change:
        if len(change) != 46:
            print(f'ERROR: new token must be exactly 46 chars (got {len(change)}).')
            sys.exit(4)
        if change.encode() == token.encode():
            print('Token unchanged — nothing to do.')
            sys.exit(0)
        old = token.encode()
        if old not in table:
            print('ERROR: current token not found in table — different build?')
            sys.exit(5)
        table = table.replace(old, change.encode(), 1)
        comp = compress_fit(table)
        out = so_path.replace('.so', '_token.so')
        open(out, 'wb').write(data[:ZLIB_OFF] + comp + b'\x00' * (ZLIB_LEN - len(comp))
                              + data[ZLIB_OFF + ZLIB_LEN:])
        print(f'Token changed. Saved: {out}')
        print('Copy it over to run: cp', out, so_path)
    elif not ok:
        print()
        print('To fix it, run:')
        print(f'  python3 {sys.argv[0]} {so_path} --change <46-char-token>')

if __name__ == '__main__':
    main()
