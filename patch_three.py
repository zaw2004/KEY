#!/usr/bin/env python3
"""
patch_three.py — Patch THREE values in the sirzipp .so in one run:
  1. ADMIN_IDS   (machine-code constant at offset 0x9b32)
  2. Embedded ID (zlib table chunk 13 — must be exactly 10 digits)
  3. BOT_TOKEN   (zlib table chunk 14 — must be exactly 46 characters)

Usage (Termux / Replit):
    python3 patch_three.py sirzipp.cpython-311-x86_64-linux-gnu.so

Prompts (press Enter to skip any):
    New admin ID (digits)
    New embedded ID (10 digits)
    New bot token (46 chars)

Output: sirzipp..._three.so
Python 3 only — no dependencies.
"""
import sys
import zlib
import struct

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548
ADMIN_OFF = 0x9b32
OLD_ADMIN = 8556036826
OLD_ADMIN_LE = struct.pack('<q', OLD_ADMIN)
OLD_TOKEN = b'8960099014:AAGTdr-eMULHi5RNUgWDQf9eH71bq5jRi5w'


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


def ask(prompt, digits_only=False, required_len=None):
    while True:
        try:
            v = input(prompt).strip()
        except EOFError:
            return None
        if v == '':
            return ''
        if digits_only and not v.isdigit():
            print(f'  ERROR: digits only. (got {v!r})')
            continue
        if required_len is not None and len(v) != required_len:
            print(f'  ERROR: exactly {required_len} characters needed (got {len(v)}).')
            continue
        return v


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    so_path = sys.argv[1]
    data = bytearray(open(so_path, 'rb').read())
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)

    cur_admin = struct.unpack('<q', bytes(data[ADMIN_OFF:ADMIN_OFF + 8]))[0]
    table = zlib.decompress(bytes(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN]))
    print('=== Patch three values in one run ===')
    print(f'Current: admin ID = {cur_admin}, embedded ID = {table[0x67:0x71].decode()}')
    print()

    admin = ask(f'New admin ID (or Enter to skip): ', digits_only=True)
    emb = ask('New embedded ID, 10 digits (or Enter to skip): ', digits_only=True, required_len=10)
    tok = ask('New bot token, 46 chars (or Enter to skip): ')

    if not any((admin, emb, tok)):
        print('Nothing to patch. Exiting.')
        sys.exit(0)

    changes = []

    if admin:
        new_id = int(admin)
        new_le = struct.pack('<q', new_id)
        if OLD_ADMIN_LE in data:
            data = data.replace(OLD_ADMIN_LE, new_le, 1)
        else:
            print('NOTE: default pattern not found — patching fixed offset 0x9b32.')
            data[ADMIN_OFF:ADMIN_OFF + 8] = new_le
        changes.append(f'admin ID {cur_admin} -> {new_id}')

    if emb:
        new_emb = emb.encode()
        old_emb = table[0x67:0x71]
        if new_emb == old_emb:
            emb = ''
        elif old_emb in table:
            table = table.replace(old_emb, new_emb, 1)
            changes.append(f'embedded ID {old_emb.decode()} -> {emb}')
        else:
            print('WARNING: embedded ID not found in table — skipped.')
            emb = ''

    if tok:
        new_tok = tok.encode()
        if new_tok == OLD_TOKEN:
            tok = ''
        elif OLD_TOKEN in table:
            table = table.replace(OLD_TOKEN, new_tok, 1)
            changes.append('bot token replaced (46 chars)')
        else:
            print('WARNING: old token not found in table — skipped.')
            tok = ''

    if any((emb, tok)):
        comp = compress_fit(bytes(table))
        data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN] = comp + b'\x00' * (ZLIB_LEN - len(comp))

    out = so_path.replace('.so', '_three.so')
    open(out, 'wb').write(data)

    print()
    print('Saved:', out)
    print('Changes applied:')
    for c in changes:
        print('  -', c)
    if not changes:
        print('  (none)')
    print()
    print('Copy over the original to run:')
    print('  cp', out, so_path)

if __name__ == '__main__':
    main()
