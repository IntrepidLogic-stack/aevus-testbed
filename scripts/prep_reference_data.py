"""Prepare public reference datasets into the normalized replay-CSV format.

Converts the REAL raw downloads into the ``frame,metric,value,unit,group`` CSV
that ReferenceReplayCollector streams. This script fabricates nothing — it
errors out if the raw files are missing. Download the sources first (see
reference_data/README.md), then run:

    python scripts/prep_reference_data.py morris  path/to/Gas_Pipeline.arff
    python scripts/prep_reference_data.py cwru     path/to/IR007_0.mat --label inner_race

Sources (verify current hosting + license before use):
  * Morris ICS gas-pipeline dataset — Mississippi State / UAH (T. Morris).
  * CWRU Bearing Data Center — Case Western Reserve University.

Both are REAL recorded lab/testbed data. Output is tagged group "reference:*"
so the platform labels it ``reference`` — never live, simulated, or Killdeer.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "reference_data" / "prepped"


def _write_frames(rows: list[dict[str, object]], out_path: Path) -> None:
    """Write normalized frame rows to a replay CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["frame", "metric", "value", "unit", "group"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len({r['frame'] for r in rows})} frames -> {out_path}")


def _find_col(names: list[str], *needles: str) -> str | None:
    """Fuzzy-match a column name containing all needles (case-insensitive)."""
    for n in names:
        low = n.lower()
        if all(nd in low for nd in needles):
            return n
    return None


def prep_morris(arff_path: Path, out_path: Path) -> None:
    """Morris gas-pipeline ICS dataset -> process frames (real Modbus values).

    Maps the dataset's process columns to platform metrics: pipe pressure (PV),
    setpoint, pump/solenoid state, control mode, and the normal/attack label.
    Column names vary across releases, so we fuzzy-match rather than hard-code.
    """
    if not arff_path.exists():
        sys.exit(f"raw Morris file not found: {arff_path} — download it first (see README)")
    try:
        from scipy.io import arff  # type: ignore
    except ImportError:
        sys.exit("scipy required: pip install scipy")

    data, meta = arff.loadarff(str(arff_path))
    names = list(meta.names())
    cols = {
        "pipe_pressure": (_find_col(names, "pressure") or _find_col(names, "measurement"), "PSI"),
        "setpoint": (_find_col(names, "setpoint"), "PSI"),
        "control_mode": (_find_col(names, "system", "mode") or _find_col(names, "mode"), "state"),
        "pump": (_find_col(names, "pump"), "state"),
        "solenoid": (_find_col(names, "solenoid"), "state"),
        "label": (_find_col(names, "binary", "result") or _find_col(names, "result"), "state"),
    }
    rows: list[dict[str, object]] = []
    for frame, rec in enumerate(data):
        for metric, (col, unit) in cols.items():
            if not col:
                continue
            raw = rec[col]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            rows.append({"frame": frame, "metric": metric, "value": value, "unit": unit, "group": "reference:morris"})
    if not rows:
        sys.exit("no process columns matched — inspect the ARFF header and adjust _find_col needles")
    _write_frames(rows, out_path)


def prep_cwru(mat_path: Path, out_path: Path, label: str, fs: int = 12000, win: int = 2048) -> None:
    """CWRU bearing vibration -> windowed RMS features (real vibration physics).

    For each non-overlapping window of the drive-end accelerometer signal we
    compute: acceleration RMS (g) and an estimated velocity RMS (mm/s, the
    ISO-10816 condition-monitoring unit) by numerically integrating the
    detrended acceleration. The seeded-fault class is carried as ``fault``.
    """
    if not mat_path.exists():
        sys.exit(f"raw CWRU file not found: {mat_path} — download it first (see README)")
    try:
        import numpy as np  # type: ignore
        from scipy.io import loadmat  # type: ignore
    except ImportError:
        sys.exit("numpy + scipy required: pip install numpy scipy")

    mat = loadmat(str(mat_path))
    de_key = next((k for k in mat if k.endswith("_DE_time")), None)
    if de_key is None:
        sys.exit(f"no *_DE_time drive-end signal in {mat_path}; keys={[k for k in mat if not k.startswith('__')]}")
    sig = np.asarray(mat[de_key]).ravel().astype(float)  # acceleration in g
    g_to_ms2 = 9.80665
    label_code = {"normal": 0, "inner_race": 1, "outer_race": 2, "ball": 3}.get(label, 9)

    rows: list[dict[str, object]] = []
    n_windows = len(sig) // win
    for frame in range(n_windows):
        w = sig[frame * win : (frame + 1) * win]
        accel_rms_g = float(np.sqrt(np.mean(w**2)))
        # FFT-domain integration accel -> velocity: V(f) = A(f) / (j*2*pi*f),
        # band-limited (10 Hz–5 kHz) so the 1/f term doesn't blow up at DC and the
        # bearing-fault band is preserved (naive time integration attenuates it).
        a = (w - w.mean()) * g_to_ms2  # m/s^2
        spec = np.fft.rfft(a)
        freq = np.fft.rfftfreq(len(a), d=1.0 / fs)
        band = (freq >= 10.0) & (freq <= 5000.0)
        vel_spec = np.zeros_like(spec)
        vel_spec[band] = spec[band] / (1j * 2.0 * np.pi * freq[band])
        v = np.fft.irfft(vel_spec, n=len(a))  # velocity m/s
        vel_rms_mm_s = float(np.sqrt(np.mean(v**2)) * 1000.0)
        # PRIMARY bearing-fault indicator = acceleration RMS (g). Rolling-element
        # faults are high-frequency/impulsive, so ISO-10816 *velocity* (mm/s) does
        # NOT flag them — velocity is for imbalance/misalignment. We carry velocity
        # as a labeled ISO-overall secondary so the contrast is visible.
        rows.append(
            {
                "frame": frame,
                "metric": "vibration",
                "value": round(accel_rms_g, 4),
                "unit": "g",
                "group": "reference:cwru",
            }
        )
        rows.append(
            {
                "frame": frame,
                "metric": "vibration_velocity",
                "value": round(vel_rms_mm_s, 3),
                "unit": "mm/s",
                "group": "reference:cwru",
            }
        )
        rows.append(
            {"frame": frame, "metric": "fault", "value": float(label_code), "unit": "state", "group": "reference:cwru"}
        )
    if not rows:
        sys.exit("signal too short for one window")
    _write_frames(rows, out_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="dataset", required=True)

    m = sub.add_parser("morris", help="prep the Morris gas-pipeline ARFF")
    m.add_argument("raw", type=Path)
    m.add_argument("--out", type=Path, default=OUT_DIR / "morris_gas.csv")

    c = sub.add_parser("cwru", help="prep a CWRU bearing .mat")
    c.add_argument("raw", type=Path)
    c.add_argument("--label", default="normal", choices=["normal", "inner_race", "outer_race", "ball"])
    c.add_argument("--out", type=Path, default=OUT_DIR / "cwru_bearing.csv")

    args = ap.parse_args()
    if args.dataset == "morris":
        prep_morris(args.raw, args.out)
    elif args.dataset == "cwru":
        prep_cwru(args.raw, args.out, args.label)


if __name__ == "__main__":
    main()
