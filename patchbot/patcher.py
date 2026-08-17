"""patcher.py — Core patch logic for the sirzipp .so (port of patch_three.py).

Patches up to three values in one pass:
  1. ADMIN_IDS   — machine-code constant at offset 0x9b32 (8 bytes, little-endian)
  2. Embedded ID — zlib table chunk 13 (table[0x67:0x71], exactly 10 digits)
  3. BOT_TOKEN   — zlib table chunk 14 (table[0x71:0x9f], exactly 46 chars)

Auto-detects current values, validates inputs, and recompresses the zlib
table using Z_FIXED so it fits the fixed 5548-byte region.

Raises PatchError with a human-readable message on any failure.
"""
import zlib
import struct

ZLIB_OFF = 0x81C78
ALLOC = 5552            # PyMemoryView buffer; stream must stay <= 5548
ADMIN_OFF = 0x9b32


class PatchError(Exception):
    pass


def _load_table(data):
    for wbits in (13, -15, 9, 12, 14, 15):
        try:
            return zlib.decompress(bytes(data[ZLIB_OFF:ZLIB_OFF + ALLOC]),
                                   wbits), wbits
        except Exception:
            continue
    raise PatchError('Cannot decode the string table in this binary. '
                     'It may not be a supported sirzipp .so build.')


def _compress_fit(table):
    for wbits in (13, 12, 14, 15):
        co = zlib.compressobj(9, zlib.DEFLATED, wbits, zlib.Z_FIXED)
        cand = co.compress(table) + co.flush()
        if len(cand) <= 5548:
            return cand
    for wbits in (13, 12, 14, 15):
        co = zlib.compressobj(9, zlib.DEFLATED, wbits)
        cand = co.compress(table) + co.flush()
        if len(cand) <= 5548:
            return cand
    raise PatchError('Patched table is too large to fit the binary. '
                     'Use shorter values.')


def read_current(data):
    """Return dict with the current values found in the binary."""
    table, _ = _load_table(data)
    return {
        'admin': struct.unpack('<q', bytes(data[ADMIN_OFF:ADMIN_OFF + 8]))[0],
        'embedded': table[0x67:0x71].decode(),
        'token': table[0x71:0x9f].decode(),
    }


def patch_binary(data, admin=None, embedded=None, token=None, out_name=None):
    """Patch the given ELF bytes.

    admin/embedded/token: new string values, or None to leave unchanged.
    out_name: filename for the saved bytes (defaults to input_name patched).
    Returns the patched bytes.
    """
    if data[:4] != b'\x7fELF':
        raise PatchError('Not an ELF binary.')

    table, wbits = _load_table(data)
    cur = read_current(data)
    changes = []

    if admin is not None:
        if not admin.isdigit():
            raise PatchError('Admin ID must be digits only.')
        data = bytearray(data)
        data[ADMIN_OFF:ADMIN_OFF + 8] = struct.pack('<q', int(admin))
        changes.append(f'admin {cur["admin"]} -> {admin}')

    if embedded is not None:
        if len(embedded) != 10 or not embedded.isdigit():
            raise PatchError('Embedded ID must be exactly 10 digits.')
        nb = embedded.encode()
        old = table[0x67:0x71]
        if nb != old:
            table = table.replace(old, nb, 1)
            changes.append(f'embedded {cur["embedded"]} -> {embedded}')

    if token is not None:
        if len(token) != 46:
            raise PatchError(f'Token must be exactly 46 characters '
                             f'(got {len(token)}).')
        tb = token.encode()
        old = table[0x71:0x9f]
        if tb != old:
            table = table.replace(old, tb, 1)
            changes.append('token replaced')

    if embedded is not None or token is not None:
        comp = _compress_fit(table)
        data = bytearray(data)
        data[ZLIB_OFF:ZLIB_OFF + ALLOC] = comp + b'\x00' * (ALLOC - len(comp))
        try:
            zlib.decompress(data[ZLIB_OFF:ZLIB_OFF + ALLOC], wbits)
        except Exception as e:
            raise PatchError(f'Patched table failed to decompress: {e}')

    return bytes(data), changes
