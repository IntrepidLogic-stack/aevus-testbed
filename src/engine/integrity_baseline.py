"""
Aevus Testbed — Comm-path integrity baseline (P3 contract #3)

"Up" and "trustworthy" are different questions. Health answers "is the link
carrying telemetry?"; integrity answers "is it carrying it the way it always
has?" A link can be health-good and integrity-suspect at once — that
divergence is the operator's earliest attack cue (D'Amico cyber-SA).

This is a deliberately small, honest first cut: per-asset we learn a baseline
of (protocol source, firmware). A change in the transport a device speaks over
(protocol_deviation) or its firmware/config (config_change) flags integrity.
Before a baseline exists we report "unknown" — never a false "expected".

Richer signals — new SNMP talkers, Modbus exception spikes, dnp3 IIN bits —
slot into detect() as they become available upstream, without changing the
enum the frontend renders.
"""

from __future__ import annotations

from typing import Any, Literal

Integrity = Literal["expected", "new_talker", "protocol_deviation", "config_change", "unknown"]


class IntegrityBaseline:
    """Learns and checks a per-asset comm baseline. Process-local; the demo
    and single-node deployments need no persistence, and a wrong-but-durable
    baseline is worse than a re-learned one on restart."""

    # Minimum consistent observations before a baseline is trusted. Below
    # this we answer "unknown" rather than assert a baseline we haven't seen.
    _MIN_SAMPLES = 3

    def __init__(self) -> None:
        # asset_id -> {"source": str, "firmware": str|None, "samples": int}
        self._base: dict[str, dict] = {}

    def observe(self, asset: Any) -> None:
        """Fold one asset observation into its baseline. Idempotent per poll."""
        aid = getattr(asset, "id", None)
        if not aid:
            return
        source = self._source_of(asset)
        firmware = getattr(asset, "firmware", None)
        b = self._base.get(aid)
        if b is None:
            self._base[aid] = {"source": source, "firmware": firmware, "samples": 1}
            return
        # A stable source/firmware increments confidence; a change is surfaced
        # by detect() and does NOT silently overwrite the baseline (that would
        # let an adversary re-baseline by persisting). Baseline moves only via
        # an explicit accept() (operator-acknowledged config change).
        if b["source"] == source and b["firmware"] == firmware:
            b["samples"] += 1

    def detect(self, asset: Any) -> Integrity:
        """Integrity verdict for the current asset state vs its baseline."""
        aid = getattr(asset, "id", None)
        if not aid:
            return "unknown"
        b = self._base.get(aid)
        if b is None or b["samples"] < self._MIN_SAMPLES:
            return "unknown"
        if self._source_of(asset) != b["source"]:
            return "protocol_deviation"
        if getattr(asset, "firmware", None) != b["firmware"]:
            return "config_change"
        return "expected"

    def accept(self, asset_id: str, asset: Any) -> None:
        """Re-baseline after an operator-acknowledged change (MOC). Only this
        path moves a baseline — never a silent observe()."""
        self._base[asset_id] = {
            "source": self._source_of(asset),
            "firmware": getattr(asset, "firmware", None),
            "samples": self._MIN_SAMPLES,
        }

    @staticmethod
    def _source_of(asset: Any) -> str:
        """The transport a device speaks over, from its vitals' source tags
        (snmp / modbus / dnp3 / opcua). Falls back to the asset.protocol."""
        for v in getattr(asset, "vitals", None) or []:
            src = getattr(v, "source", None)
            if src and src != "simulator":
                return src
        return getattr(asset, "protocol", "unknown")


# Process-wide singleton — the pearls endpoint observes on each grid build.
_baseline = IntegrityBaseline()


def get_baseline() -> IntegrityBaseline:
    return _baseline
