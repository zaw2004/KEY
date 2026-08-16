#!/usr/bin/env python3
"""
patch_token.py — Change ONLY the bot token inside the sirzipp .so.

The token lives in the zlib-compressed constant table at chunk 14.
It MUST be exactly 46 characters long and match the standard format:
    <10-digit bot id>:AAG<33-char token>
(use "Enter" for Enter — the script checks the format automatically)

Usage (Termux / Replit):
    python3 patch_token.py sirzipp.cpython-311-x86_64-linux-gnu.so

Output: sirzipp..._token.so
Python 3 only (zlib built-in, no other dependencies).
"""
import sys
import zlib
import re

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548

OLD_TOKEN = b'8960099014:AAGTdr-eMULHi5RNUgWDQf9eH71bq5jRi5w'  # 46 bytes

TOKEN_RE = re.compile(r'^\d{10}:A[A-Za-z0-9_-]{35}$')


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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    so_path = sys.argv[1]
    data = open(so_path, 'rb').read()
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)

    table = zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN])

    if OLD_TOKEN not in table:
        print('ERROR: old token not found in the binary.')
        print('Either the token was already changed, or the .so is a different build.')
        sys.exit(3)

    try:
        new_tok = input('New bot token (46 chars): ').strip()
    except EOFError:
        print('Usage: python3 patch_token.py file.so < token.txt')
        sys.exit(1)

    if not new_tok:
        print('Nothing to patch. Exiting.')
        sys.exit(0)

    if len(new_tok) != 46:
        print(f'ERROR: token must be exactly 46 characters (yours: {len(new_tok)}).')
        print('Copy the token EXACTLY from BotFather — include the 10-digit id and colon.')
        sys.exit(4)

    if not TOKEN_RE.match(new_tok):
        print('WARNING: token format looks unusual.')
        print('Expected: 1234567890:AA... (10 digits, colon, AAG or similar)')
        try:
            if input('Continue anyway? (y/n): ').strip().lower() != 'y':
                print('Aborted.')
                sys.exit(0)
        except EOFError:
            sys.exit(1)

    if new_tok.encode() == OLD_TOKEN:
        print('Token unchanged — nothing to do.')
        sys.exit(0)

    table = table.replace(OLD_TOKEN, new_tok.encode(), 1)
    comp = compress_fit(table)

    out = so_path.replace('.so', '_token.so')
    open(out, 'wb').write(data[:ZLIB_OFF] + comp + b'\x00' * (ZLIB_LEN - len(comp))
                          + data[ZLIB_OFF + ZLIB_LEN:])
    print('Saved:', out)
    print('Done. Copy it over the original to run:')
    print('  cp', out, so_path)

if __name__ == '__main__':
    main()
