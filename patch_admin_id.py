#!/usr/bin/env python3
"""
patch_admin_id.py — Change ONLY the admin ID (ADMIN_IDS) inside the
sirzipp .so.

The admin ID is stored as a machine-code constant at file offset 0x9b32
(inside the movabs instruction that builds the ADMIN_IDS list).

Usage (Termux / Replit):
    python3 patch_admin_id.py sirzipp.cpython-311-x86_64-linux-gnu.so

Prompts for the new admin ID (digits only). Output: sirzipp..._admin.so
Python 3 only — no dependencies.
"""
import sys
import struct

OLD_ADMIN = 8556036826
OLD_ADMIN_LE = struct.pack('<q', OLD_ADMIN)
PATCH_OFF = 0x9b32


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    so_path = sys.argv[1]
    data = bytearray(open(so_path, 'rb').read())
    if data[:4] != b'\x7fELF':
        print('ERROR: not an ELF binary.')
        sys.exit(2)

    # Report current value
    cur = struct.unpack('<q', bytes(data[PATCH_OFF:PATCH_OFF + 8]))[0]
    print(f'Current admin ID in binary: {cur}')

    try:
        new = input('New admin ID (digits): ').strip()
    except EOFError:
        print('Usage: python3 patch_admin_id.py file.so < id.txt')
        sys.exit(1)

    if not new:
        print('Nothing to patch. Exiting.')
        sys.exit(0)

    if not new.isdigit():
        print(f'ERROR: admin ID must be digits only (got {new!r}).')
        sys.exit(3)

    new_id = int(new)
    if new_id < 1 or new_id > 2 ** 63 - 1:
        print('ERROR: admin ID out of range.')
        sys.exit(4)

    new_le = struct.pack('<q', new_id)
    if OLD_ADMIN_LE in data:
        data = data.replace(OLD_ADMIN_LE, new_le, 1)
    else:
        # already-patched or different build: patch at the fixed offset instead
        print('NOTE: default pattern not found — patching at the fixed offset 0x9b32.')
        data[PATCH_OFF:PATCH_OFF + 8] = new_le

    out = so_path.replace('.so', '_admin.so')
    open(out, 'wb').write(data)

    # Verify
    check = struct.unpack('<q', bytes(data[PATCH_OFF:PATCH_OFF + 8]))[0]
    print(f'New admin ID written at 0x9b32: {check}')
    if check != new_id:
        print('ERROR: verification failed — file not modified correctly.')
        sys.exit(5)

    print('Saved:', out)
    print('Copy it over the original to run:')
    print('  cp', out, so_path)

if __name__ == '__main__':
    main()
