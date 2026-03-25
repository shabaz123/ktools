#!/usr/bin/env python
"""
list-libs.py

Creates lib-list.txt in the target folder by reading:
- sym-lib-table
- fp-lib-table

For each symbol library found, writes:
symbol_library,"<name>"

For each footprint library found, writes:
footprint_library,"<name>"

Usage:
    python list-libs.py
    python list-libs.py /path/to/folder
Example:
    python list-libs.py C:/DEV/vhd_mounts/kicad/10.0/share/kicad/template
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


LIB_NAME_PATTERN = re.compile(r'\(lib\s+\(name\s+"([^"]+)"\)')


def extract_library_names(table_path: Path) -> list[str]:
    """Extract library names from a KiCad lib table file."""
    try:
        text = table_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = table_path.read_text(encoding="utf-8", errors="replace")

    return LIB_NAME_PATTERN.findall(text)


def main() -> int:
    if len(sys.argv) > 2:
        print(f"Usage: {Path(sys.argv[0]).name} [folder_path]")
        return 1

    folder = Path(sys.argv[1]) if len(sys.argv) == 2 else Path.cwd()
    folder = folder.resolve()

    sym_lib_table = folder / "sym-lib-table"
    fp_lib_table = folder / "fp-lib-table"
    output_file = Path.cwd() / "lib-list.txt"

    symbol_names: list[str] = []
    footprint_names: list[str] = []

    if sym_lib_table.is_file():
        symbol_names = extract_library_names(sym_lib_table)
    else:
        print(f'No sym-lib-table file was found in {folder}')

    if fp_lib_table.is_file():
        footprint_names = extract_library_names(fp_lib_table)
    else:
        print(f'No fp-lib-table file was found in {folder}')

    with output_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)

        for name in symbol_names:
            writer.writerow(["symbol_library", name])

        for name in footprint_names:
            writer.writerow(["footprint_library", name])

    print(f"Symbol libraries found: {len(symbol_names)}")
    print(f"Footprint libraries found: {len(footprint_names)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
