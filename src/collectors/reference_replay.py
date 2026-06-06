"""Aevus Testbed — Reference-Dataset Replay Collector.

Streams REAL recorded industrial telemetry from public reference datasets
(e.g. the Mississippi State / UAH Morris gas-pipeline Modbus ICS dataset and the
Case Western Reserve University bearing-vibration dataset) into the platform on
the same interface as a live device collector.

WHY: the lab pulls genuinely-live data from the Trio JR900 radios, the Cisco
Catalyst, the MikroTik, and the SCADAPack 470. Everything else on the Killdeer
twin is SIMULATED. This collector adds a THIRD, honestly-labeled class —
``reference`` — so the platform also processes *real recorded* industrial
process + vibration data without pretending it is field-live.

HONESTY CONTRACT (non-negotiable):
  * Every reading is tagged ``source="reference"`` — never "live"/"simulated".
  * Reference data is NOT a Killdeer twin node and must never be presented as
    Killdeer field-live or as a customer feed. It is recorded lab/testbed data,
    attributed to its source dataset (see reference_data/README.md).
  * Values come ONLY from a prepped CSV produced by scripts/prep_reference_data.py
    from the real downloads — this module fabricates nothing.

The replay CSV is a normalized "frame" format (one process time-step per frame):

    frame,metric,value,unit,group
    0,pipe_pressure,12.4,PSI,reference:morris
    0,setpoint,15.0,PSI,reference:morris
    0,label,0,state,reference:morris
    1,pipe_pressure,11.9,PSI,reference:morris
    ...
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from src.collectors.base import BaseCollector

if TYPE_CHECKING:
    from src.models.telemetry import RawTelemetry

REFERENCE_SOURCE = "reference"


class ReferenceReplayCollector(BaseCollector):
    """Replays a prepped reference-dataset CSV one frame per ``poll()``.

    Args:
        asset_id: platform asset id to attach the readings to (a dedicated
            reference asset, e.g. "REF-MORRIS" or "REF-CWRU" — NOT a Killdeer node).
        csv_path: path to a normalized replay CSV (see module docstring).
        poll_interval: seconds between frames (replay rate).
        loop: when True, wrap around to frame 0 at the end (continuous demo loop).
    """

    def __init__(
        self,
        asset_id: str,
        csv_path: str | Path,
        poll_interval: int = 5,
        loop: bool = True,
    ) -> None:
        super().__init__(asset_id=asset_id, host=str(csv_path), poll_interval=poll_interval)
        self.csv_path = Path(csv_path)
        self.loop = loop
        self._frames: list[list[dict[str, str]]] = self._load_frames(self.csv_path)
        self._cursor = 0
        self.log.info(
            "reference_replay_loaded",
            frames=len(self._frames),
            csv=str(self.csv_path),
        )

    @staticmethod
    def _load_frames(csv_path: Path) -> list[list[dict[str, str]]]:
        """Group the replay CSV rows into ordered frames by the ``frame`` column."""
        if not csv_path.exists():
            return []
        grouped: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        with csv_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                grouped.setdefault(row.get("frame", "0"), []).append(row)
        return list(grouped.values())

    async def is_reachable(self) -> bool:
        """Reference data is 'reachable' iff a prepped CSV with frames is loaded."""
        return bool(self._frames)

    async def poll(self) -> list[RawTelemetry]:
        """Return the readings for the next frame; advance (and optionally loop)."""
        if not self._frames:
            return []
        if self._cursor >= len(self._frames):
            if not self.loop:
                return []
            self._cursor = 0

        frame = self._frames[self._cursor]
        self._cursor += 1

        readings: list[RawTelemetry] = []
        for row in frame:
            try:
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            readings.append(
                self._make_reading(
                    metric=row.get("metric", "value"),
                    value=value,
                    unit=row.get("unit", ""),
                    source=REFERENCE_SOURCE,  # honesty: never "live"/"simulated"
                    group=row.get("group", "reference"),
                )
            )
        return readings
