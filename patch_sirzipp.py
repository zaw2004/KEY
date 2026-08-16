#!/usr/bin/env python3
"""Patch Telegram username in a sirzipp Cython .so file (zlib string table)."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zlib
from pathlib import Path

ZLIB_OFFSET = 0x81C78


class PatchError(RuntimeError):
    pass


def find_all(data: bytes, needle: bytes) -> list[int]:
    result: list[int] = []
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos < 0:
            return result
        result.append(pos)
        start = pos + 1


def ask(value: str | None, prompt: str, no_prompt: bool) -> str:
    if value is not None:
        return value
    if no_prompt:
        raise PatchError(f"Missing required option: {prompt.rstrip(': ')}")
    try:
        return input(prompt).strip()
    except EOFError as exc:
        raise PatchError(f"No value supplied for {prompt.rstrip(': ')}") from exc


def default_output(path: Path) -> Path:
    return path.with_name(f"{path.stem}_patched{path.suffix}")


def decompress_table(raw: bytes) -> tuple[bytes, int]:
    if len(raw) <= ZLIB_OFFSET:
        raise PatchError(f"Input is shorter than zlib offset 0x{ZLIB_OFFSET:x}.")
    obj = zlib.decompressobj()
    try:
        decompressed = obj.decompress(raw[ZLIB_OFFSET:])
    except zlib.error as exc:
        raise PatchError(f"Could not decompress stream at 0x{ZLIB_OFFSET:x}: {exc}") from exc
    if not obj.eof:
        raise PatchError("The zlib stream did not reach EOF.")
    consumed = len(raw[ZLIB_OFFSET:]) - len(obj.unused_data)
    if consumed <= 0:
        raise PatchError("Could not determine the compressed allocation.")
    return decompressed, consumed


def padded_replacement(old: bytes, new: bytes) -> bytes:
    return new + b"\x00" * (len(old) - len(new))


def patch_table(data: bytes, old: bytes, new: bytes, label: str) -> tuple[bytes, int]:
    count = data.count(old)
    if not count:
        return data, 0
    if len(new) <= len(old):
        return data.replace(old, padded_replacement(old, new)), count
    print(
        f"Warning: {label} grows from {len(old)} to {len(new)} bytes; "
        "the recompressed stream must still fit its allocation."
    )
    return data.replace(old, new), count


def patch_plaintext_outside(raw: bytearray, old: bytes, new: bytes, allocation: int) -> int:
    positions = [
        p for p in find_all(bytes(raw), old)
        if not (ZLIB_OFFSET <= p < ZLIB_OFFSET + allocation)
    ]
    if not positions:
        return 0
    if len(new) > len(old):
        raise PatchError(
            f"{len(positions)} plaintext occurrence(s) found outside zlib, "
            f"but the new value is longer ({len(new)} > {len(old)}) and cannot be patched in place."
        )
    replacement = padded_replacement(old, new)
    for pos in positions:
        raw[pos:pos + len(old)] = replacement
    return len(positions)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch the Telegram username in a sirzipp .so file."
    )
    parser.add_argument("so_path", help="Input .so file path")
    parser.add_argument("--old-username", help="Old Telegram username, e.g. KENOBEE")
    parser.add_argument("--new-username", help="New Telegram username, e.g. ZAW2004")
    parser.add_argument("-o", "--output", help="Output path; default adds _patched before the suffix")
    parser.add_argument("--no-prompt", action="store_true", help="Require all values via command-line options")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        src = Path(args.so_path).expanduser().resolve()
        if not src.is_file():
            raise PatchError(f"Input file does not exist: {src}")

        old_username = ask(args.old_username, "Old Telegram username (e.g. KENOBEE): ", args.no_prompt)
        new_username = ask(args.new_username, "New Telegram username (e.g. ZAW2004): ", args.no_prompt)
        if not (old_username and new_username):
            raise PatchError("Username values must not be empty.")

        old_b, new_b = old_username.encode(), new_username.encode()
        raw = src.read_bytes()
        table, allocation = decompress_table(raw)
        original_size = len(table)

        inside = find_all(table, old_b)
        outside = [p for p in find_all(raw, old_b) if not (ZLIB_OFFSET <= p < ZLIB_OFFSET + allocation)]
        print(f"Input: {src}")
        print(f"Old username {old_b!r} -> new username {new_b!r}")
        print(f"  inside zlib table: {len(inside)} at " + (", ".join(f"0x{x:x}" for x in inside) or "none"))
        print(f"  raw plaintext outside zlib: {len(outside)} at " + (", ".join(f"0x{x:x}" for x in outside) or "none"))

        modified_table, table_count = patch_table(table, old_b, new_b, "Username")
        # Compress with best effort to stay within the allocation
        level = 9
        recompressed = None
        while level >= 1:
            cand = zlib.compress(modified_table, level)
            if len(cand) <= allocation:
                recompressed = cand
                break
            level -= 1
        if recompressed is None:
            recompressed = zlib.compress(modified_table)
        if len(recompressed) > allocation:
            print(f"Warning: recompressed size {len(recompressed)} exceeds allocation {allocation}; "
                  "writing anyway (file may have trailing zeroes).")

        patched = bytearray(raw)
        raw_count = patch_plaintext_outside(patched, old_b, new_b, allocation)
        patched[ZLIB_OFFSET:ZLIB_OFFSET + allocation] = recompressed + b"\x00" * max(0, allocation - len(recompressed))

        output = Path(args.output).expanduser().resolve() if args.output else default_output(src)
        atomic_write(output, bytes(patched), src.stat().st_mode & 0o777)

        verify_raw = output.read_bytes()
        print(f"\nSaved patched file: {output}")
        print(f"Replacements in zlib table: {table_count}")
        print(f"Replacements in raw plaintext outside zlib: {raw_count}")
        dec, _ = decompress_table(verify_raw)
        leftover = verify_raw.count(old_b) + dec.count(old_b)
        print(f"Old username remaining: {leftover} (0 = fully patched)")
        return 0
    except PatchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
