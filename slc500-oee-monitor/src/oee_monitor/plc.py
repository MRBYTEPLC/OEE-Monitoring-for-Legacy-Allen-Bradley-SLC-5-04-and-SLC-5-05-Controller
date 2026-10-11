"""PLC access layer: a real SLC 5/05 client (via pylogix / EtherNet-IP PCCC) and a built-in simulator."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from .oee import to_unsigned16

STATE_IDLE, STATE_RUN, STATE_FAULT, STATE_PLANNED = 0, 1, 2, 3
STATE_NAMES = {STATE_IDLE: "IDLE", STATE_RUN: "RUNNING", STATE_FAULT: "FAULT", STATE_PLANNED: "PLANNED STOP"}

# PLC data-table map (see docs/Implementation_Guide.pdf, Appendix A). Only N-file reads are used.
TAGS = {
    "total": "N7:0", "scrap": "N7:1",
    "run_s": "N7:2", "idle_s": "N7:3", "fault_s": "N7:4", "planned_s": "N7:5",
    "run_m": "N7:6", "idle_m": "N7:7", "fault_m": "N7:8", "planned_m": "N7:9",
    "fault_events": "N7:10", "heartbeat": "N7:12", "state": "N7:13", "alarm": "N10:0",
}
RESET_TAG = "N7:11"


class PLCError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    ts: float
    state: int
    total: int
    scrap: int
    run_s: int
    idle_s: int
    fault_s: int
    planned_s: int
    fault_events: int
    alarm_word: int
    heartbeat: int
    stale: bool = False        # heartbeat not advancing -> PLC in PROG mode or scan stopped

    def with_stale(self, stale: bool) -> "Snapshot":
        return replace(self, stale=stale)


class PLCClient:
    """Read-mostly client. The only write ever issued is 1 -> N7:11 (period reset request)."""

    def __init__(self, ip: str, slot: int = 0):
        try:
            from pylogix import PLC
        except ImportError as exc:                      # pragma: no cover
            raise PLCError("pylogix is not installed (pip install pylogix)") from exc
        self._plc = PLC()
        self._plc.IPAddress = ip
        self._plc.ProcessorSlot = slot
        self._plc.SocketTimeout = 3.0

    def read(self) -> Snapshot:
        names = list(TAGS)
        res = self._plc.Read([TAGS[n] for n in names])
        res = res if isinstance(res, list) else [res]
        for r in res:
            if r.Status != "Success":
                raise PLCError(f"{r.TagName}: {r.Status}")
        v = {n: to_unsigned16(r.Value) for n, r in zip(names, res)}
        return Snapshot(
            ts=time.time(), state=v["state"], total=v["total"], scrap=v["scrap"],
            run_s=v["run_m"] * 60 + v["run_s"], idle_s=v["idle_m"] * 60 + v["idle_s"],
            fault_s=v["fault_m"] * 60 + v["fault_s"], planned_s=v["planned_m"] * 60 + v["planned_s"],
            fault_events=v["fault_events"], alarm_word=v["alarm"], heartbeat=v["heartbeat"])

    def request_reset(self) -> bool:
        r = self._plc.Write(RESET_TAG, 1)
        return r.Status == "Success"

    def close(self) -> None:
        self._plc.Close()


class SimulatedPLC:
    """Produces realistic data (run / idle / faults / planned stops / scrap) without hardware.

    `speed` = simulated seconds per real second, so trends become visible within minutes."""

    def __init__(self, ideal_cycle_s: float = 5.0, speed: float = 60.0, seed=None):
        self.ideal, self.speed = ideal_cycle_s, speed
        self.rng = random.Random(seed)
        self._last = time.time()
        self._carry = 0.0
        self.request_reset()
        self.state, self._remaining = STATE_RUN, 3600

    def request_reset(self) -> bool:
        self.t = {"run": 0, "idle": 0, "fault": 0, "planned": 0}
        self.total = self.scrap = self.events = 0
        self.alarm = 0
        self.hb = 0
        self._progress = 0.0
        self._cycle = self.ideal
        return True

    def _enter(self, state: int) -> None:
        self.state = state
        self.alarm = 0
        if state == STATE_FAULT:
            self._remaining = self.rng.randint(60, 300)
            self.alarm = 1 << self.rng.choice([0, 1, 2, 3])
            self.events += 1
        elif state == STATE_IDLE:
            self._remaining = self.rng.randint(30, 180)
        elif state == STATE_PLANNED:
            self._remaining = self.rng.randint(300, 600)
        else:
            self._remaining = self.rng.randint(900, 5400)

    def _step(self) -> None:                             # advance one simulated second
        self.hb = (self.hb + 1) % 30000
        key = {STATE_RUN: "run", STATE_IDLE: "idle", STATE_FAULT: "fault", STATE_PLANNED: "planned"}[self.state]
        self.t[key] += 1
        if self.state == STATE_RUN:
            self._progress += 1
            if self._progress >= self._cycle:
                self._progress = 0
                self._cycle = self.ideal * self.rng.uniform(1.0, 1.18)
                self.total += 1
                if self.rng.random() < 0.03:
                    self.scrap += 1
        self._remaining -= 1
        if self._remaining <= 0:
            if self.state == STATE_RUN:
                self._enter(self.rng.choices([STATE_FAULT, STATE_IDLE, STATE_PLANNED], [5, 4, 1])[0])
            else:
                self._enter(STATE_RUN)

    def read(self) -> Snapshot:
        now = time.time()
        self._carry += (now - self._last) * self.speed
        self._last = now
        for _ in range(int(self._carry)):
            self._step()
        self._carry -= int(self._carry)
        return Snapshot(ts=now, state=self.state, total=self.total, scrap=self.scrap,
                        run_s=self.t["run"], idle_s=self.t["idle"], fault_s=self.t["fault"],
                        planned_s=self.t["planned"], fault_events=self.events,
                        alarm_word=self.alarm, heartbeat=self.hb)

    def close(self) -> None:
        pass
