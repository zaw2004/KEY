#!/usr/bin/env python3
"""
patch_embedded.py — Change the embedded system-key ID and bot token inside
the sirzipp .so zlib string table.

Usage (Termux / Replit):
    python3 patch_embedded.py sirzipp.cpython-311-x86_64-linux-gnu.so

The script interactively asks for:
  - new 10-digit embedded ID  (must be exactly 10 digits)
  - new bot token             (must be exactly 46 characters)
Press Enter to skip either one. Output: sirzipp..._embedded.so

Why same length? The embedded values live inside a zlib-compressed constant
table that is decoded by fixed offsets at runtime. Growing/shrinking them
would shift every following constant and break the bot.
"""
import sys
import zlib

SO_PATH = sys.argv[1] if len(sys.argv) > 1 else None
if SO_PATH is None:
    print(__doc__)
    sys.exit(1)

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548

OLD_ID = b'1767590675'                     # 10 bytes  (embedded system key / author ID)
OLD_TOKEN = b'8960099014:AAGTdr-eMULHi5RNUgWDQf9eH71bq5jRi5w'  # 46 bytes

data = open(SO_PATH, 'rb').read()
table = zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN])

print(f'Table size: {len(table)} bytes')
print(f'Old embedded ID  : {OLD_ID.decode()}')
print(f'Old embedded token: {OLD_TOKEN.decode()}')

new_id = input('New embedded ID (10 digits, or Enter to skip): ').strip()
new_token = input('New bot token (46 chars, or Enter to skip): ').strip()

if new_id:
    assert len(new_id) == len(OLD_ID) and new_id.isdigit(), \
        f'ID must be exactly {len(OLD_ID)} digits (you gave {len(new_id)})'
    if OLD_ID not in table:
        print('WARNING: old ID not found in table — aborting ID change.')
        new_id = ''
if new_token:
    assert len(new_token) == len(OLD_TOKEN), \
        f'Token must be exactly {len(OLD_TOKEN)} chars (you gave {len(new_token)})'
    if OLD_TOKEN not in table:
        print('WARNING: old token not found in table — aborting token change.')
        new_token = ''

if new_id:
    table = table.replace(OLD_ID, new_id.encode(), 1)
    print(f'ID patched: {OLD_ID.decode()} -> {new_id}')
if new_token:
    table = table.replace(OLD_TOKEN, new_token.encode(), 1)
    print(f'Token patched (hidden)')

comp = zlib.compress(table)
if len(comp) > ZLIB_LEN:
    print(f'ERROR: recompressed table ({len(comp)}) larger than original ({ZLIB_LEN}). Aborting.')
    sys.exit(2)

out = SO_PATH.replace('.so', '_embedded.so')
open(out, 'wb').write(data[:ZLIB_OFF] + comp + b'\x00' * (ZLIB_LEN - len(comp))
                      + data[ZLIB_OFF + ZLIB_LEN:])
print(f'Saved: {out}')
print('NOTE: If you changed the token, update BOT_TOKEN usage accordingly;')
print('the bot will now log in with the new token. ID change affects the')
print('embedded system key used in license checks.')
