"""Read a CZ-based IBM calibration export and score each physical embedding."""
import csv
from functools import lru_cache
import math

import numpy as np


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return math.nan


def neighbors(text):
    return {int(q): number(value) for q, value in
            (entry.split(":", 1) for entry in text.split(";") if ":" in entry)}


class Calibration:
    limits = {"rz": 0.0, "sx": .01, "x": .01, "cz": .05, "measure": .10, "reset": .10}

    def __init__(self, path):
        self.coherence, self.operations, self.usable = {}, {}, set()
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                q = int(row["Qubit"])
                t1, t2 = number(row["T1 (us)"]), number(row["T2 (us)"])
                self.coherence[q] = min(t1, t2) * 1e-6
                ro, one = number(row["Readout length (ns)"]), number(row["Single-qubit gate length (ns)"])
                for op, field, ns in [
                    ("rz", "Z-axis rotation (rz) error", 0),
                    ("sx", "\u221ax (sx) error", one), ("x", "Pauli-X error", one),
                    ("measure", "Readout assignment error", ro), ("reset", "Init error", ro + one),
                ]:
                    self.operations[op, (q,)] = (number(row.get(field)), ns * 1e-9)
                lengths = neighbors(row["Gate length (ns)"])
                for other, error in neighbors(row["CZ error"]).items():
                    self.operations["cz", (q, other)] = (error, lengths.get(other, math.nan) * 1e-9)
                if (row["Operational"].strip().lower() in {"yes", "true", "1"}
                        and all(math.isfinite(t) and t > 0 for t in (t1, t2))
                        and all(0 <= self.operations[op, (q,)][0] <= self.limits[op]
                                for op in ("sx", "x", "measure"))):
                    self.usable.add(q)

    @lru_cache(maxsize=None)
    def admitted(self, op, qs):
        if op == "barrier":
            return True
        error, seconds = self.operations.get((op, qs), (math.nan, math.nan))
        return (op in self.limits and 0 <= error <= self.limits[op] and
                math.isfinite(seconds) and (seconds > 0 or (op == "rz" and seconds == 0)))

    def costs(self, kinds, sequence, mappings):
        """Sum gate/readout risk and coherence-weighted idle time at synchronizations."""
        duration = np.zeros((len(kinds), len(mappings)))
        risk = np.zeros_like(duration)
        for i, (op, wires) in enumerate(kinds):
            if op == "barrier":
                continue
            for j, mapping in enumerate(mappings):
                err, seconds = self.operations[op, tuple(mapping[q] for q in wires)]
                risk[i, j], duration[i, j] = -math.log1p(-err), seconds
        cost = np.bincount(sequence, minlength=len(kinds)) @ risk
        coherence = np.array([[self.coherence[q] for q in mapping] for mapping in mappings])
        ready = np.zeros_like(coherence)
        for i in sequence:
            wires = kinds[i][1]
            if not wires:
                continue
            start = np.max(ready[:, wires], axis=1)
            for q in wires:
                cost += (start - ready[:, q]) / coherence[:, q]
                ready[:, q] = start + duration[i]
        return cost
