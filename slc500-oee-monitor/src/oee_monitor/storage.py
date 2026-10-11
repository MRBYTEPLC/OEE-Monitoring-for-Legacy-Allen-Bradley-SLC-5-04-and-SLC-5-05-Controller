"""SQLite historian: time-series samples, alarm events and closed-shift records (single local file)."""
from __future__ import annotations

import csv
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .oee import KPIs
from .plc import Snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples(
  ts REAL, machine TEXT, state INT, total INT, scrap INT,
  run_s INT, idle_s INT, fault_s INT, planned_s INT, fault_events INT, alarm_word INT,
  oee REAL, availability REAL, performance REAL, quality REAL);
CREATE INDEX IF NOT EXISTS ix_samples ON samples(machine, ts);
CREATE TABLE IF NOT EXISTS alarm_events(ts REAL, machine TEXT, bit INT, text TEXT, active INT);
CREATE INDEX IF NOT EXISTS ix_alarm ON alarm_events(machine, ts);
CREATE TABLE IF NOT EXISTS shifts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, machine TEXT, start_ts REAL, end_ts REAL,
  ideal_cycle_s REAL, total INT, scrap INT, run_s INT, idle_s INT, fault_s INT, planned_s INT,
  fault_events INT, oee REAL, availability REAL, performance REAL, quality REAL, note TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


class Storage:
    def __init__(self, path: Path):
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, args=()):
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _rows(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # ---- samples -------------------------------------------------------------------------
    def add_sample(self, machine: str, s: Snapshot, k: KPIs) -> None:
        self._exec("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (s.ts, machine, s.state, s.total, s.scrap, s.run_s, s.idle_s, s.fault_s, s.planned_s,
                    s.fault_events, s.alarm_word, k.oee * 100, k.availability * 100,
                    k.performance * 100, k.quality * 100))

    def samples_between(self, machine: str, start: float, end: float) -> list[dict]:
        return self._rows("SELECT * FROM samples WHERE machine=? AND ts BETWEEN ? AND ? ORDER BY ts",
                          (machine, start, end))

    def export_samples_csv(self, path: Path, machine: str, start: float, end: float) -> int:
        rows = self.samples_between(machine, start, end)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            if rows:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        return len(rows)

    # ---- alarms ----------------------------------------------------------------------------
    def add_alarm_event(self, ts: float, machine: str, bit: int, text: str, active: bool) -> None:
        self._exec("INSERT INTO alarm_events VALUES(?,?,?,?,?)", (ts, machine, bit, text, int(active)))

    def alarm_events(self, machine: str, start: float = 0, end: float = 9e12, limit: int = 500) -> list[dict]:
        return self._rows("SELECT * FROM alarm_events WHERE machine=? AND ts BETWEEN ? AND ? "
                          "ORDER BY ts DESC LIMIT ?", (machine, start, end, limit))

    # ---- shifts ----------------------------------------------------------------------------
    def add_shift(self, machine: str, start_ts: float, end_ts: float, ideal: float,
                  s: Snapshot, k: KPIs, note: str = "") -> int:
        cur = self._exec(
            "INSERT INTO shifts(machine,start_ts,end_ts,ideal_cycle_s,total,scrap,run_s,idle_s,fault_s,"
            "planned_s,fault_events,oee,availability,performance,quality,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (machine, start_ts, end_ts, ideal, s.total, s.scrap, s.run_s, s.idle_s, s.fault_s, s.planned_s,
             s.fault_events, k.oee * 100, k.availability * 100, k.performance * 100, k.quality * 100, note))
        return int(cur.lastrowid)

    def shifts(self, machine: str, limit: int = 200) -> list[dict]:
        return self._rows("SELECT * FROM shifts WHERE machine=? ORDER BY id DESC LIMIT ?", (machine, limit))

    def shift(self, shift_id: int) -> Optional[dict]:
        rows = self._rows("SELECT * FROM shifts WHERE id=?", (shift_id,))
        return rows[0] if rows else None

    # ---- meta ------------------------------------------------------------------------------
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        rows = self._rows("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key: str, value: str) -> None:
        self._exec("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, value))

    def close(self) -> None:
        with self._lock:
            self._db.close()
