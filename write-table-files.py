#!/usr/bin/env python
"""
write-table-files.py

Usage:
    python write-table-files.py <desired.txt> <folder_name>
Example:
    python write-table-files.py <desired.txt> C:/DEV/vhd_mounts/kicad/10.0/share/kicad/template

What it does:
1. Reads the desired library list from <desired.txt>
2. Backs up:
      sym-lib-table -> sym-lib-table_backup
      fp-lib-table  -> fp-lib-table_backup
3. Halts if the backups were not successful!
4. Rewrites:
      sym-lib-table
      fp-lib-table
   preserving all non-library lines, but only keeping library entries whose
   names appear in <desired.txt> for the matching type.
5. Stores all removed lines in a file called lib-table-removed-lines.txt

Input file format:
    symbol_library,Device
    symbol_library,Connector
    footprint_library,Resistor_SMD
    footprint_library,Connector_USB
"""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path


def load_desired_libraries(desired_file: Path) -> tuple[set[str], set[str]]:
    symbol_libs: set[str] = set()
    footprint_libs: set[str] = set()

    with desired_file.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row_num, row in enumerate(reader, start=1):
            if not row:
                continue

            if len(row) < 2:
                print(f"Warning: skipping malformed line {row_num}")
                continue

            lib_type = row[0].strip()
            lib_name = row[1].strip()

            if lib_type == "symbol_library":
                symbol_libs.add(lib_name)
            elif lib_type == "footprint_library":
                footprint_libs.add(lib_name)
            else:
                print(f"Warning: unknown type on line {row_num}: {lib_type}")

    return symbol_libs, footprint_libs


def extract_lib_name_from_line(line: str) -> str | None:
    marker = '(lib (name "'
    start = line.find(marker)
    if start == -1:
        return None

    name_start = start + len(marker)
    name_end = line.find('"', name_start)
    if name_end == -1:
        return None

    return line[name_start:name_end]


def backup_file(path: Path) -> Path:
    """Create a _backup copy of the given file and verify size matches."""
    backup_path = path.with_name(path.name + "_backup")

    shutil.copy2(path, backup_path)

    original_size = path.stat().st_size
    backup_size = backup_path.stat().st_size

    if original_size != backup_size:
        raise RuntimeError(
            f"Backup verification failed for {path.name}: "
            f"original size {original_size} != backup size {backup_size}"
        )

    return backup_path


def rewrite_table_file(
    table_path: Path,
    backup_path: Path,
    desired_names: set[str],
    removed_file_handle,
) -> tuple[int, int]:
    kept_count = 0
    skipped_count = 0

    with backup_path.open("r", encoding="utf-8", errors="replace") as src, \
         table_path.open("w", encoding="utf-8", newline="") as dst:

        for line in src:
            lib_name = extract_lib_name_from_line(line)

            if lib_name is None:
                dst.write(line)
                continue

            if lib_name in desired_names:
                dst.write(line)
                kept_count += 1
            else:
                removed_file_handle.write(line)
                skipped_count += 1

    return kept_count, skipped_count


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {Path(sys.argv[0]).name} <desired.txt> <folder_name>")
        return 1

    desired_file = Path(sys.argv[1]).resolve()
    folder = Path(sys.argv[2]).resolve()

    if not desired_file.is_file():
        print(f"Desired file not found: {desired_file}")
        return 1

    if not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 1

    sym_table = folder / "sym-lib-table"
    fp_table = folder / "fp-lib-table"
    removed_file = Path.cwd() / "lib-table-removed-lines.txt"

    if not sym_table.is_file():
        print(f"No sym-lib-table file was found in {folder}")
        return 1

    if not fp_table.is_file():
        print(f"No fp-lib-table file was found in {folder}")
        return 1

    symbol_libs, footprint_libs = load_desired_libraries(desired_file)

    sym_backup = backup_file(sym_table)
    fp_backup = backup_file(fp_table)

    # Open removed-lines file once for both tables
    with removed_file.open("w", encoding="utf-8", newline="") as removed_f:
        sym_kept, sym_skipped = rewrite_table_file(
            sym_table, sym_backup, symbol_libs, removed_f
        )

        fp_kept, fp_skipped = rewrite_table_file(
            fp_table, fp_backup, footprint_libs, removed_f
        )

    print(f"Backed up {sym_table.name} to {sym_backup.name}")
    print(f"Backed up {fp_table.name} to {fp_backup.name}")
    print(f"Removed lines saved to {removed_file.name}")
    print(f"Rewrote {sym_table.name}: kept {sym_kept}, removed {sym_skipped}")
    print(f"Rewrote {fp_table.name}: kept {fp_kept}, removed {fp_skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())