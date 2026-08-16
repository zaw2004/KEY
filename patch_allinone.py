#!/usr/bin/env python3
"""
patch_allinone.py — Change EVERYTHING in the sirzipp .so in one command.

Patches in a single run:
  1. ADMIN_IDS (machine-code immediate at offset 0x9b32)
  2. Embedded zlib-table ID (10-digit system/creator key at table offset 0x67)
  3. BOT_TOKEN (zlib table, chunk 14 — must stay 46 characters)
  4. Telegram username (e.g. KENOBEE or sayarkn in the zlib string table)

Auto-detection: reads the CURRENT values from the binary, so it works on
different builds (original KENOBEE build, sayarkn build, already-patched
files, etc.).

Usage (Termux / Replit):
    python3 patch_allinone.py sirzipp.cpython-311-x86_64-linux-gnu.so

Prompts:
  New admin ID            (digits)                      - Enter to skip
  New embedded ID (10 dig)(digits)                      - Enter to skip
  New bot token (46 chars)(exactly 46 chars)            - Enter to skip
  New username            (e.g. ZAW2004)                - Enter to skip

Output: sirzipp..._allinone.so
No dependencies except Python 3 (zlib is built-in).
"""
import sys
import zlib
import struct

ZLIB_OFF = 0x81C78
ALLOC = 5552            # memoryview buffer; stream must stay <= 5548


def load_table(data):
    for wbits in (13, -15, 9, 12, 14, 15):
        try:
            return zlib.decompress(bytes(data[ZLIB_OFF:ZLIB_OFF + ALLOC]), wbits), wbits
        except Exception:
            continue
    return None, None


def compress_fit(table):
    """Compress so the stream fits within the 5548-byte region."""
    for strat in (zlib.Z_FIXED,):
        for wbits in (13, 12, 14, 15):
            try:
                co = zlib.compressobj(9, zlib.DEFLATED, wbits, strat)
            except ValueError:
                continue
            cand = co.compress(table) + co.flush()
            if len(cand) <= 5548:
                return cand
    for wbits in (13, 12, 14, 15):
        co = zlib.compressobj(9, zlib.DEFLATED, wbits)
        cand = co.compress(table) + co.flush()
        if len(cand) <= 5548:
            return cand
    for level in range(9, 0, -1):
        cand = zlib.compress(table, level)
        if len(cand) <= 5548:
            return cand
    comp = zlib.compress(table)
    print(f'WARNING: recompressed size {len(comp)} exceeds 5548; writing anyway.')
    return comp


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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    so_path = sys.argv[1]
    data = bytearray(open(so_path, 'rb').read())
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)

    # Auto-detect current values
    cur_admin = struct.unpack('<q', bytes(data[0x9b32:0x9b3a]))[0]
    table, wbits = load_table(data)
    if table is None:
        print('ERROR: cannot decode the string table in this binary.')
        sys.exit(3)

    cur_emb = table[0x67:0x71]
    cur_tok = table[0x71:0x9f]
    # current username: search for the common candidates
    cur_user = None
    for cand in (b'KENOBEE', b'sayarkn', b'ZAW2004'):
        if cand in table:
            cur_user = cand
            break
    print('=== Patch everything in one run ===')
    print(f'Current: admin ID = {cur_admin}')
    print(f'         embedded ID = {cur_emb.decode()}')
    print(f'         token = {cur_tok.decode()} ({len(cur_tok)} chars)')
    print(f'         username = {cur_user.decode() if cur_user else "(none found)"}')
    print()

    admin = ask('New admin ID (digits, or Enter to skip): ', digits_only=True)
    while admin == 'RETRY':
        admin = ask('New admin ID (digits, or Enter to skip): ', digits_only=True)

    emb = ask('New embedded ID (10 digits, or Enter to skip): ', required_len=10, digits_only=True)
    while emb == 'RETRY':
        emb = ask('New embedded ID (10 digits, or Enter to skip): ', required_len=10, digits_only=True)

    tok = ask('New bot token (46 chars, or Enter to skip): ', required_len=46)
    while tok == 'RETRY':
        tok = ask('New bot token (46 chars, or Enter to skip): ', required_len=46)

    user = ask('New username (e.g. ZAW2004, or Enter to skip): ')

    if not any((admin, emb, tok, user)):
        print('Nothing to patch. Exiting.')
        sys.exit(0)

    changes = []

    # --- Zlib table changes ---
    if emb:
        nb = emb.encode()
        if nb != cur_emb and cur_emb in table:
            table = table.replace(cur_emb, nb, 1)
            changes.append(f'embedded ID {cur_emb.decode()} -> {emb}')
        else:
            print('NOTE: embedded ID unchanged.')

    if tok:
        tb = tok.encode()
        if len(tb) == len(cur_tok) and tb != cur_tok and cur_tok in table:
            table = table.replace(cur_tok, tb, 1)
            changes.append('bot token replaced (46 chars)')
        elif tb == cur_tok:
            print('NOTE: token unchanged.')
        else:
            print('WARNING: token chunk not replaceable (length mismatch) — token skipped.')

    if user:
        ub = user.encode()
        if cur_user and cur_user in table:
            count = table.count(cur_user)
            if len(ub) <= len(cur_user):
                table = table.replace(cur_user, ub + b'\x00' * (len(cur_user) - len(ub)))
            else:
                table = table.replace(cur_user, ub)
            changes.append(f'username {cur_user.decode()} -> {user} ({count} places)')
        else:
            print('WARNING: no known username found in table — username skipped.')

    if any((emb, tok, user)):
        comp = compress_fit(table)
        data[ZLIB_OFF:ZLIB_OFF + ALLOC] = comp + b'\x00' * (ALLOC - len(comp))
        try:
            zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ALLOC], wbits)
        except Exception as e:
            print(f'ERROR: patched table does not decompress ({e}). Aborting.')
            sys.exit(5)

    # --- Admin ID machine-code patch ---
    if admin:
        new_id = int(admin)
        data[0x9b32:0x9b3a] = struct.pack('<q', new_id)
        changes.append(f'ADMIN_IDS machine code {cur_admin} -> {new_id}')

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
    print('Copy over the original to run:')
    print('  cp', out, so_path)
    print()
    print('NOTE: after patching, the license system needs a key matching the NEW')
    print('embedded ID in your allinone.txt / bypass.txt for Access Granted.')

if __name__ == '__main__':
    main()
