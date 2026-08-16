#!/usr/bin/env python3
"""
check_embedded_id.py — Check (and optionally change) the embedded ID
inside the sirzipp .so.

The embedded ID lives in the zlib-compressed constant table at chunk 13.
It is the 10-digit value used by the license system ('Your key' value).

Usage (Termux / Replit):
    python3 check_embedded_id.py sirzipp.cpython-311-x86_64-linux-gnu.so

Output: prints the embedded ID and the embedded bot token.
Optional: python3 check_embedded_id.py file.so --change 1234567890
          (new ID must be exactly 10 digits; output file = ..._embedded.so)

Python 3 only (zlib built-in).
"""
import sys
import zlib

ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548

OLD_TOKEN = b'8960099014:AAGTdr-eMULHi5RNUgWDQf9eH71bq5jRi5w'  # 46 bytes


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

    try:
        table = zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN])
    except zlib.error as e:
        print(f'ERROR: cannot decompress the string table ({e}).')
        print('The binary may be corrupted or is a different build.')
        sys.exit(3)

    embedded_id = table[0x67:0x71]          # chunk 13, 10 bytes
    token = table[0x71:0x9f]                # chunk 14, 46 bytes

    print(f'Embedded ID   : {embedded_id.decode("utf-8", "replace")}')
    print(f'Embedded token: {token.split(b":")[0].decode("ascii", "replace")}:...')

    # parse check
    if embedded_id.isdigit():
        print('Embedded ID is a valid 10-digit number.')
    else:
        print('WARNING: embedded ID does not look like a 10-digit number!')

    # --- optional change ---
    change = None
    if '--change' in sys.argv:
        idx = sys.argv.index('--change')
        if idx + 1 < len(sys.argv):
            change = sys.argv[idx + 1].strip()

    if change:
        if not change.isdigit() or len(change) != 10:
            print(f'ERROR: new ID must be exactly 10 digits (got {change!r}).')
            sys.exit(4)
        new_id = change.encode()
        if new_id == embedded_id:
            print('ID unchanged — nothing to do.')
            sys.exit(0)
        if embedded_id not in table:
            print('ERROR: current embedded ID not found in table — different build?')
            sys.exit(5)
        table = table.replace(embedded_id, new_id, 1)
        comp = compress_fit(table)
        out = so_path.replace('.so', '_embedded.so')
        open(out, 'wb').write(data[:ZLIB_OFF] + comp + b'\x00' * (ZLIB_LEN - len(comp))
                              + data[ZLIB_OFF + ZLIB_LEN:])
        print(f'Embedded ID changed: {embedded_id.decode()} -> {change}')
        print('Saved:', out)
        print('NOTE: the license system will need a key matching the new ID')
        print('in allinone.txt / bypass.txt for Access Granted.')
    else:
        print()
        print('To change it, run:')
        print(f'  python3 {sys.argv[0]} {so_path} --change <10-digit-id>')

if __name__ == '__main__':
    main()
