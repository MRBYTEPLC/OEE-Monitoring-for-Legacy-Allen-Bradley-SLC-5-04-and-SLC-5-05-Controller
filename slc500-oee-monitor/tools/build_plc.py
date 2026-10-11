"""Generates the ladder listing (Markdown) and an RSLogix 500 ASCII rung file from ONE source of truth.

Run:  python tools/build_plc.py      ->  plc/SLC500_OEE_ladder_listing.md , plc/OEE_MON_LAD3_rungs.asc
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "plc"
INPUTS = {"XIC", "XIO", "ONS", "EQU", "NEQ", "GEQ"}

DATA = [  # address, name, description
    ("N7:0", "TOTAL_COUNT", "All parts produced in the period (good + scrap)"),
    ("N7:1", "SCRAP_COUNT", "Rejected parts in the period"),
    ("N7:2 / N7:6", "RUN_SEC / RUN_MIN", "Run time: seconds (0-59) / whole minutes"),
    ("N7:3 / N7:7", "IDLE_SEC / IDLE_MIN", "Idle time (starved, blocked, no operator)"),
    ("N7:4 / N7:8", "FAULT_SEC / FAULT_MIN", "Fault time (breakdown)"),
    ("N7:5 / N7:9", "PLAN_SEC / PLAN_MIN", "Planned stop (break, meeting, PM) - excluded from OEE"),
    ("N7:10", "FAULT_EVENTS", "Number of fault occurrences (for MTBF / MTTR)"),
    ("N7:11", "RESET_REQ", "PC writes 1 -> PLC clears N7:0..N7:10, then clears N7:11"),
    ("N7:12", "HEARTBEAT", "Increments every second (0-29999); PC detects a stopped PLC"),
    ("N7:13", "STATE_CODE", "0 = Idle, 1 = Run, 2 = Fault, 3 = Planned stop"),
    ("N7:14", "SIM_SCRAP_CTR", "Simulator only: counts parts to generate 1 scrap in 10"),
    ("N10:0", "ALARM_WORD", "16 alarm bits (bit = alarm number); any bit set = FAULT state"),
    ("B3:0/1", "ST_RUN", "State bit: running (kept from the original project)"),
    ("B3:0/2", "ST_IDLE", "State bit: idle"),
    ("B3:0/3", "ST_FAULT", "State bit: fault"),
    ("B3:0/4", "ST_PLANNED", "State bit: planned stop"),
    ("B3:1/0", "RUN_IN", "Machine in automatic cycle (from your I/O)"),
    ("B3:1/1", "PLANNED_IN", "Planned-stop selector (from your I/O, e.g. key switch)"),
    ("B3:1/2", "PART_IN", "Part-complete sensor pulse (counts every part)"),
    ("B3:1/3", "REJECT_IN", "Reject / diverter sensor pulse (counts scrap)"),
    ("B3:1/10", "SIM_RUN", "Simulator: pretend machine is running"),
    ("B3:1/12, /13", "SIM_PART, SIM_REJECT", "Simulator: generated part and reject pulses"),
    ("B3:1/15", "SIM_ENABLE", "1 = simulator on, real inputs ignored"),
    ("B3:2/0..2", "ONS storage", "One-shot bits: part, reject, fault-event"),
    ("T4:0", "TIMER 1 s", "Time base 0.01 s, preset 100 -> 1-second pulse (T4:0/DN)"),
    ("T4:1", "SIM CYCLE", "Time base 1.0 s, preset 5 -> simulator cycle time"),
]

R = []                                                   # (title, comment, items)
def rung(title, comment, *items): R.append((title, comment, list(items)))
def br(*paths): return ("BR", [list(p) for p in paths])

rung("Subroutine entry", "First rung of LAD 3 (OEE_MON). Call it with JSR U:3 from LAD 2.", "SBR")
rung("Period reset", "PC writes 1 to N7:11 at shift end. Clear counters N7:0..N7:10, then acknowledge.",
     "EQU N7:11 1", "FLL 0 #N7:0 11", "MOV 0 N7:11")
rung("Map input: RUN", "EDIT ADDRESS to your machine I/O. Ignored while simulator is on.", "XIO B3:1/15", "XIC I:1/0", "OTE B3:1/0")
rung("Map input: PLANNED STOP", "EDIT ADDRESS. Break / changeover / planned maintenance selector.", "XIO B3:1/15", "XIC I:1/1", "OTE B3:1/1")
rung("Map input: PART SENSOR", "EDIT ADDRESS. One pulse per completed part (before the reject diverter).", "XIO B3:1/15", "XIC I:1/2", "OTE B3:1/2")
rung("Map input: REJECT SENSOR", "EDIT ADDRESS. One pulse per rejected part.", "XIO B3:1/15", "XIC I:1/3", "OTE B3:1/3")
rung("Alarm 0: E-stop circuit", "EDIT ADDRESS. Healthy = input ON (fail-safe wiring); alarm when OFF. Monitoring only, NOT a safety function.",
     "XIO B3:1/15", "XIO I:1/4", "OTE N10:0/0")
rung("Alarm 1: Low air pressure", "EDIT ADDRESS. Healthy = ON.", "XIO B3:1/15", "XIO I:1/5", "OTE N10:0/1")
rung("Alarm 2: Drive fault / over-temperature", "EDIT ADDRESS. Healthy = ON.", "XIO B3:1/15", "XIO I:1/6", "OTE N10:0/2")
rung("Alarm 3: Safety door open", "EDIT ADDRESS. Healthy = ON.", "XIO B3:1/15", "XIO I:1/7", "OTE N10:0/3")
rung("Simulator: cycle timer", "Test without a machine. Set B3:1/15 = 1 and B3:1/10 = 1. Preset = ideal cycle time (5 s).",
     "XIC B3:1/15", "XIC B3:1/10", "XIO T4:1/DN", "TON T4:1 1.0 5 0")
rung("Simulator: part pulse", "One-scan pulse each time the simulator cycle completes.", "XIC T4:1/DN", "OTE B3:1/12")
rung("Simulator: count parts", "Counts simulated parts.", "XIC B3:1/12", "ADD N7:14 1 N7:14")
rung("Simulator: 1 scrap in 10", "Generates a reject pulse on every 10th part (does NOT touch the production counters).",
     "GEQ N7:14 10", "OTE B3:1/13", "CLR N7:14")
rung("State: PLANNED STOP", "Highest priority: time inside a planned stop never counts against OEE.", "XIC B3:1/1", "OTE B3:0/4")
rung("State: FAULT", "Any alarm bit set (and not in planned stop).", "NEQ N10:0 0", "XIO B3:0/4", "OTE B3:0/3")
rung("State: RUN", "Automatic cycle active (real or simulated), no fault, no planned stop.",
     br(["XIC B3:1/0"], ["XIC B3:1/10"]), "XIO B3:0/4", "XIO B3:0/3", "OTE B3:0/1")
rung("State: IDLE", "None of the above: starved, blocked, waiting for operator / material.", "XIO B3:0/1", "XIO B3:0/3", "XIO B3:0/4", "OTE B3:0/2")
rung("State code: IDLE", "Integer copy of the state for the PC.", "XIC B3:0/2", "MOV 0 N7:13")
rung("State code: RUN", "", "XIC B3:0/1", "MOV 1 N7:13")
rung("State code: FAULT", "", "XIC B3:0/3", "MOV 2 N7:13")
rung("State code: PLANNED", "", "XIC B3:0/4", "MOV 3 N7:13")
rung("1-second pulse", "T4:0/DN is true for exactly one scan each second (self-resetting timer).", "XIO T4:0/DN", "TON T4:0 0.01 100 0")
for name, st, sec, mn in (("RUN", "B3:0/1", "N7:2", "N7:6"), ("IDLE", "B3:0/2", "N7:3", "N7:7"),
                          ("FAULT", "B3:0/3", "N7:4", "N7:8"), ("PLANNED", "B3:0/4", "N7:5", "N7:9")):
    rung(f"Time: {name} seconds", "Adds 1 s while the state is active.", f"XIC {st}", "XIC T4:0/DN", f"ADD {sec} 1 {sec}")
    rung(f"Time: {name} minutes", "Seconds roll into minutes (avoids the 32,767 integer limit).", f"GEQ {sec} 60", f"ADD {mn} 1 {mn}", f"CLR {sec}")
rung("Count: parts", "Real or simulated part pulse, one count per rising edge.",
     br(["XIC B3:1/2"], ["XIC B3:1/12"]), "ONS B3:2/0", "ADD N7:0 1 N7:0")
rung("Count: scrap", "Real or simulated reject pulse, one count per rising edge.",
     br(["XIC B3:1/3"], ["XIC B3:1/13"]), "ONS B3:2/1", "ADD N7:1 1 N7:1")
rung("Count: fault events", "One count per transition into FAULT (needed for MTBF / MTTR).", "XIC B3:0/3", "ONS B3:2/2", "ADD N7:10 1 N7:10")
rung("Heartbeat", "Lets the PC detect a stopped or PROGRAM-mode PLC.", "XIC T4:0/DN", "ADD N7:12 1 N7:12")
rung("Heartbeat rollover", "Keeps the heartbeat inside 0-29999.", "GEQ N7:12 30000", "MOV 0 N7:12")


def pretty(tok):
    p = tok.split()
    op = p[0]
    if op == "ADD": return f"ADD {p[1]} + {p[2]} -> {p[3]}"
    if op == "MOV": return f"MOV {p[1]} -> {p[2]}"
    if op == "FLL": return f"FLL {p[1]} -> {p[2]} len {p[3]}"
    if op == "TON": return f"TON {p[1]} base {p[2]}s preset {p[3]}"
    if op == "EQU": return f"EQU {p[1]} = {p[2]}"
    if op == "NEQ": return f"NEQ {p[1]} <> {p[2]}"
    if op == "GEQ": return f"GEQ {p[1]} >= {p[2]}"
    return tok

def box(tok): return f"[{pretty(tok)}]" if tok.split()[0] in INPUTS else f"({pretty(tok)})"

def art(items):
    top = mid = bot = ""
    branched = False
    for it in items:
        if isinstance(it, tuple):
            branched = True
            a, b = (" ".join(box(t) for t in p) for p in it[1])
            w = max(len(a), len(b))
            top += "  +-" + a.ljust(w, "-") + "-+"
            mid += "--|" + " " * (w + 2) + "+"
            bot += "  +-" + b.ljust(w, "-") + "-+"
        else:
            s = "--" + box(it)
            mid += s; top += " " * len(s); bot += " " * len(s)
    lines = [top, mid, bot] if branched else [mid]
    return "\n".join(l.rstrip() for l in lines)

def asc(items):
    out = []
    for it in items:
        if isinstance(it, tuple):
            out.append("BST " + " NXB ".join(" ".join(p) for p in it[1]) + " BND")
        else:
            out.append(it)
    return "SOR " + " ".join(out) + " EOR"


md = ["# SLC 500 OEE ladder listing (LAD 3 `OEE_MON`)", "",
      "Identical for SLC 5/04 and SLC 5/05. Rung comments starting with **EDIT ADDRESS** must be changed to your machine I/O.", "",
      "## Data table map", "", "| Address | Symbol | Description |", "|---|---|---|"]
md += [f"| `{a}` | {n} | {d} |" for a, n, d in DATA]
md += ["", f"## Rungs ({len(R)} total, numbered from 0000)", ""]
for i, (title, comment, items) in enumerate(R):
    md += ["```", f"RUNG {i:04d}  {title}" + (f"\n  ; {comment}" if comment else ""), art(items), "```", ""]
(OUT / "SLC500_OEE_ladder_listing.md").write_text("\n".join(md), encoding="utf-8")
(OUT / "OEE_MON_LAD3_rungs.asc").write_text("\n".join(asc(it) for _, _, it in R) + "\n", encoding="ascii")
print(f"{len(R)} rungs written to {OUT}")
