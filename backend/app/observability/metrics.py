from __future__ import annotations

import math
import threading
from collections import defaultdict


def _labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in labels.items()))


class Metrics:
    """Small dependency-free Prometheus exposition registry with bounded labels."""

    def __init__(self):
        self._lock = threading.Lock()
        self.counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self.gauges: dict[tuple[str, tuple], float] = {}
        self.histograms: dict[tuple[str, tuple], list[float]] = defaultdict(list)

    def inc(self, name: str, value: float = 1, **labels: str):
        with self._lock:
            self.counters[(name, _labels(labels))] += value

    def set(self, name: str, value: float, **labels: str):
        with self._lock:
            self.gauges[(name, _labels(labels))] = value

    def observe(self, name: str, value: float, **labels: str):
        with self._lock:
            values = self.histograms[(name, _labels(labels))]
            values.append(float(value))
            if len(values) > 10_000:
                del values[: len(values) - 10_000]

    @staticmethod
    def _format_labels(labels: tuple) -> str:
        if not labels:
            return ""
        return (
            "{"
            + ",".join(f'{k}="{str(v).replace(chr(34), chr(92) + chr(34))}"' for k, v in labels)
            + "}"
        )

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self.counters.items()):
                lines.append(f"{name}{self._format_labels(labels)} {value}")
            for (name, labels), value in sorted(self.gauges.items()):
                lines.append(f"{name}{self._format_labels(labels)} {value}")
            for (name, labels), values in sorted(self.histograms.items()):
                if not values:
                    continue
                ordered = sorted(values)
                total = sum(ordered)
                for quantile, position in (("0.5", 0.5), ("0.95", 0.95)):
                    index = min(len(ordered) - 1, math.ceil(position * len(ordered)) - 1)
                    qlabels = labels + (("quantile", quantile),)
                    lines.append(f"{name}{self._format_labels(qlabels)} {ordered[index]}")
                lines.append(f"{name}_count{self._format_labels(labels)} {len(values)}")
                lines.append(f"{name}_sum{self._format_labels(labels)} {total}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
