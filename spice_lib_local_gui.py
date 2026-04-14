#!/usr/bin/env python3
"""
KiCad SPICE Localizer GUI

rev 1 - shabaz - April 2026

WARNING - This tool modifies schematic files. Always back up your project before using it.

A small desktop tool for making KiCad schematic SPICE library references local
to the project folder. It scans a chosen project directory for .kicad_sch files,
shows Sim.Library properties found in symbol definitions and instances, copies
referenced model files into <project>/spice_lib, and can rewrite selected
Sim.Library paths to relative paths such as:

    spice_lib\\BC549.lib

Designed for KiCad schematic text files without requiring KiCad itself.

Tested against KiCad 10-style .kicad_sch text structure where Sim.Library may
appear inside:
- lib_symbols / symbol definitions
- placed symbol instances elsewhere in the file
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Iterable


APP_TITLE = "KiCad SPICE Localizer"
LOCAL_LIB_DIRNAME = "spice_lib"
BACKUP_SUFFIX = ".kicad_sch_before_script"
SIM_LIBRARY_RE = re.compile(r'^(?P<prefix>\s*\(property\s+"Sim\.Library"\s+")(?P<value>.*?)(?P<suffix>".*)$')


@dataclass
class SimLibraryEntry:
    line_index: int
    line_number: int
    raw_value: str
    normalized_source: str
    basename: str
    scope: str  # "instance" or "symbol_def"


class SchematicParseError(Exception):
    pass


class SchematicAnalyzer:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lines: list[str] = []
        self.symbol_defs: list[SimLibraryEntry] = []
        self.instances: list[SimLibraryEntry] = []

    def load(self) -> None:
        try:
            self.lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            self.lines = self.path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        self._parse()

    def _parse(self) -> None:
        self.symbol_defs = []
        self.instances = []

        context_stack: list[str] = []
        in_quote = False
        escape = False

        for index, line in enumerate(self.lines):
            stripped = line.strip()

            # Classify property line using current context *before* updating nesting
            match = SIM_LIBRARY_RE.match(line)
            if match:
                raw_value = match.group("value")
                normalized = self._normalize_kicad_path(raw_value)
                entry = SimLibraryEntry(
                    line_index=index,
                    line_number=index + 1,
                    raw_value=raw_value,
                    normalized_source=normalized,
                    basename=Path(normalized).name if normalized else "",
                    scope="symbol_def" if "lib_symbols" in context_stack else "instance",
                )
                if entry.scope == "symbol_def":
                    self.symbol_defs.append(entry)
                else:
                    self.instances.append(entry)

            # Update simplified s-expression context stack.
            i = 0
            while i < len(line):
                ch = line[i]
                if escape:
                    escape = False
                    i += 1
                    continue
                if ch == '\\' and in_quote:
                    escape = True
                    i += 1
                    continue
                if ch == '"':
                    in_quote = not in_quote
                    i += 1
                    continue
                if not in_quote:
                    if ch == '(':
                        token = self._read_token_after_paren(line, i + 1)
                        context_stack.append(token)
                    elif ch == ')':
                        if context_stack:
                            context_stack.pop()
                i += 1

        if in_quote:
            raise SchematicParseError(f"Unbalanced quote while parsing {self.path}")

    @staticmethod
    def _read_token_after_paren(line: str, start: int) -> str:
        j = start
        while j < len(line) and line[j].isspace():
            j += 1
        k = j
        while k < len(line) and not line[k].isspace() and line[k] not in '()':
            k += 1
        return line[j:k]

    @staticmethod
    def _normalize_kicad_path(value: str) -> str:
        # KiCad schematic text stores backslashes escaped as double backslashes.
        return value.replace('\\\\', '\\')

    @staticmethod
    def _encode_kicad_path(value: str) -> str:
        return value.replace('\\', '\\\\')

    def all_entries(self) -> list[SimLibraryEntry]:
        return [*self.symbol_defs, *self.instances]

    def unique_source_paths(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in self.all_entries():
            if entry.normalized_source and entry.normalized_source not in seen:
                seen.add(entry.normalized_source)
                ordered.append(entry.normalized_source)
        return ordered

    def ensure_backup(self) -> Path:
        backup_path = self.path.with_name(self.path.name + BACKUP_SUFFIX)
        shutil.copy2(self.path, backup_path)

        original_size = self.path.stat().st_size
        backup_size = backup_path.stat().st_size
        if original_size != backup_size:
            raise IOError(
                f"Backup size mismatch for {self.path.name}: original={original_size}, backup={backup_size}"
            )
        return backup_path

    def rewrite(self, update_instances: bool, update_symbol_defs: bool, local_dir_name: str = LOCAL_LIB_DIRNAME) -> tuple[int, Path]:
        if not update_instances and not update_symbol_defs:
            return 0, self.path.with_name(self.path.name + BACKUP_SUFFIX)

        backup_path = self.ensure_backup()
        backup_lines = backup_path.read_text(encoding="utf-8").splitlines(keepends=True)
        self.lines = backup_lines[:]  # work from backup contents
        self._parse()

        replacements = 0
        targets: list[SimLibraryEntry] = []
        if update_symbol_defs:
            targets.extend(self.symbol_defs)
        if update_instances:
            targets.extend(self.instances)

        for entry in targets:
            basename = Path(entry.normalized_source).name
            if not basename:
                continue
            new_value = f"{local_dir_name}\\{basename}"
            encoded_new_value = self._encode_kicad_path(new_value)
            old_line = self.lines[entry.line_index]
            match = SIM_LIBRARY_RE.match(old_line)
            if not match:
                continue
            new_line = f"{match.group('prefix')}{encoded_new_value}{match.group('suffix')}\n"
            if old_line != new_line:
                self.lines[entry.line_index] = new_line
                replacements += 1

        self.path.write_text("".join(self.lines), encoding="utf-8", newline="")
        return replacements, backup_path


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x760")
        self.minsize(980, 620)

        self.project_dir: Path | None = None
        self.schematic_files: list[Path] = []
        self.current_analyzer: SchematicAnalyzer | None = None

        self._build_ui()
        self.after_idle(self.show_startup_message)

    def show_startup_message(self):
        messagebox.showinfo(
            APP_TITLE,
            "Warning, this tool modifies schematic files.\n\n"
            "Always back up your project before using it.\n"
        )

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Project folder:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.project_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.project_var).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(top, text="Open Folder", command=self.choose_folder).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(top, text="Analyze", command=self.analyze_selected).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(top, text="Refresh", command=self.refresh_project).grid(row=0, column=4)

        middle = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        middle.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # Left: schematic list
        left = ttk.Labelframe(middle, text="Schematic files", padding=8)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.schematic_list = tk.Listbox(left, exportselection=False)
        self.schematic_list.grid(row=0, column=0, sticky="nsew")
        self.schematic_list.bind("<<ListboxSelect>>", lambda _e: self._update_button_state())
        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.schematic_list.yview)
        left_scroll.grid(row=0, column=1, sticky="ns")
        self.schematic_list.configure(yscrollcommand=left_scroll.set)
        middle.add(left, weight=1)

        # Right: local folder contents
        right = ttk.Labelframe(middle, text=f"Local {LOCAL_LIB_DIRNAME} contents", padding=8)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.local_list = tk.Listbox(right)
        self.local_list.grid(row=0, column=0, sticky="nsew")
        right_scroll = ttk.Scrollbar(right, orient="vertical", command=self.local_list.yview)
        right_scroll.grid(row=0, column=1, sticky="ns")
        self.local_list.configure(yscrollcommand=right_scroll.set)
        middle.add(right, weight=1)

        bottom = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        bottom.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        inst_frame = ttk.Labelframe(bottom, text="Instances", padding=8)
        inst_frame.columnconfigure(0, weight=1)
        inst_frame.rowconfigure(0, weight=1)
        self.instances_tree = self._make_tree(inst_frame)
        bottom.add(inst_frame, weight=1)

        sym_frame = ttk.Labelframe(bottom, text="Symbol definitions", padding=8)
        sym_frame.columnconfigure(0, weight=1)
        sym_frame.rowconfigure(0, weight=1)
        self.symbols_tree = self._make_tree(sym_frame)
        bottom.add(sym_frame, weight=1)

        actions = ttk.Frame(self, padding=(10, 0, 10, 10))
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)

        self.copy_button = ttk.Button(actions, text="Copy Libs to Local", command=self.copy_libs_to_local)
        self.copy_button.grid(row=0, column=0, padx=(0, 8))

        self.make_instances_button = ttk.Button(actions, text="Make Instances Local", command=self.make_instances_local)
        self.make_instances_button.grid(row=0, column=1, padx=(0, 8))

        self.make_symbols_button = ttk.Button(actions, text="Make Symbol Definitions Local", command=self.make_symbol_defs_local)
        self.make_symbols_button.grid(row=0, column=2, padx=(0, 8))

        self.make_both_button = ttk.Button(actions, text="Make Both Local", command=self.make_both_local)
        self.make_both_button.grid(row=0, column=3, padx=(0, 8))

        self.status_var = tk.StringVar(value="Choose a project folder.")
        ttk.Label(actions, textvariable=self.status_var, anchor="w").grid(row=0, column=4, sticky="ew")

        self._update_button_state()

    def _make_tree(self, parent: ttk.Frame) -> ttk.Treeview:
        columns = ("line", "basename", "source")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        tree.heading("line", text="Line")
        tree.heading("basename", text="File", anchor="w")
        tree.heading("source", text="Current Sim.Library Usage", anchor="w")
        tree.column("line", width=65, anchor="center", stretch=False)
        tree.column("basename", width=150, anchor="w", stretch=False)
        tree.column("source", width=500, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select KiCad project folder")
        if not selected:
            return
        self.load_project(Path(selected))

    def load_project(self, folder: Path) -> None:
        folder = folder.resolve()
        self.project_dir = folder
        self.project_var.set(str(folder))
        self.schematic_files = sorted(folder.rglob("*.kicad_sch"))
        self.schematic_list.delete(0, tk.END)

        if self.schematic_files:
            self._ensure_local_lib_dir(create=True)
            for path in self.schematic_files:
                try:
                    rel = path.relative_to(folder)
                except ValueError:
                    rel = path
                self.schematic_list.insert(tk.END, str(rel))
            self.schematic_list.selection_set(0)
            self.schematic_list.activate(0)
            self.status_var.set(f"Found {len(self.schematic_files)} schematic file(s).")
        else:
            self.status_var.set("No .kicad_sch files found in that folder.")
            messagebox.showinfo(APP_TITLE, "No .kicad_sch files were found in the selected folder.")

        self.refresh_local_list()
        self.clear_analysis_views()
        self._update_button_state()

    def refresh_project(self) -> None:
        path_text = self.project_var.get().strip()
        if not path_text:
            self.status_var.set("Choose a project folder first.")
            return
        folder = Path(path_text)
        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, "The selected project folder no longer exists.")
            return
        self.load_project(folder)

    def _ensure_local_lib_dir(self, create: bool) -> Path | None:
        if self.project_dir is None:
            return None
        local_dir = self.project_dir / LOCAL_LIB_DIRNAME
        if create:
            local_dir.mkdir(parents=True, exist_ok=True)
        return local_dir

    def refresh_local_list(self) -> None:
        self.local_list.delete(0, tk.END)
        local_dir = self._ensure_local_lib_dir(create=bool(self.schematic_files))
        if local_dir is None or not local_dir.exists():
            return
        files = sorted(p for p in local_dir.iterdir() if p.is_file())
        for path in files:
            self.local_list.insert(tk.END, path.name)
        if not files:
            self.local_list.insert(tk.END, "<empty>")

    def clear_analysis_views(self) -> None:
        for tree in (self.instances_tree, self.symbols_tree):
            for item in tree.get_children():
                tree.delete(item)
        self.current_analyzer = None

    def selected_schematic(self) -> Path | None:
        if not self.schematic_files:
            return None
        selection = self.schematic_list.curselection()
        if not selection:
            return None
        index = selection[0]
        return self.schematic_files[index]

    def analyze_selected(self) -> None:
        schematic = self.selected_schematic()
        # Check for KiCad lock file
        if self.project_dir is not None:
            lock_files = list(self.project_dir.glob("*.lck"))
            if lock_files:
                messagebox.showwarning(
                    APP_TITLE,
                    "The project is still open in KiCad (.lck file is present).\n\n"
                    "Select File -> Close Project in KiCad, then click Analyze again."
                )
                return
        if schematic is None:
            messagebox.showinfo(APP_TITLE, "Select a schematic file first.")
            return
        try:
            analyzer = SchematicAnalyzer(schematic)
            analyzer.load()
            self.current_analyzer = analyzer
            self.populate_tree(self.instances_tree, analyzer.instances)
            self.populate_tree(self.symbols_tree, analyzer.symbol_defs)
            self.refresh_local_list()
            self.status_var.set(
                f"Analyzed {schematic.name}: {len(analyzer.instances)} instance entr{'y' if len(analyzer.instances)==1 else 'ies'}, "
                f"{len(analyzer.symbol_defs)} symbol definition entr{'y' if len(analyzer.symbol_defs)==1 else 'ies'}."
            )
        except Exception as exc:
            self.current_analyzer = None
            self.clear_analysis_views()
            messagebox.showerror(APP_TITLE, f"Failed to analyze schematic:\n\n{exc}")
            self.status_var.set("Analysis failed.")

        self._update_button_state()

    def populate_tree(self, tree: ttk.Treeview, entries: Iterable[SimLibraryEntry]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for entry in entries:
            tree.insert(
                "",
                tk.END,
                values=(entry.line_number, entry.basename or "<none>", entry.normalized_source),
            )

    def copy_libs_to_local(self) -> None:
        if not self._require_analysis():
            return
        assert self.current_analyzer is not None
        local_dir = self._ensure_local_lib_dir(create=True)
        assert local_dir is not None

        copied = 0
        failed: list[str] = []

        for source_str in self.current_analyzer.unique_source_paths():
            src = Path(source_str)
            if not src.is_file():
                failed.append(f"Missing: {source_str}")
                continue
            dst = local_dir / src.name
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception as exc:
                failed.append(f"{source_str} -> {dst.name}: {exc}")

        self.refresh_local_list()

        if failed:
            details = "\n".join(failed[:20])
            messagebox.showwarning(
                APP_TITLE,
                f"Copied {copied} file(s), but some copies failed:\n\n{details}",
            )
            self.status_var.set(f"Copied {copied} file(s); {len(failed)} failed.")
        else:
            self.status_var.set(f"Copied {copied} library file(s) into {LOCAL_LIB_DIRNAME}.")

    def make_instances_local(self) -> None:
        self._rewrite_current(update_instances=True, update_symbol_defs=False)

    def make_symbol_defs_local(self) -> None:
        self._rewrite_current(update_instances=False, update_symbol_defs=True)

    def make_both_local(self) -> None:
        self._rewrite_current(update_instances=True, update_symbol_defs=True)

    def _rewrite_current(self, update_instances: bool, update_symbol_defs: bool) -> None:
        if not self._require_analysis():
            return
        assert self.current_analyzer is not None

        target_desc_parts = []
        if update_instances:
            target_desc_parts.append("instance")
        if update_symbol_defs:
            target_desc_parts.append("symbol definition")
        target_desc = " and ".join(target_desc_parts)

        try:
            replacements, backup_path = self.current_analyzer.rewrite(
                update_instances=update_instances,
                update_symbol_defs=update_symbol_defs,
                local_dir_name=LOCAL_LIB_DIRNAME,
            )
            self.analyze_selected()
            self.status_var.set(
                f"Rewrote {replacements} {target_desc} Sim.Library entr{'y' if replacements == 1 else 'ies'} in "
                f"{self.current_analyzer.path.name}. Backup: {backup_path.name}"
            )
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Failed to rewrite schematic:\n\n{exc}")
            self.status_var.set("Rewrite failed.")

    def _require_analysis(self) -> bool:
        if self.project_dir is None or not self.schematic_files:
            messagebox.showinfo(APP_TITLE, "Open a project folder containing at least one .kicad_sch file first.")
            return False
        if self.current_analyzer is None:
            messagebox.showinfo(APP_TITLE, "Select a schematic and click Analyze first.")
            return False
        return True

    def _update_button_state(self) -> None:
        has_project = self.project_dir is not None and bool(self.schematic_files)
        has_analysis = self.current_analyzer is not None
        analyze_state = "normal" if has_project and self.selected_schematic() is not None else "disabled"
        active_state = "normal" if has_analysis else "disabled"

        for button in (
            self.copy_button,
            self.make_instances_button,
            self.make_symbols_button,
            self.make_both_button,
        ):
            button.configure(state=active_state)

        # Analyze button is the third child in the top frame, but we avoid brittle widget indexing.
        # Its state is not critical for function, so leave always enabled if project exists.
        # The command itself checks selection.


def main() -> int:
    # Optional convenience: allow folder path as first command-line argument.
    app = App()
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1])
        if candidate.is_dir():
            app.load_project(candidate)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
