#!/usr/bin/env python3
"""Patch Telegram username and chat-ID values in a Cython .so file."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ZLIB_OFFSET = 0x81C78


class PatchError(RuntimeError):
    pass


@dataclass
class OccurrenceReport:
    old: bytes
    new: bytes
    decompressed_offsets: list[int] = field(default_factory=list)
    raw_inside_offsets: list[int] = field(default_factory=list)
    raw_outside_offsets: list[int] = field(default_factory=list)


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


def report_occurrences(raw: bytes, decompressed: bytes, old: bytes, new: bytes, allocation: int) -> OccurrenceReport:
    rep = OccurrenceReport(old, new)
    rep.decompressed_offsets = find_all(decompressed, old)
    for pos in find_all(raw, old):
        if ZLIB_OFFSET <= pos < ZLIB_OFFSET + allocation:
            rep.raw_inside_offsets.append(pos)
        else:
            rep.raw_outside_offsets.append(pos)
    return rep


def fmt_offsets(values: list[int], limit: int = 20) -> str:
    if not values:
        return "none"
    text = ", ".join(f"0x{x:x}" for x in values[:limit])
    if len(values) > limit:
        text += f", ... (+{len(values) - limit} more)"
    return text


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


def patch_plaintext_outside(raw: bytearray, old: bytes, new: bytes, label: str, allocation: int) -> int:
    positions = [
        p for p in find_all(bytes(raw), old)
        if not (ZLIB_OFFSET <= p < ZLIB_OFFSET + allocation)
    ]
    if not positions:
        return 0
    if len(new) > len(old):
        raise PatchError(
            f"{label}: {len(positions)} plaintext occurrence(s) found outside zlib, "
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


def verify(path: Path, old_user: bytes, new_user: bytes, old_id: bytes, new_id: bytes) -> dict[str, int | bool]:
    raw = path.read_bytes()
    dec, consumed = decompress_table(raw)
    result: dict[str, int | bool] = {
        "raw_old_username": raw.count(old_user),
        "raw_old_id": raw.count(old_id),
        "dec_old_username": dec.count(old_user),
        "dec_old_id": dec.count(old_id),
        "raw_new_username": raw.count(new_user),
        "raw_new_id": raw.count(new_id),
        "dec_new_username": dec.count(new_user),
        "dec_new_id": dec.count(new_id),
        "decompressed_size": len(dec),
        "compressed_size": consumed,
        "elf": raw[:4] == b"\x7fELF",
    }
    if any(result[k] for k in ("raw_old_username", "raw_old_id", "dec_old_username", "dec_old_id")):
        raise PatchError("Verification failed: at least one old value remains.")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch Telegram username and chat/admin ID values in a sirzipp .so file."
    )
    parser.add_argument("so_path", help="Input .so file path")
    parser.add_argument("--old-username", help="Old Telegram username, e.g. @SIRZIPP")
    parser.add_argument("--new-username", help="New Telegram username, e.g. @KENOBEE")
    parser.add_argument("--old-id", help="Old chat/admin ID, e.g. 8556036826")
    parser.add_argument("--new-id", help="New chat/admin ID, e.g. 1767590675")
    parser.add_argument("-o", "--output", help="Output path; default adds _patched before the suffix")
    parser.add_argument("--no-prompt", action="store_true", help="Require all values via command-line options")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        src = Path(args.so_path).expanduser().resolve()
        if not src.is_file():
            raise PatchError(f"Input file does not exist: {src}")

        old_username = ask(args.old_username, "Old Telegram username (e.g. @SIRZIPP): ", args.no_prompt)
        new_username = ask(args.new_username, "New Telegram username (e.g. @KENOBE): ", args.no_prompt)
        old_id = ask(args.old_id, "Old chat/admin ID (e.g. 8556036826): ", args.no_prompt)
        new_id = ask(args.new_id, "New chat/admin ID (e.g. 1767590675): ", args.no_prompt)
        if not all((old_username, new_username, old_id, new_id)):
            raise PatchError("Replacement values must not be empty.")

        old_user_b, new_user_b = old_username.encode(), new_username.encode()
        old_id_b, new_id_b = old_id.encode(), new_id.encode()
        raw = src.read_bytes()
        table, allocation = decompress_table(raw)
        original_size = len(table)

        reports = [
            ("username", report_occurrences(raw, table, old_user_b, new_user_b, allocation)),
            ("chat/admin ID", report_occurrences(raw, table, old_id_b, new_id_b, allocation)),
        ]
        print(f"Input: {src}")
        print(f"Zlib stream: offset 0x{ZLIB_OFFSET:x}, allocation {allocation} bytes")
        print(f"Original decompressed size: {original_size} bytes")
        for label, rep in reports:
            print(f"\n{label}: {rep.old!r} -> {rep.new!r}")
            print(f"  length: {len(rep.old)} -> {len(rep.new)} bytes")
            print(f"  inside zlib table: {len(rep.decompressed_offsets)} at {fmt_offsets(rep.decompressed_offsets)}")
            print(f"  raw inside compressed allocation: {len(rep.raw_inside_offsets)} at {fmt_offsets(rep.raw_inside_offsets)}")
            print(f"  raw plaintext outside zlib: {len(rep.raw_outside_offsets)} at {fmt_offsets(rep.raw_outside_offsets)}")

        modified_table, table_user_count = patch_table(table, old_user_b, new_user_b, "Username")
        modified_table, table_id_count = patch_table(modified_table, old_id_b, new_id_b, "Chat/admin ID")
        recompressed = zlib.compress(modified_table)
        print(f"\nRecompressed size: {len(recompressed)} bytes")
        if len(recompressed) > allocation:
            raise PatchError(
                f"Recompressed data does not fit ({len(recompressed)} > {allocation} bytes); no output written."
            )

        patched = bytearray(raw)
        raw_user_count = patch_plaintext_outside(patched, old_user_b, new_user_b, "Username", allocation)
        raw_id_count = patch_plaintext_outside(patched, old_id_b, new_id_b, "Chat/admin ID", allocation)
        patched[ZLIB_OFFSET:ZLIB_OFFSET + allocation] = recompressed + b"\x00" * (allocation - len(recompressed))

        output = Path(args.output).expanduser().resolve() if args.output else default_output(src)
        atomic_write(output, bytes(patched), src.stat().st_mode & 0o777)
        result = verify(output, old_user_b, new_user_b, old_id_b, new_id_b)

        print(f"\nSaved patched file: {output}")
        print(f"Replacements in decompressed table: username={table_user_count}, chat/admin ID={table_id_count}")
        print(f"Replacements in raw plaintext outside zlib: username={raw_user_count}, chat/admin ID={raw_id_count}")
        print(f"Verified old values: username raw/decoded={result['raw_old_username']}/{result['dec_old_username']}, ID raw/decoded={result['raw_old_id']}/{result['dec_old_id']}")
        print(f"Verified new values: username raw/decoded={result['raw_new_username']}/{result['dec_new_username']}, ID raw/decoded={result['raw_new_id']}/{result['dec_new_id']}")
        print(f"Decompressed size: {result['decompressed_size']} bytes (original {original_size})")
        print(f"ELF header: {'yes' if result['elf'] else 'no'}")
        return 0
    except PatchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
