"""OEE and reliability KPI mathematics.

Definitions follow the Availability x Performance (Effectiveness) x Quality structure used by
ISO 22400-2:2014 (KPIs for manufacturing operations management) and the classic Nakajima TPM
formulation.  All inputs are plain numbers so the maths can be unit-tested without a PLC.

    Planned Production Time (PPT) = Run + Idle + Fault      (planned stops are excluded)
    Availability  A = Run / PPT
    Performance   P = (Ideal Cycle Time x Total Count) / Run       (capped at 100 %)
    Quality       Q = Good Count / Total Count
    OEE             = A x P x Q  =  (Good Count x Ideal Cycle Time) / PPT   (when P is not capped)
    MTBF = Run / Fault events          MTTR = Fault time / Fault events
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Counters:
    run_s: int
    idle_s: int
    fault_s: int
    planned_s: int
    total: int
    scrap: int
    fault_events: int = 0


@dataclass(frozen=True)
class KPIs:
    ppt_s: int                 # planned production time
    availability: float        # 0..1
    performance: float         # 0..1 (capped)
    quality: float             # 0..1
    oee: float                 # 0..1
    good: int
    performance_capped: bool   # True -> ideal cycle time is probably set too high
    fully_productive_s: float  # good count x ideal cycle time
    speed_loss_s: float        # run time lost to slow cycles / micro-stops
    quality_loss_s: float      # time spent making scrap
    mtbf_s: Optional[float]
    mttr_s: Optional[float]


def to_unsigned16(value: int) -> int:
    """SLC integer files are signed 16-bit; counters that pass 32,767 read as negative."""
    return int(value) & 0xFFFF


def compute_kpis(c: Counters, ideal_cycle_s: float) -> KPIs:
    if ideal_cycle_s <= 0:
        raise ValueError("ideal_cycle_s must be > 0")
    run, idle, fault = max(c.run_s, 0), max(c.idle_s, 0), max(c.fault_s, 0)
    total = max(c.total, 0)
    scrap = min(max(c.scrap, 0), total)
    good = total - scrap

    ppt = run + idle + fault
    availability = run / ppt if ppt > 0 else 0.0

    raw_perf = (total * ideal_cycle_s) / run if run > 0 else 0.0
    capped = raw_perf > 1.0
    performance = min(raw_perf, 1.0)

    quality = good / total if total > 0 else 1.0     # no parts yet -> no defects observed
    oee = availability * performance * quality

    ideal_time = total * ideal_cycle_s
    return KPIs(
        ppt_s=ppt, availability=availability, performance=performance, quality=quality, oee=oee,
        good=good, performance_capped=capped,
        fully_productive_s=good * ideal_cycle_s,
        speed_loss_s=max(run - ideal_time, 0.0),
        quality_loss_s=scrap * ideal_cycle_s,
        mtbf_s=(run / c.fault_events) if c.fault_events > 0 else None,
        mttr_s=(fault / c.fault_events) if c.fault_events > 0 else None,
    )


def fmt_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--"
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
