#!/usr/bin/env python3
"""
patch_allinone.py — Change EVERYTHING in the sirzipp .so in one command.

Patches in a single run:
  1. ADMIN_IDS (machine-code immediate at offset 0x9b32)
  2. Embedded zlib-table ID (10-digit system/creator key at table offset 0x67)
  3. BOT_TOKEN (zlib table, chunk 14 — must stay 46 characters)
  4. Telegram username (KENOBEE in the zlib string table — 4 places)

Usage (Termux / Replit):
    python3 patch_allinone.py sirzipp.cpython-311-x86_64-linux-gnu.so

Prompts:
  New admin ID            (digits, e.g. 7205649312)   - Enter to skip
  New embedded ID (10 dig)(digits)                    - Enter to skip
  New bot token (46 chars)(exactly 46 chars)          - Enter to skip
  New username            (e.g. ZAW2004)              - Enter to skip

Output: sirzipp..._allinone.so
No dependencies except Python 3 (zlib is built-in).
"""
import sys
import zlib
import struct

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548

OLD_ADMIN = 8556036826
OLD_ADMIN_LE = struct.pack('<q', OLD_ADMIN)

OLD_EMBED_ID = b'1767590675'                          # 10 bytes
OLD_TOKEN = b'8960099014:AAGTdr-eMULHi5RNUgWDQf9eH71bq5jRi5w'  # 46 bytes
OLD_USER = b'KENOBEE'


def ask(prompt, required_len=None, digits_only=False):
    try:
        v = input(prompt).strip()
    except EOFError:
        return ''
    if v == '':
        return ''
    if digits_only and not v.isdigit():
        print(f'  ERROR: must be digits only. (got {v!r})')
        return 'RETRY'
    if required_len is not None and len(v) != required_len:
        print(f'  ERROR: must be exactly {required_len} characters. (got {len(v)})')
        return 'RETRY'
    return v


def compress_fit(table):
    """Compress so the stream fits within ZLIB_LEN (5548) bytes."""
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
    data = bytearray(open(so_path, 'rb').read())
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)

    print('=== Patch everything in one run ===')
    print('Old values: admin ID = 8556036826, embedded ID = 1767590675')
    print('            token = 8960099014:AAGTdr-... (46 chars), username = KENOBEE')
    print()

    # 1) Admin ID
    admin = ask('New admin ID (digits, or Enter to skip): ', digits_only=True)
    while admin == 'RETRY':
        admin = ask('New admin ID (digits, or Enter to skip): ', digits_only=True)

    # 2) Embedded ID (10 digits)
    emb = ask('New embedded ID (10 digits, or Enter to skip): ', required_len=10, digits_only=True)
    while emb == 'RETRY':
        emb = ask('New embedded ID (10 digits, or Enter to skip): ', required_len=10, digits_only=True)

    # 3) Bot token (46 chars)
    tok = ask('New bot token (46 chars, or Enter to skip): ', required_len=46)
    while tok == 'RETRY':
        tok = ask('New bot token (46 chars, or Enter to skip): ', required_len=46)

    # 4) Username
    user = ask('New username (e.g. ZAW2004, or Enter to skip): ')

    if not any((admin, emb, tok, user)):
        print('Nothing to patch. Exiting.')
        sys.exit(0)

    changes = []

    # --- Zlib table changes ---
    table = zlib.decompress(bytes(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN]))

    if emb:
        nb = emb.encode()
        assert nb not in table or OLD_EMBED_ID in table, 'state check'
        if OLD_EMBED_ID in table:
            table = table.replace(OLD_EMBED_ID, nb, 1)
            changes.append('embedded ID 1767590675 -> ' + emb)

    if tok:
        tb = tok.encode()
        if OLD_TOKEN in table:
            table = table.replace(OLD_TOKEN, tb, 1)
            changes.append('bot token replaced (46 chars)')
        else:
            print('WARNING: old token not found in table — token skipped.')

    if user:
        ub = user.encode()
        count = table.count(OLD_USER)
        if count:
            if len(ub) <= len(OLD_USER):
                table = table.replace(OLD_USER, ub + b'\x00' * (len(OLD_USER) - len(ub)))
            else:
                table = table.replace(OLD_USER, ub)
            changes.append(f'username KENOBEE -> {user} ({count} places)')
        else:
            print('WARNING: KENOBEE not found in table — username skipped.')

    comp = compress_fit(bytes(table))
    data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN] = comp + b'\x00' * (ZLIB_LEN - len(comp))

    # --- Admin ID machine-code patch ---
    if admin:
        new_id = int(admin)
        if OLD_ADMIN_LE in data:
            data = data.replace(OLD_ADMIN_LE, struct.pack('<q', new_id), 1)
            changes.append(f'ADMIN_IDS machine code {OLD_ADMIN} -> {new_id}')
        else:
            print('WARNING: admin ID machine-code immediate not found — binary may already be patched.')

    out = so_path.replace('.so', '_allinone.so')
    open(out, 'wb').write(data)
    print()
    print('Saved:', out)
    print('Changes applied:')
    for c in changes:
        print('  -', c)
    if not changes:
        print('  (none)')
    print()
    print('NOTE: after patching, the license system needs a key matching the NEW')
    print('embedded ID in your allinone.txt / bypass.txt for Access Granted.')

if __name__ == '__main__':
    main()
