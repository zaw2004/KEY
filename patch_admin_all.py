#!/usr/bin/env python3
"""
patch_admin_all.py — Change ALL admin ID occurrences in sirzipp .so at once.

Usage:
    python3 patch_admin_all.py <new_admin_id> [input.so]

Searches the whole binary for every possible encoding of the old admin ID
(8556036826):
  1. 64-bit little-endian immediate (machine-code movabs)
  2. 32-bit LE low part 0xfdfac2da combined with high word 0x00000001
  3. The same inside the zlib-compressed string table (offset 0x81C78)
Patches every found location with the new ID, verifies, and writes output.
Works offline, no dependencies, runs on Termux / Replit.
"""
import struct, sys, zlib

OLD_ID = 8556036826
OLD_LO = OLD_ID & 0xFFFFFFFF   # 0xfdfac2da
OLD_LO_LE = struct.pack('<I', OLD_LO)
OLD_HI_LE = struct.pack('<I', (OLD_ID >> 32) & 0xFFFFFFFF)  # 0x00000001
OLD64_LE = struct.pack('<q', OLD_ID)

# Zlib string table location (78 DA header)
ZLIB_OFF = 0x81C78
ZLIB_LEN = 5548

def find_all(data, needle):
    idxs, i = [], 0
    while True:
        j = data.find(needle, i)
        if j == -1:
            return idxs
        idxs.append(j)
        i = j + 1

def patch_zlib_table(data, new_id):
    """Re-compress the zlib string table with the ID replaced if present."""
    blob = data[ZLIB_OFF:ZLIB_OFF + ZLIB_LEN]
    try:
        table = zlib.decompress(blob)
    except Exception:
        return data, 0
    as_ascii = str(OLD_ID).encode()
    if as_ascii not in table:
        return data, 0
    new_table = table.replace(as_ascii, str(new_id).encode())
    level = 9
    while level >= 1:
        comp = zlib.compress(new_table, level)
        if len(comp) <= ZLIB_LEN:
            new_data = data[:ZLIB_OFF] + comp + data[ZLIB_OFF + ZLIB_LEN:]
            return new_data, 1
        level -= 1
    print('WARNING: zlib table did not shrink; ASCII ID in table left unpatched.')
    return data, 0

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    new_id = int(sys.argv[1])
    inp = sys.argv[2] if len(sys.argv) > 2 else 'sirzipp.cpython-311-x86_64-linux-gnu.so'
    out = inp.replace('.so', '_allpatched.so')
    data = open(inp, 'rb').read()

    hits = []
    # 1) full 64-bit LE
    for o in find_all(data, OLD64_LE):
        hits.append(('64-bit LE immediate', o))
    # 2) lo+hi combo (covers case where high word != 0x00000001 too, only accept combo)
    for o in find_all(data, OLD_LO_LE + OLD_HI_LE):
        # avoid double counting with the 64-bit hit (64-bit hit starts at same offset)
        if not any(h[1] == o for h in hits):
            hits.append(('32-bit lo+hi combo', o))

    print(f'Scanning {inp} for old admin ID {OLD_ID} ...')
    for kind, o in hits:
        print(f'  [{kind}] offset {hex(o)}')
    if not hits:
        print('  No occurrences found — binary may already be patched.')

    data, zlib_patched = patch_zlib_table(data, new_id)
    if zlib_patched:
        print(f'  [zlib string table] ASCII ID replaced (table re-compressed)')

    for kind, o in hits:
        if kind == '64-bit LE immediate':
            data = data[:o] + struct.pack('<q', new_id) + data[o + 8:]
        else:  # lo+hi combo
            data = data[:o] + struct.pack('<I', new_id & 0xFFFFFFFF) + struct.pack('<I', (new_id >> 32) & 0xFFFFFFFF) + data[o + 8:]

    # Verify nothing left
    leftover64 = data.find(OLD64_LE)
    leftover_combo = data.find(OLD_LO_LE + OLD_HI_LE)
    new_check = data.find(struct.pack('<q', new_id))
    print(f'\nVerification: old ID 64-bit leftover={leftover64}, combo leftover={leftover_combo}')
    print(f'New ID {new_id} present at 64-bit LE: {new_check} (hex {hex(new_check) if new_check != -1 else "-"})')

    open(out, 'wb').write(data)
    print(f'\nDone -> {out}  (admin IDs: {len(hits)} code location(s) patched)')

if __name__ == '__main__':
    main()
