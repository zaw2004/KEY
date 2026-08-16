#!/usr/bin/env python3
"""
check_all.py — Check EVERYTHING in the sirzipp .so in one run:
  1. ADMIN_IDS   (machine-code constant at offset 0x9b32)
  2. Embedded ID (zlib table chunk 13 — the license "Your key" value)
  3. BOT_TOKEN   (zlib table chunk 14)
  4. (optional) Telegram API getMe verification of the embedded token
  5. Username (KENOBEE) occurrences in the string table

Usage (Termux / Replit):
    python3 check_all.py sirzipp.cpython-311-x86_64-linux-gnu.so
    python3 check_all.py sirzipp.cpython-311-x86_64-linux-gnu.so --verify
Python 3 only (zlib built-in, urllib for --verify).
"""
import sys
import zlib
import struct
import urllib.request
import json

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548
ADMIN_OFF = 0x9b32
OLD_TOKEN = b'8960099014:AAGTdr-eMULHi5RNUgWDQf9eH71bq5jRi5w'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    so_path = sys.argv[1]
    data = open(so_path, 'rb').read()
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)

    try:
        table = zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN])
    except zlib.error as e:
        print(f'ERROR: cannot decompress the string table ({e}).')
        sys.exit(3)

    admin = struct.unpack('<q', data[ADMIN_OFF:ADMIN_OFF + 8])[0]
    embedded_id = table[0x67:0x71]
    token = table[0x71:0x9f]

    print('=== sirzipp .so check ===')
    print(f'ADMIN_IDS      : {admin}')
    print(f'Embedded ID    : {embedded_id.decode("utf-8", "replace")}')
    print(f'Embedded token : {token.decode("utf-8", "replace")}')

    # status
    issues = []
    if not embedded_id.isdigit() or len(embedded_id) != 10:
        issues.append('embedded ID is not a valid 10-digit number')
    if len(token) != 46:
        issues.append(f'token length is {len(token)} (must be 46)')
    print('KENOBEE in table :', table.count(b'KENOBEE'), 'occurrences')

    if '--verify' in sys.argv:
        url = f'https://api.telegram.org/bot{token.decode()}/getMe'
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                resp = json.loads(r.read())
            if resp.get('ok'):
                u = resp['result']
                print(f"Telegram API getMe : ok — @{u['username']} (id {u['id']})")
            else:
                print(f'Telegram API getMe : FAILED — {resp.get("description")}')
                issues.append('token rejected by Telegram API')
        except Exception as e:
            print(f'Telegram API check could not run: {e}')
            issues.append('token API check could not run')

    print()
    if issues:
        print('ISSUES FOUND:')
        for i in issues:
            print('  -', i)
    else:
        print('STATUS: all values look valid.')

if __name__ == '__main__':
    main()
