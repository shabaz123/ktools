#!/usr/bin/env python3
"""Plot KiCad AC simulation CSV exports.

Expected input format:
- Semicolon-separated values
- A trailing semicolon at the end of each line is allowed
- First column: frequency
- Remaining columns: one or more signal series, usually named like
  "V(/OUT) (gain)" and/or "V(/OUT) (phase)"
- Optional header row

Supported cases:
- gain only
- phase only
- gain + phase
- up to 5 distinct signals are plotted; any extra signals are ignored

Examples:
    python plot_ac.py ac.csv
    python plot_ac.py ac.csv --title "Frequency response"
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter

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
FIGURE_SIZE_INCHES = (11.6, 5.4)
FIGURE_DPI = 100
GAIN_LINE_WIDTH = 2.4
PHASE_LINE_WIDTH = 2.0
PHASE_LINESTYLE = (0, (2.0, 2.2))
GRID_ALPHA_MAJOR = 0.28
GRID_ALPHA_MINOR = 0.10

MIN_FREQ_HZ = 1e-1
MAX_FREQ_HZ = 1e10
PHASE_YMIN = -180.0
PHASE_YMAX = 180.0
PHASE_TICKS = [-180, -120, -60, 0, 60, 120, 180]

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

HEADER_SUFFIX_RE = re.compile(r"^(.*?)\s*\((gain|phase)\)\s*$", re.IGNORECASE)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


@dataclass
class SignalData:
    name: str
    gain: List[float] = field(default_factory=list)
    phase: List[float] = field(default_factory=list)
    has_gain: bool = False
    has_phase: bool = False


@dataclass
class AcData:
    frequency_hz: List[float]
    signals: List[SignalData]


@dataclass
class ColumnSpec:
    signal_name: str
    kind: str  # 'gain' or 'phase'
    column_index: int



def sanitize_frequency_range(values: Sequence[float]) -> List[float]:
    cleaned = [v for v in values if math.isfinite(v) and v > 0]
    if not cleaned:
        raise ValueError("No positive frequency values were found.")
    return cleaned



def format_frequency_hz(value: float, _pos=None) -> str:
    if value <= 0 or not math.isfinite(value):
        return ""

    units = [
        (1e9, "GHz"),
        (1e6, "MHz"),
        (1e3, "kHz"),
        (1.0, "Hz"),
    ]

    for scale, suffix in units:
        if value >= scale:
            scaled = value / scale
            if math.isclose(scaled, round(scaled), rel_tol=1e-9, abs_tol=1e-12):
                return f"{int(round(scaled))} {suffix}"
            return f"{scaled:g} {suffix}"

    return f"{value:g} Hz"



def clean_signal_name(text: str) -> str:
    match = HEADER_SUFFIX_RE.match(text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()



def parse_column_header(text: str, fallback_index: int) -> ColumnSpec:
    stripped = text.strip()
    match = HEADER_SUFFIX_RE.match(stripped)
    if match:
        return ColumnSpec(signal_name=match.group(1).strip(), kind=match.group(2).lower(), column_index=fallback_index)

    # Fallback: if the header has no explicit suffix, treat it as gain.
    return ColumnSpec(signal_name=clean_signal_name(stripped) or f"Signal {fallback_index}", kind="gain", column_index=fallback_index)



def build_default_header(column_count: int) -> List[str]:
    header = ["frequency"]
    for index in range(1, column_count):
        header.append(f"Signal {index} (gain)")
    return header


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------



def parse_semicolon_file(path: Path) -> AcData:
    rows: List[List[str]] = []

    with path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter=";")
        for raw_row in reader:
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
        header = build_default_header(len(first_row))
        data_rows = rows

    if len(header) < 2:
        raise ValueError("Expected at least two columns: frequency plus one signal column.")

    header = header[: len(first_row)]
    column_specs = [parse_column_header(text, idx) for idx, text in enumerate(header[1:], start=1)]

    signal_order: List[str] = []
    signals_by_name: Dict[str, SignalData] = {}
    kept_specs: List[ColumnSpec] = []

    for spec in column_specs:
        if spec.signal_name not in signals_by_name:
            if len(signal_order) >= MAX_SIGNALS:
                continue
            signal_order.append(spec.signal_name)
            signals_by_name[spec.signal_name] = SignalData(name=spec.signal_name)
        kept_specs.append(spec)

    if not kept_specs:
        raise ValueError("No signal columns were found.")

    frequency_hz: List[float] = []

    for line_number, row in enumerate(data_rows, start=2 if has_header else 1):
        if len(row) < len(header):
            raise ValueError(f"Row {line_number} has {len(row)} column(s), expected at least {len(header)}.")

        try:
            freq = float(row[0])
        except ValueError as exc:
            raise ValueError(f"Non-numeric frequency value on row {line_number}: {row[0]!r}") from exc

        if not math.isfinite(freq) or freq <= 0:
            # Logarithmic axis cannot use zero or negative values.
            continue
        if freq < MIN_FREQ_HZ or freq > MAX_FREQ_HZ:
            continue

        frequency_hz.append(freq)

        for spec in kept_specs:
            try:
                value = float(row[spec.column_index])
            except ValueError as exc:
                raise ValueError(
                    f"Non-numeric value found on row {line_number}, column {spec.column_index + 1}: {row[spec.column_index]!r}"
                ) from exc

            signal = signals_by_name[spec.signal_name]
            if spec.kind == "gain":
                signal.gain.append(value)
                signal.has_gain = True
            else:
                signal.phase.append(value)
                signal.has_phase = True

        # Keep list lengths aligned for optional columns.
        for signal_name in signal_order:
            signal = signals_by_name[signal_name]
            if len(signal.gain) < len(frequency_hz):
                signal.gain.append(math.nan)
            if len(signal.phase) < len(frequency_hz):
                signal.phase.append(math.nan)

    if not frequency_hz:
        raise ValueError("No usable data rows remained after filtering invalid frequencies.")

    signals = [signals_by_name[name] for name in signal_order]
    return AcData(frequency_hz=frequency_hz, signals=signals)


# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------



def finite_values(values: Sequence[float]) -> List[float]:
    return [v for v in values if math.isfinite(v)]



def nice_db_limits(values: Sequence[float]) -> tuple[float, float]:
    finite = finite_values(values)
    if not finite:
        return -20.0, 20.0

    vmin = min(finite)
    vmax = max(finite)

    if math.isclose(vmin, vmax):
        pad = 6.0 if vmin == 0 else max(3.0, abs(vmin) * 0.10)
        vmin -= pad
        vmax += pad
    else:
        span = vmax - vmin
        pad = max(1.5, span * 0.08)
        vmin -= pad
        vmax += pad

    candidates = [1, 2, 5, 10, 20, 25, 50]
    target_step = max((vmax - vmin) / 8.0, 1e-9)
    step = min(candidates, key=lambda c: abs(c - target_step))

    lower = step * math.floor(vmin / step)
    upper = step * math.ceil(vmax / step)

    if math.isclose(lower, upper):
        upper = lower + step

    return lower, upper


class AcPlotter:
    def __init__(self, csv_path: Path, title: Optional[str] = None):
        self.csv_path = csv_path
        self.title = title
        self.fig = None
        self.ax_gain = None
        self.ax_phase = None

    def configure_theme(self) -> None:
        plt.rcParams.update(DARK_THEME)

    def _connect_replot_shortcut(self) -> None:
        assert self.fig is not None

        def on_key_press(event):
            if event.key and event.key.lower() == "r":
                self.replot()

        self.fig.canvas.mpl_connect("key_press_event", on_key_press)

    def _create_axes_if_needed(self) -> None:
        if self.ax_gain is not None and self.ax_phase is not None:
            return

        self.fig, self.ax_gain = plt.subplots(figsize=FIGURE_SIZE_INCHES, dpi=FIGURE_DPI)
        self.ax_phase = self.ax_gain.twinx()
        self.fig.subplots_adjust(left=0.10, right=0.76, bottom=0.18, top=0.90)
        self._connect_replot_shortcut()

    def _style_axes(self) -> None:
        assert self.ax_gain is not None
        assert self.ax_phase is not None

        self.ax_gain.set_xscale("log")
        self.ax_gain.grid(True, which="major", linestyle="-", linewidth=0.8, alpha=GRID_ALPHA_MAJOR)
        self.ax_gain.grid(True, which="minor", linestyle="-", linewidth=0.5, alpha=GRID_ALPHA_MINOR)

        self.ax_gain.xaxis.set_major_locator(LogLocator(base=10.0, subs=(1.0,)))
        self.ax_gain.xaxis.set_minor_locator(LogLocator(base=10.0, subs=tuple(range(2, 10))))
        self.ax_gain.xaxis.set_minor_formatter(NullFormatter())
        self.ax_gain.xaxis.set_major_formatter(FuncFormatter(format_frequency_hz))

        self.ax_phase.set_ylim(PHASE_YMIN, PHASE_YMAX)
        self.ax_phase.yaxis.set_major_locator(FixedLocator(PHASE_TICKS))
        self.ax_phase.yaxis.set_label_position("right")
        self.ax_phase.yaxis.tick_right()
        self.ax_phase.spines["right"].set_position(("axes", 1.0))
        self.ax_phase.spines["left"].set_visible(False)
        self.ax_phase.grid(False)

        for spine in self.ax_gain.spines.values():
            spine.set_linewidth(1.0)
        for spine in self.ax_phase.spines.values():
            spine.set_linewidth(1.0)

        self.ax_gain.tick_params(axis="both", which="major", length=6, width=1.0)
        self.ax_gain.tick_params(axis="both", which="minor", length=3, width=0.7)
        self.ax_phase.tick_params(axis="y", which="major", length=6, width=1.0)

    def replot(self, _event=None) -> None:
        data = parse_semicolon_file(self.csv_path)
        self._create_axes_if_needed()

        assert self.ax_gain is not None
        assert self.ax_phase is not None
        assert self.fig is not None

        self.ax_gain.clear()
        self.ax_phase.clear()

        freq_values = sanitize_frequency_range(data.frequency_hz)
        gain_values_all: List[float] = []
        legend_handles: List[Line2D] = []

        for index, signal in enumerate(data.signals):
            color = SIGNAL_COLORS[index % len(SIGNAL_COLORS)]

            if signal.has_gain:
                gain_values_all.extend(finite_values(signal.gain))
                self.ax_gain.plot(
                    freq_values,
                    signal.gain,
                    color=color,
                    linewidth=GAIN_LINE_WIDTH,
                    linestyle="-",
                    solid_capstyle="round",
                    label=signal.name,
                )

            if signal.has_phase:
                self.ax_phase.plot(
                    freq_values,
                    signal.phase,
                    color=color,
                    linewidth=PHASE_LINE_WIDTH,
                    linestyle=PHASE_LINESTYLE,
                    dash_capstyle="round",
                    alpha=0.95,
                )

            legend_handles.append(
                Line2D([0], [0], color=color, linewidth=GAIN_LINE_WIDTH, linestyle="-", solid_capstyle="round")
            )

        ymin, ymax = nice_db_limits(gain_values_all)
        self.ax_gain.set_xlim(max(min(freq_values), MIN_FREQ_HZ), min(max(freq_values), MAX_FREQ_HZ))
        self.ax_gain.set_ylim(ymin, ymax)

        self.ax_gain.set_xlabel("Frequency", fontsize=13, fontweight="bold")
        self.ax_gain.set_ylabel("Gain (dB)", fontsize=13, fontweight="bold")
        self.ax_phase.set_ylabel("Phase (deg)", fontsize=13, fontweight="bold", rotation=270, labelpad=18)
        self.ax_phase.yaxis.set_label_position("right")
        self.ax_phase.yaxis.tick_right()

        title = self.title or self.csv_path.name
        self.ax_gain.set_title(title, fontsize=14, fontweight="bold", pad=10)

        if legend_handles:
            legend = self.ax_gain.legend(
                legend_handles,
                [signal.name for signal in data.signals],
                loc="center left",
                bbox_to_anchor=(1.14, 0.5),
                framealpha=0.95,
                borderpad=0.7,
                labelspacing=0.5,
            )
            for leg_line in legend.get_lines():
                leg_line.set_linewidth(GAIN_LINE_WIDTH + 0.4)

        self._style_axes()
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
        description="Plot AC simulation CSV files exported from KiCad or similar tools."
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
        plotter = AcPlotter(args.csv_file, title=args.title)
        plotter.show()
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
