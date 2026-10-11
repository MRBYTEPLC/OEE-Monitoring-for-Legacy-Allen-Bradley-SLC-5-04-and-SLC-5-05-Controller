"""Persistent settings stored as JSON in ~/OEE_Monitor (override with the OEE_HOME variable)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_ALARMS = {
    "0": "Emergency stop circuit open",
    "1": "Low compressed-air pressure",
    "2": "Drive fault / over-temperature",
    "3": "Safety door open",
}


def app_home() -> Path:
    home = Path(os.environ.get("OEE_HOME", Path.home() / "OEE_Monitor"))
    (home / "reports").mkdir(parents=True, exist_ok=True)
    return home


@dataclass
class Settings:
    machine_name: str = "Line 1 - Machine A"
    plc_ip: str = "192.168.1.10"
    processor_slot: int = 0
    ideal_cycle_s: float = 5.0        # seconds per part at rated speed (must match the real machine)
    poll_s: float = 2.0
    log_interval_s: int = 30
    target_oee: float = 85.0          # commonly cited world-class benchmark
    demo_mode: bool = True
    allow_plc_write: bool = True      # needed only for "Close Shift & Reset"
    alarm_names: dict = field(default_factory=lambda: dict(DEFAULT_ALARMS))

    def alarm_name(self, bit: int) -> str:
        return self.alarm_names.get(str(bit)) or f"Alarm bit {bit} (undefined)"

    @classmethod
    def load(cls) -> "Settings":
        path = app_home() / "settings.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (ValueError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        (app_home() / "settings.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
