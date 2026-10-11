"""Tkinter dashboard: live OEE gauge, KPI cards, trends, alarms, history, PDF reports."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import __version__, report
from .config import Settings, app_home
from .oee import Counters, compute_kpis, fmt_hms
from .plc import STATE_FAULT, STATE_IDLE, STATE_NAMES, STATE_PLANNED, STATE_RUN, PLCClient, SimulatedPLC, Snapshot
from .storage import Storage

C = dict(bg="#0B1220", card="#152033", card2="#1B2A42", text="#E6EDF7", muted="#8DA2C0", accent="#38BDF8",
         green="#22C55E", amber="#F59E0B", red="#EF4444", blue="#60A5FA", track="#2A3B57")
STATE_COLOR = {STATE_RUN: C["green"], STATE_IDLE: C["amber"], STATE_FAULT: C["red"], STATE_PLANNED: C["blue"]}
FONT = "Segoe UI"


def level_color(value: float, target: float) -> str:
    return C["green"] if value >= target else C["amber"] if value >= 0.7 * target else C["red"]


# --------------------------------------------------------------------------------------------
class Poller(threading.Thread):
    """Background thread: talks to the PLC (or simulator) and posts snapshots to a queue."""

    def __init__(self, st: Settings, out: queue.Queue):
        super().__init__(daemon=True)
        self.st, self.out = st, out
        self.stop_evt = threading.Event()
        self.cmds: queue.Queue = queue.Queue()

    def run(self) -> None:
        try:
            src = SimulatedPLC(self.st.ideal_cycle_s) if self.st.demo_mode else PLCClient(self.st.plc_ip, self.st.processor_slot)
        except Exception as exc:
            self.out.put(("error", str(exc)))
            return
        last_hb, last_change = None, time.time()
        while not self.stop_evt.is_set():
            try:
                while not self.cmds.empty():
                    if self.cmds.get_nowait() == "reset":
                        self.out.put(("reset", bool(src.request_reset())))
                snap: Snapshot = src.read()
                if snap.heartbeat != last_hb:
                    last_hb, last_change = snap.heartbeat, time.time()
                stale = (time.time() - last_change) > max(10.0, 5 * self.st.poll_s)
                self.out.put(("snap", snap.with_stale(stale)))
            except Exception as exc:
                self.out.put(("error", str(exc)))
            self.stop_evt.wait(self.st.poll_s)
        src.close()


# --------------------------------------------------------------------------------------------
class Gauge(tk.Canvas):
    def __init__(self, master, size=250):
        super().__init__(master, width=size, height=size, bg=C["card"], highlightthickness=0)
        self.size = size
        p = 22
        self.box = (p, p, size - p, size - p)
        self.create_arc(*self.box, start=210, extent=-240, style="arc", width=20, outline=C["track"])
        self.arc = self.create_arc(*self.box, start=210, extent=0, style="arc", width=20, outline=C["green"])
        self.txt = self.create_text(size / 2, size / 2 - 6, text="--", fill=C["text"], font=(FONT, 34, "bold"))
        self.create_text(size / 2, size / 2 + 34, text="OEE", fill=C["muted"], font=(FONT, 13, "bold"))
        self.sub = self.create_text(size / 2, size - 20, text="", fill=C["muted"], font=(FONT, 9))

    def set(self, value: float, target: float) -> None:
        col = level_color(value, target)
        self.itemconfigure(self.arc, extent=-240 * min(max(value, 0), 100) / 100, outline=col)
        self.itemconfigure(self.txt, text=f"{value:.1f}%", fill=col)
        self.itemconfigure(self.sub, text=f"Target {target:.0f}%")


class KpiCard(tk.Frame):
    def __init__(self, master, title: str, hint: str):
        super().__init__(master, bg=C["card"], padx=16, pady=10)
        tk.Label(self, text=title, bg=C["card"], fg=C["muted"], font=(FONT, 10, "bold")).grid(row=0, column=0, sticky="w")
        self.val = tk.Label(self, text="--", bg=C["card"], fg=C["text"], font=(FONT, 26, "bold"))
        self.val.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self.bar = tk.Canvas(self, height=8, bg=C["track"], highlightthickness=0)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        self.fill = self.bar.create_rectangle(0, 0, 0, 8, fill=C["green"], width=0)
        tk.Label(self, text=hint, bg=C["card"], fg=C["muted"], font=(FONT, 8), wraplength=250, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.columnconfigure(0, weight=1)

    def set(self, value: float, target: float, note: str = "") -> None:
        col = level_color(value, target)
        self.val.config(text=f"{value:.1f}%{note}", fg=col)
        w = max(self.bar.winfo_width(), 1)
        self.bar.coords(self.fill, 0, 0, w * min(value, 100) / 100, 8)
        self.bar.itemconfigure(self.fill, fill=col)


# --------------------------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"SLC 500 OEE Monitor  v{__version__}")
        self.geometry("1320x860")
        self.minsize(1180, 780)
        self.configure(bg=C["bg"])
        self.st = Settings.load()
        self.db = Storage(app_home() / "oee_history.db")
        self.q: queue.Queue = queue.Queue()
        self.poller: Poller | None = None
        self.last: Snapshot | None = None
        self.prev_alarm = 0
        self.last_log = 0.0
        self.last_chart = 0.0
        self._style()
        self._build()
        self.period_start = float(self.db.get_meta(f"period_start:{self.st.machine_name}", str(time.time())))
        self._start_poller()
        self.after(300, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---- construction -----------------------------------------------------------------------
    def _style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TNotebook", background=C["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=C["card"], foreground=C["muted"], padding=(22, 9), font=(FONT, 10, "bold"))
        s.map("TNotebook.Tab", background=[("selected", C["card2"])], foreground=[("selected", C["accent"])])
        s.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["text"], rowheight=26, borderwidth=0, font=(FONT, 9))
        s.configure("Treeview.Heading", background=C["card2"], foreground=C["text"], font=(FONT, 9, "bold"))
        s.configure("Accent.TButton", background=C["accent"], foreground="#04121F", font=(FONT, 10, "bold"), padding=8, borderwidth=0)
        s.map("Accent.TButton", background=[("active", "#7DD3FC")])
        s.configure("TButton", background=C["card2"], foreground=C["text"], font=(FONT, 10), padding=8, borderwidth=0)
        s.map("TButton", background=[("active", C["track"])])
        s.configure("TCombobox", fieldbackground=C["card2"], background=C["card2"], foreground=C["text"], arrowcolor=C["text"])
        s.map("TCombobox", fieldbackground=[("readonly", C["card2"])], foreground=[("readonly", C["text"])],
              selectbackground=[("readonly", C["card2"])], selectforeground=[("readonly", C["text"])])

    def _label(self, parent, text, size=10, bold=False, fg=None, bg=None, **kw):
        return tk.Label(parent, text=text, bg=bg or C["card"], fg=fg or C["text"], font=(FONT, size, "bold" if bold else "normal"), **kw)

    def _build(self) -> None:
        head = tk.Frame(self, bg=C["card"], padx=18, pady=10)
        head.pack(fill="x")
        self._label(head, "OEE MONITOR", 17, True, C["accent"]).pack(side="left")
        self.lbl_machine = self._label(head, self.st.machine_name, 13, True)
        self.lbl_machine.pack(side="left", padx=24)
        self.lbl_clock = self._label(head, "", 11, fg=C["muted"])
        self.lbl_clock.pack(side="right")
        self.lbl_status = tk.Label(head, text="STARTING", bg=C["track"], fg=C["text"], font=(FONT, 10, "bold"), padx=12, pady=4)
        self.lbl_status.pack(side="right", padx=16)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=10)
        self.tab_dash, self.tab_hist, self.tab_set = (tk.Frame(self.nb, bg=C["bg"]) for _ in range(3))
        self.nb.add(self.tab_dash, text="Dashboard")
        self.nb.add(self.tab_hist, text="History & Reports")
        self.nb.add(self.tab_set, text="Settings")
        self._build_dash()
        self._build_hist()
        self._build_settings()

    def _build_dash(self) -> None:
        d = self.tab_dash
        d.columnconfigure((0, 1, 2), weight=1, uniform="c")
        d.rowconfigure(1, weight=1)
        top = tk.Frame(d, bg=C["bg"])
        top.grid(row=0, column=0, columnspan=3, sticky="nsew")
        top.columnconfigure((0, 1, 2), weight=1, uniform="t")

        left = tk.Frame(top, bg=C["card"], padx=10, pady=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.gauge = Gauge(left)
        self.gauge.pack()
        self.lbl_state = tk.Label(left, text="--", bg=C["track"], fg="white", font=(FONT, 16, "bold"), pady=8)
        self.lbl_state.pack(fill="x", pady=(6, 0))

        mid = tk.Frame(top, bg=C["bg"])
        mid.grid(row=0, column=1, sticky="nsew", padx=8)
        self.cards = {}
        for i, (key, title, hint) in enumerate([
                ("a", "AVAILABILITY", "Share of planned production time the machine was actually running."),
                ("p", "PERFORMANCE", "Actual output compared with the output possible at the rated cycle time."),
                ("q", "QUALITY", "Good parts divided by all parts produced (scrap excluded).")]):
            card = KpiCard(mid, title, hint)
            card.pack(fill="x", pady=(0 if i == 0 else 8, 0), expand=True)
            self.cards[key] = card

        right = tk.Frame(top, bg=C["card"], padx=16, pady=10)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        self._label(right, "PRODUCTION & TIME", 10, True, C["muted"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.stat = {}
        for i, (key, name) in enumerate([("total", "Total parts"), ("good", "Good parts"), ("scrap", "Scrap parts"),
                                         ("run", "Run time"), ("idle", "Idle time"), ("fault", "Fault time"),
                                         ("planned", "Planned stop"), ("events", "Fault events"),
                                         ("mtbf", "MTBF"), ("mttr", "MTTR")], start=1):
            self._label(right, name, 10, fg=C["muted"]).grid(row=i, column=0, sticky="w", pady=2)
            self.stat[key] = self._label(right, "--", 11, True)
            self.stat[key].grid(row=i, column=1, sticky="e", padx=(30, 0))
        right.columnconfigure(1, weight=1)

        # bottom row
        bottom = tk.Frame(d, bg=C["bg"])
        bottom.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)
        chart_box = tk.Frame(bottom, bg=C["card"], padx=6, pady=6)
        chart_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        bar = tk.Frame(chart_box, bg=C["card"])
        bar.pack(fill="x")
        self._label(bar, "KPI TREND", 10, True, C["muted"]).pack(side="left", padx=8)
        self.range_var = tk.StringVar(value="Current period")
        cb = ttk.Combobox(bar, textvariable=self.range_var, width=16, state="readonly",
                          values=["Current period", "Last 1 hour", "Last 8 hours", "Last 24 hours", "Last 7 days"])
        cb.pack(side="right", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_trend(force=True))
        self.fig = Figure(figsize=(6, 3), dpi=100, facecolor=C["card"])
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_box)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        side = tk.Frame(bottom, bg=C["bg"])
        side.grid(row=0, column=1, sticky="nsew")
        side.rowconfigure(0, weight=1)
        side.columnconfigure(0, weight=1)
        alarm_box = tk.Frame(side, bg=C["card"], padx=14, pady=10)
        alarm_box.grid(row=0, column=0, sticky="nsew")
        self._label(alarm_box, "ACTIVE ALARMS", 10, True, C["muted"]).pack(anchor="w")
        self.lbl_alarm = tk.Label(alarm_box, text="No active alarms", bg=C["card"], fg=C["green"], font=(FONT, 12, "bold"),
                                  justify="left", anchor="nw", wraplength=420)
        self.lbl_alarm.pack(fill="both", expand=True, pady=(6, 0))
        btns = tk.Frame(side, bg=C["bg"])
        btns.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        btns.columnconfigure((0, 1), weight=1, uniform="b")
        ttk.Button(btns, text="Print current report", style="Accent.TButton", command=self._report_current).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(btns, text="Close shift & reset", command=self._close_shift).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Button(btns, text="Export samples (CSV)", command=self._export_csv).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _build_hist(self) -> None:
        h = self.tab_hist
        h.columnconfigure(0, weight=3)
        h.columnconfigure(1, weight=2)
        h.rowconfigure(1, weight=1)
        self._label(h, "Closed shifts / periods", 12, True, bg=C["bg"]).grid(row=0, column=0, sticky="w", pady=(6, 4))
        self._label(h, "Alarm event log", 12, True, bg=C["bg"]).grid(row=0, column=1, sticky="w", padx=10, pady=(6, 4))
        cols = ("id", "start", "end", "oee", "a", "p", "q", "total", "scrap")
        heads = ("#", "Start", "End", "OEE %", "Avail %", "Perf %", "Qual %", "Parts", "Scrap")
        self.tv_shift = ttk.Treeview(h, columns=cols, show="headings", selectmode="browse")
        for c, t, w in zip(cols, heads, (40, 140, 140, 70, 70, 70, 70, 70, 60)):
            self.tv_shift.heading(c, text=t)
            self.tv_shift.column(c, width=w, anchor="center")
        self.tv_shift.grid(row=1, column=0, sticky="nsew")
        self.tv_alarm = ttk.Treeview(h, columns=("t", "a", "e"), show="headings")
        for c, t, w in (("t", "Time", 140), ("a", "Alarm", 210), ("e", "Event", 70)):
            self.tv_alarm.heading(c, text=t)
            self.tv_alarm.column(c, width=w)
        self.tv_alarm.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        row = tk.Frame(h, bg=C["bg"])
        row.grid(row=2, column=0, columnspan=2, sticky="w", pady=10)
        ttk.Button(row, text="Open / print selected shift report", style="Accent.TButton", command=self._report_selected).pack(side="left")
        ttk.Button(row, text="Refresh", command=self._refresh_history).pack(side="left", padx=8)
        ttk.Button(row, text="Open reports folder", command=lambda: self._open_path(app_home() / "reports")).pack(side="left")
        self._refresh_history()

    def _build_settings(self) -> None:
        f = tk.Frame(self.tab_set, bg=C["card"], padx=24, pady=18)
        f.pack(anchor="nw", padx=6, pady=6)
        self.vars = {
            "machine_name": tk.StringVar(value=self.st.machine_name), "plc_ip": tk.StringVar(value=self.st.plc_ip),
            "processor_slot": tk.StringVar(value=str(self.st.processor_slot)), "ideal_cycle_s": tk.StringVar(value=str(self.st.ideal_cycle_s)),
            "poll_s": tk.StringVar(value=str(self.st.poll_s)), "log_interval_s": tk.StringVar(value=str(self.st.log_interval_s)),
            "target_oee": tk.StringVar(value=str(self.st.target_oee)),
        }
        labels = [("machine_name", "Machine / line name"), ("plc_ip", "PLC IP address (SLC 5/05 or gateway)"),
                  ("processor_slot", "Processor slot"), ("ideal_cycle_s", "Ideal cycle time (seconds per part)"),
                  ("poll_s", "Poll interval (s)"), ("log_interval_s", "History log interval (s)"), ("target_oee", "OEE target (%)")]
        for i, (k, t) in enumerate(labels):
            self._label(f, t, 10).grid(row=i, column=0, sticky="w", pady=4)
            tk.Entry(f, textvariable=self.vars[k], width=30, bg=C["card2"], fg=C["text"], insertbackground=C["text"], relief="flat",
                     font=(FONT, 10)).grid(row=i, column=1, padx=14, pady=4)
        self.demo_var = tk.BooleanVar(value=self.st.demo_mode)
        self.write_var = tk.BooleanVar(value=self.st.allow_plc_write)
        for j, (var, txt) in enumerate([(self.demo_var, "Demo mode (built-in simulator, no PLC needed)"),
                                        (self.write_var, "Allow 'Close shift & reset' to write 1 to N7:11 (only write ever issued)")]):
            tk.Checkbutton(f, text=txt, variable=var, bg=C["card"], fg=C["text"], selectcolor=C["card2"], activebackground=C["card"],
                           activeforeground=C["text"], font=(FONT, 10)).grid(row=len(labels) + j, column=0, columnspan=2, sticky="w", pady=3)
        self._label(f, "Alarm names for N10:0 bits 0-15", 10, True, C["muted"]).grid(row=0, column=2, sticky="w", padx=(40, 0))
        self.alarm_vars = []
        for b in range(16):
            v = tk.StringVar(value=self.st.alarm_names.get(str(b), ""))
            self.alarm_vars.append(v)
            self._label(f, f"Bit {b:>2}", 9, fg=C["muted"]).grid(row=b + 1, column=2, sticky="e", padx=(40, 6))
            tk.Entry(f, textvariable=v, width=36, bg=C["card2"], fg=C["text"], insertbackground=C["text"], relief="flat",
                     font=(FONT, 9)).grid(row=b + 1, column=3, pady=1, rowspan=1)
        ttk.Button(f, text="Save & apply", style="Accent.TButton", command=self._save_settings).grid(
            row=len(labels) + 3, column=0, columnspan=2, sticky="w", pady=(18, 0))

    # ---- polling ------------------------------------------------------------------------------
    def _start_poller(self) -> None:
        if self.poller:
            self.poller.stop_evt.set()
        self.poller = Poller(self.st, self.q)
        self.poller.start()

    def _tick(self) -> None:
        self.lbl_clock.config(text=datetime.now().strftime("%a %Y-%m-%d  %H:%M:%S"))
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "snap":
                    self._on_snapshot(payload)
                elif kind == "error":
                    self._set_status(f"PLC COMMUNICATION LOST - {payload[:70]}", C["red"])
                elif kind == "reset":
                    if not payload:
                        messagebox.showwarning("Reset", "The PLC did not accept the reset request.")
        except queue.Empty:
            pass
        self.after(500, self._tick)

    def _set_status(self, text: str, color: str) -> None:
        self.lbl_status.config(text=text, bg=color, fg="white")

    def _counters(self, s: Snapshot) -> Counters:
        return Counters(s.run_s, s.idle_s, s.fault_s, s.planned_s, s.total, s.scrap, s.fault_events)

    def _on_snapshot(self, s: Snapshot) -> None:
        self.last = s
        k = compute_kpis(self._counters(s), self.st.ideal_cycle_s)
        tgt = self.st.target_oee
        if s.stale:
            self._set_status("PLC NOT SCANNING (heartbeat frozen) - check RUN mode", C["red"])
        else:
            self._set_status("DEMO MODE - SIMULATED DATA" if self.st.demo_mode else f"LIVE - {self.st.plc_ip}",
                             C["blue"] if self.st.demo_mode else C["green"])
        self.gauge.set(k.oee * 100, tgt)
        self.cards["a"].set(k.availability * 100, tgt)
        self.cards["p"].set(k.performance * 100, tgt, " *" if k.performance_capped else "")
        self.cards["q"].set(k.quality * 100, tgt)
        self.lbl_state.config(text=STATE_NAMES.get(s.state, "UNKNOWN"), bg=STATE_COLOR.get(s.state, C["track"]))
        st = self.stat
        st["total"].config(text=f"{s.total:,}")
        st["good"].config(text=f"{k.good:,}")
        st["scrap"].config(text=f"{s.scrap:,}")
        st["run"].config(text=fmt_hms(s.run_s))
        st["idle"].config(text=fmt_hms(s.idle_s))
        st["fault"].config(text=fmt_hms(s.fault_s))
        st["planned"].config(text=fmt_hms(s.planned_s))
        st["events"].config(text=str(s.fault_events))
        st["mtbf"].config(text=fmt_hms(k.mtbf_s))
        st["mttr"].config(text=fmt_hms(k.mttr_s))

        active = [self.st.alarm_name(b) for b in range(16) if (s.alarm_word >> b) & 1]
        self.lbl_alarm.config(text="\n".join("!  " + a for a in active) if active else "No active alarms",
                              fg=C["red"] if active else C["green"])
        changed = s.alarm_word ^ self.prev_alarm
        for b in range(16):
            if (changed >> b) & 1:
                self.db.add_alarm_event(s.ts, self.st.machine_name, b, self.st.alarm_name(b), bool((s.alarm_word >> b) & 1))
        if changed:
            self._refresh_history()
        self.prev_alarm = s.alarm_word

        if k.ppt_s > 0 and s.ts - self.last_log >= self.st.log_interval_s:
            self.db.add_sample(self.st.machine_name, s, k)
            self.last_log = s.ts
        self._refresh_trend()

    # ---- charts / tables -------------------------------------------------------------------
    def _range(self) -> tuple[float, float]:
        now = time.time()
        span = {"Last 1 hour": 3600, "Last 8 hours": 8 * 3600, "Last 24 hours": 86400, "Last 7 days": 7 * 86400}.get(self.range_var.get())
        return (now - span, now) if span else (self.period_start, now)

    def _refresh_trend(self, force: bool = False) -> None:
        if not force and time.time() - self.last_chart < 5:
            return
        self.last_chart = time.time()
        a, b = self._range()
        rows = self.db.samples_between(self.st.machine_name, a, b)
        ax = self.ax
        ax.clear()
        ax.set_facecolor(C["card"])
        for sp in ax.spines.values():
            sp.set_color(C["track"])
        ax.tick_params(colors=C["muted"], labelsize=8)
        if len(rows) >= 2:
            t = [datetime.fromtimestamp(r["ts"]) for r in rows]
            for key, lab, col, lw in (("oee", "OEE", C["accent"], 2.6), ("availability", "Availability", C["blue"], 1.2),
                                      ("performance", "Performance", C["amber"], 1.2), ("quality", "Quality", C["green"], 1.2)):
                ax.plot(t, [r[key] for r in rows], label=lab, color=col, lw=lw)
            ax.axhline(self.st.target_oee, color=C["red"], ls="--", lw=1)
            ax.legend(facecolor=C["card2"], edgecolor=C["track"], labelcolor=C["text"], fontsize=8, ncol=4, loc="lower left")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        else:
            ax.text(0.5, 0.5, "Collecting data... (history is logged every "
                    f"{self.st.log_interval_s} s)", color=C["muted"], ha="center", va="center", transform=ax.transAxes)
        ax.set_ylim(0, 105)
        ax.grid(color=C["track"], lw=0.5)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _refresh_history(self) -> None:
        if not hasattr(self, "tv_shift"):
            return
        for tv in (self.tv_shift, self.tv_alarm):
            tv.delete(*tv.get_children())
        fmt = lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        for r in self.db.shifts(self.st.machine_name):
            self.tv_shift.insert("", "end", iid=str(r["id"]), values=(r["id"], fmt(r["start_ts"]), fmt(r["end_ts"]),
                                 f"{r['oee']:.1f}", f"{r['availability']:.1f}", f"{r['performance']:.1f}", f"{r['quality']:.1f}",
                                 r["total"], r["scrap"]))
        for a in self.db.alarm_events(self.st.machine_name, limit=200):
            self.tv_alarm.insert("", "end", values=(datetime.fromtimestamp(a["ts"]).strftime("%m-%d %H:%M:%S"), a["text"],
                                                    "ACTIVE" if a["active"] else "cleared"))

    # ---- actions ---------------------------------------------------------------------------
    def _open_path(self, path) -> None:
        import os, subprocess, sys
        if sys.platform.startswith("win"):
            os.startfile(str(path))                                # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def _make_report(self, start: float, end: float, snap: Snapshot, ideal: float, name: str):
        c = self._counters(snap)
        k = compute_kpis(c, ideal)
        path = app_home() / "reports" / f"OEE_{self.st.machine_name.replace(' ', '_')}_{name}.pdf"
        report.build_report(path, self.st.machine_name, start, end, c, k, ideal, self.st.target_oee,
                            self.db.samples_between(self.st.machine_name, start, end),
                            self.db.alarm_events(self.st.machine_name, start, end))
        return path, k

    def _offer_print(self, path) -> None:
        if messagebox.askyesno("Report created", f"Saved:\n{path}\n\nSend it to the default printer now?"):
            try:
                report.print_file(path)
            except Exception as exc:
                messagebox.showerror("Print", f"Could not print automatically ({exc}).\nOpen the PDF and print it manually.")
                self._open_path(path)

    def _report_current(self) -> None:
        if not self.last:
            return messagebox.showinfo("Report", "No data received yet.")
        path, _ = self._make_report(self.period_start, time.time(), self.last, self.st.ideal_cycle_s,
                                    datetime.now().strftime("%Y%m%d_%H%M%S"))
        self._offer_print(path)

    def _close_shift(self) -> None:
        if not self.last:
            return messagebox.showinfo("Shift", "No data received yet.")
        if not messagebox.askyesno("Close shift", "Save this period to history, create the PDF report and reset the PLC counters?"):
            return
        snap, end = self.last, time.time()
        path, k = self._make_report(self.period_start, end, snap, self.st.ideal_cycle_s, f"shift_{datetime.now():%Y%m%d_%H%M%S}")
        self.db.add_shift(self.st.machine_name, self.period_start, end, self.st.ideal_cycle_s, snap, k)
        if self.st.demo_mode or self.st.allow_plc_write:
            self.poller.cmds.put("reset")
        else:
            messagebox.showinfo("Reset", "Automatic writes are disabled. Set N7:11 = 1 in the PLC to clear the counters.")
        self.period_start = end
        self.db.set_meta(f"period_start:{self.st.machine_name}", str(end))
        self._refresh_history()
        self._refresh_trend(force=True)
        self._offer_print(path)

    def _report_selected(self) -> None:
        sel = self.tv_shift.selection()
        if not sel:
            return messagebox.showinfo("Report", "Select a shift in the table first.")
        r = self.db.shift(int(sel[0]))
        snap = Snapshot(ts=r["end_ts"], state=0, total=r["total"], scrap=r["scrap"], run_s=r["run_s"], idle_s=r["idle_s"],
                        fault_s=r["fault_s"], planned_s=r["planned_s"], fault_events=r["fault_events"], alarm_word=0, heartbeat=0)
        path, _ = self._make_report(r["start_ts"], r["end_ts"], snap, r["ideal_cycle_s"], f"shift_{r['id']:05d}")
        self._offer_print(path)

    def _export_csv(self) -> None:
        a, b = self._range()
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="oee_samples.csv", filetypes=[("CSV", "*.csv")])
        if path:
            n = self.db.export_samples_csv(path, self.st.machine_name, a, b)
            messagebox.showinfo("Export", f"{n} rows exported.")

    def _save_settings(self) -> None:
        try:
            v = self.vars
            self.st.machine_name = v["machine_name"].get().strip() or "Machine"
            self.st.plc_ip = v["plc_ip"].get().strip()
            self.st.processor_slot = int(v["processor_slot"].get())
            self.st.ideal_cycle_s = float(v["ideal_cycle_s"].get())
            self.st.poll_s = max(0.5, float(v["poll_s"].get()))
            self.st.log_interval_s = max(1, int(float(v["log_interval_s"].get())))
            self.st.target_oee = float(v["target_oee"].get())
            if self.st.ideal_cycle_s <= 0:
                raise ValueError("Ideal cycle time must be greater than zero")
        except ValueError as exc:
            return messagebox.showerror("Settings", f"Invalid value: {exc}")
        self.st.demo_mode = self.demo_var.get()
        self.st.allow_plc_write = self.write_var.get()
        self.st.alarm_names = {str(i): var.get().strip() for i, var in enumerate(self.alarm_vars) if var.get().strip()}
        self.st.save()
        self.lbl_machine.config(text=self.st.machine_name)
        self.period_start = float(self.db.get_meta(f"period_start:{self.st.machine_name}", str(time.time())))
        self.prev_alarm = 0
        self._start_poller()
        self._refresh_history()
        messagebox.showinfo("Settings", "Settings saved and applied.")

    def _close(self) -> None:
        if self.poller:
            self.poller.stop_evt.set()
        self.db.close()
        self.destroy()


def main() -> None:
    App().mainloop()
