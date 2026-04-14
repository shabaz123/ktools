#!/usr/bin/env python3
"""Plot KiCad transient simulation CSV exports.

Expected input format:
- Semicolon-separated values
- A trailing semicolon at the end of each line is allowed
- First column: time
- Remaining columns: signal amplitudes
- Optional header row

Examples:
    python plot_tran.py tran.csv
    python plot_tran.py tran.csv --title "Transient response"
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# -----------------------------------------------------------------------------
# User-tweakable settings
# -----------------------------------------------------------------------------

SIGNAL_COLORS = [
    "#5cc8ff",  # signal 1
    "#ff6b6b",  # signal 2
    "#ffd166",  # signal 3
    "#95e06c",  # signal 4
    "#c792ea",  # signal 5
]

MAX_SIGNALS = 5
FIGURE_SIZE_INCHES = (9.2, 4.8)  # slightly larger to avoid clipping labels/legend
FIGURE_DPI = 100
LINE_WIDTH = 2.2
GRID_ALPHA_MAJOR = 0.28
GRID_ALPHA_MINOR = 0.10

DARK_THEME = {
    "figure.facecolor": "#111318",
    "axes.facecolor": "#161a22",
    "axes.edgecolor": "#8b93a7",
    "axes.labelcolor": "#e8ecf3",
    "axes.titlecolor": "#f6f8fb",
    "xtick.color": "#d3d9e6",
    "ytick.color": "#d3d9e6",
    "grid.color": "#cfd6e6",
    "text.color": "#eef2f8",
    "legend.facecolor": "#1d2330",
    "legend.edgecolor": "#7d869c",
    "savefig.facecolor": "#111318",
    "savefig.edgecolor": "#111318",
    "font.size": 11,
}

# -----------------------------------------------------------------------------
# Engineering-unit helpers
# -----------------------------------------------------------------------------

PREFIXES = {
    -12: "p",
    -9: "n",
    -6: "u",
    -3: "m",
    0: "",
    3: "k",
    6: "M",
    9: "G",
}


def choose_engineering_scale(values: Sequence[float], allowed_exponents: Sequence[int]) -> Tuple[float, str]:
    """Return (scale_factor, prefix) for display.

    Scaled values are obtained by: displayed = raw / scale_factor
    Example: for mV, scale_factor = 1e-3 and prefix = 'm'.
    """
    finite_values = [abs(v) for v in values if math.isfinite(v)]
    max_abs = max(finite_values, default=0.0)

    if max_abs == 0:
        exponent = 0
    else:
        raw_exponent = int(math.floor(math.log10(max_abs)))
        exponent = 3 * int(math.floor(raw_exponent / 3))
        exponent = min(allowed_exponents, key=lambda e: (abs(e - exponent), abs(e)))

    return 10.0 ** exponent, PREFIXES[exponent]


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------


def is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


class TranData:
    def __init__(self, time_values: List[float], signal_names: List[str], signal_series: List[List[float]]):
        self.time_values = time_values
        self.signal_names = signal_names
        self.signal_series = signal_series



def parse_semicolon_file(path: Path) -> TranData:
    rows: List[List[str]] = []

    with path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter=";")
        for raw_row in reader:
            # Remove empty cells caused by the trailing semicolon and trim whitespace.
            row = [cell.strip() for cell in raw_row]
            while row and row[-1] == "":
                row.pop()

            if not row:
                continue
            if row[0].startswith("#"):
                continue

            rows.append(row)

    if not rows:
        raise ValueError("Input file contains no usable data rows.")

    first_row = rows[0]
    has_header = not is_number(first_row[0])

    if has_header:
        header = first_row
        data_rows = rows[1:]
        if not data_rows:
            raise ValueError("Header found, but no data rows were present.")
    else:
        header = ["time"] + [f"Signal {i}" for i in range(1, len(first_row))]
        data_rows = rows

    if len(header) < 2:
        raise ValueError("Expected at least two columns: time plus one signal.")

    expected_columns = len(header)
    trimmed_columns = min(expected_columns, MAX_SIGNALS + 1)
    header = header[:trimmed_columns]

    time_values: List[float] = []
    signal_series: List[List[float]] = [[] for _ in range(trimmed_columns - 1)]

    for line_number, row in enumerate(data_rows, start=2 if has_header else 1):
        row = row[:trimmed_columns]
        if len(row) < trimmed_columns:
            raise ValueError(
                f"Row {line_number} has {len(row)} column(s), expected at least {trimmed_columns}."
            )

        try:
            time_values.append(float(row[0]))
            for index in range(1, trimmed_columns):
                signal_series[index - 1].append(float(row[index]))
        except ValueError as exc:
            raise ValueError(f"Non-numeric value found on row {line_number}: {row}") from exc

    signal_names = header[1:]
    return TranData(time_values=time_values, signal_names=signal_names, signal_series=signal_series)


# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------


def all_signal_values(series: Sequence[Sequence[float]]) -> List[float]:
    values: List[float] = []
    for sig in series:
        values.extend(sig)
    return values


class TranPlotter:
    def __init__(self, csv_path: Path, title: str | None = None):
        self.csv_path = csv_path
        self.title = title
        self.fig = None
        self.ax = None

    def configure_theme(self) -> None:
        plt.rcParams.update(DARK_THEME)

    def _nice_limits(self, values: Sequence[float], prefer_symmetric: bool) -> Tuple[float, float]:
        locator = MaxNLocator(nbins=9, steps=[1, 2, 2.5, 5, 10], symmetric=prefer_symmetric)
        vmin = min(values)
        vmax = max(values)

        if math.isclose(vmin, vmax):
            pad = 1.0 if vmin == 0 else abs(vmin) * 0.15
            vmin -= pad
            vmax += pad

        return tuple(locator.view_limits(vmin, vmax))

    def _apply_axes_styling(self, x_crosses_zero: bool, y_crosses_zero: bool) -> None:
        assert self.ax is not None

        self.ax.grid(True, which="major", linestyle="-", linewidth=0.8, alpha=GRID_ALPHA_MAJOR)
        self.ax.minorticks_on()
        self.ax.grid(True, which="minor", linestyle="-", linewidth=0.5, alpha=GRID_ALPHA_MINOR)

        self.ax.xaxis.set_major_locator(MaxNLocator(nbins=12, steps=[1, 2, 2.5, 5, 10]))
        self.ax.yaxis.set_major_locator(
            MaxNLocator(nbins=9, steps=[1, 2, 2.5, 5, 10], symmetric=y_crosses_zero)
        )

        for spine in self.ax.spines.values():
            spine.set_linewidth(1.0)

        self.ax.tick_params(axis="both", which="major", length=6, width=1.0)
        self.ax.tick_params(axis="both", which="minor", length=3, width=0.7)

        if x_crosses_zero:
            self.ax.axvline(0.0, linewidth=1.0, alpha=0.20)
        if y_crosses_zero:
            self.ax.axhline(0.0, linewidth=1.0, alpha=0.20)

    def replot(self, _event=None) -> None:
        data = parse_semicolon_file(self.csv_path)

        time_scale, time_prefix = choose_engineering_scale(data.time_values, allowed_exponents=[-9, -6, -3, 0])
        amp_values = all_signal_values(data.signal_series)
        amp_scale, amp_prefix = choose_engineering_scale(
            amp_values, allowed_exponents=[-12, -9, -6, -3, 0, 3, 6]
        )

        scaled_time = [value / time_scale for value in data.time_values]
        scaled_signals = [[value / amp_scale for value in signal] for signal in data.signal_series]

        x_label_unit = {
            "n": "nsec",
            "u": "usec",
            "m": "msec",
            "": "sec",
        }.get(time_prefix, f"{time_prefix}sec")
        y_label_unit = f"{amp_prefix}V" if amp_prefix else "V"

        x_crosses_zero = min(scaled_time) < 0 < max(scaled_time)
        y_crosses_zero = min(all_signal_values(scaled_signals)) < 0 < max(all_signal_values(scaled_signals))

        if self.ax is None:
            self.fig, self.ax = plt.subplots(figsize=FIGURE_SIZE_INCHES, dpi=FIGURE_DPI)
            self.fig.subplots_adjust(left=0.12, right=0.80, bottom=0.16, top=0.90)

            def on_key_press(event):
                if event.key and event.key.lower() == "r":
                    self.replot()

            self.fig.canvas.mpl_connect("key_press_event", on_key_press)

        assert self.ax is not None
        self.ax.clear()

        for index, (name, signal) in enumerate(zip(data.signal_names, scaled_signals)):
            self.ax.plot(
                scaled_time,
                signal,
                label=name,
                linewidth=LINE_WIDTH,
                color=SIGNAL_COLORS[index % len(SIGNAL_COLORS)],
                solid_capstyle="round",
            )

        x_limits = self._nice_limits(scaled_time, prefer_symmetric=False)
        y_limits = self._nice_limits(all_signal_values(scaled_signals), prefer_symmetric=y_crosses_zero)
        self.ax.set_xlim(*x_limits)
        self.ax.set_ylim(*y_limits)

        self.ax.set_xlabel(f"Time ({x_label_unit})", fontsize=13, fontweight="bold")
        self.ax.set_ylabel(f"Amplitude ({y_label_unit})", fontsize=13, fontweight="bold")

        title = self.title or self.csv_path.name
        self.ax.set_title(title, fontsize=14, fontweight="bold", pad=10)

        legend = self.ax.legend(
            loc="center left",
            bbox_to_anchor=(1.01, 0.5),
            framealpha=0.95,
            borderpad=0.7,
            labelspacing=0.5,
        )
        for leg_line in legend.get_lines():
            leg_line.set_linewidth(LINE_WIDTH + 0.5)

        self._apply_axes_styling(x_crosses_zero=x_crosses_zero, y_crosses_zero=y_crosses_zero)

        # Re-apply padding after artists are created so ylabel and legend are less likely to be clipped.
        self.fig.subplots_adjust(left=0.12, right=0.80, bottom=0.16, top=0.90)
        self.fig.canvas.draw_idle()

    def show(self) -> None:
        self.configure_theme()
        self.replot()
        plt.show()


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot transient simulation CSV files exported from KiCad or similar tools."
    )
    parser.add_argument("csv_file", type=Path, help="Input semicolon-separated CSV file")
    parser.add_argument("--title", default=None, help="Optional chart title")
    return parser



def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.csv_file.exists():
        print(f"Error: file not found: {args.csv_file}", file=sys.stderr)
        return 1

    try:
        plotter = TranPlotter(args.csv_file, title=args.title)
        plotter.show()
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
