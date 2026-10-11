"""Printable PDF shift / period report (reportlab + matplotlib, no external services)."""
from __future__ import annotations

import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .oee import Counters, KPIs, fmt_hms

NAVY, GREEN, AMBER, RED = colors.HexColor("#0F172A"), colors.HexColor("#15803D"), colors.HexColor("#B45309"), colors.HexColor("#B91C1C")


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _chart(samples: list[dict], c: Counters, k: KPIs, target: float) -> bytes:
    fig = Figure(figsize=(7.4, 3.0), dpi=150)
    FigureCanvasAgg(fig)
    ax1, ax2 = fig.subplots(1, 2, gridspec_kw={"width_ratios": [2.2, 1]})
    if len(samples) >= 2:
        t = [datetime.fromtimestamp(r["ts"]) for r in samples]
        for key, lab, col in (("oee", "OEE", "#0F172A"), ("availability", "Availability", "#2563EB"),
                              ("performance", "Performance", "#D97706"), ("quality", "Quality", "#16A34A")):
            ax1.plot(t, [r[key] for r in samples], label=lab, color=col, lw=2.0 if key == "oee" else 1.1)
        ax1.axhline(target, color="#DC2626", ls="--", lw=0.9, label=f"Target {target:.0f}%")
        ax1.set_ylim(0, 105)
        ax1.legend(fontsize=6, ncol=5, loc="lower center")
        fig.autofmt_xdate(rotation=20)
    else:
        ax1.text(0.5, 0.5, "Not enough logged samples", ha="center", va="center", transform=ax1.transAxes)
    ax1.set_title("KPI trend (%)", fontsize=8)
    ax1.tick_params(labelsize=6)
    labels = ["Run", "Idle", "Fault"]
    vals = [c.run_s, c.idle_s, c.fault_s]
    ax2.bar(labels, [v / 3600 for v in vals], color=["#16A34A", "#F59E0B", "#DC2626"])
    ax2.set_title("Planned production time (h)", fontsize=8)
    ax2.tick_params(labelsize=7)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return buf.getvalue()


def build_report(path: Path, machine: str, start_ts: float, end_ts: float, c: Counters, k: KPIs,
                 ideal_cycle_s: float, target_oee: float, samples: list[dict], alarms: list[dict],
                 title: str = "OEE Performance Report") -> Path:
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, textColor=NAVY, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11.5, textColor=NAVY, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"))
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9)

    def color_for(v: float) -> colors.Color:
        return GREEN if v >= target_oee else AMBER if v >= 0.7 * target_oee else RED

    def table(data, widths, header=True):
        t = Table(data, colWidths=widths)
        style = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                      ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        t.setStyle(TableStyle(style))
        return t

    ppt = max(k.ppt_s, 1)
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch, title=f"{title} - {machine}")
    s: list = [Paragraph(title, h1), Paragraph(f"{machine}", body), Spacer(1, 6)]
    s.append(table([["Period start", _stamp(start_ts), "Period end", _stamp(end_ts)],
                    ["Ideal cycle time", f"{ideal_cycle_s:g} s/part", "OEE target", f"{target_oee:g} %"]],
                   [1.2 * inch, 2.4 * inch, 1.2 * inch, 2.3 * inch], header=False))

    s.append(Paragraph("1. Key performance indicators", h2))
    kp = [["Indicator", "Value", "Meaning"],
          ["OEE", f"{k.oee * 100:.1f} %", "Availability x Performance x Quality"],
          ["Availability", f"{k.availability * 100:.1f} %", "Run time / planned production time"],
          ["Performance", f"{k.performance * 100:.1f} %" + (" (capped)" if k.performance_capped else ""),
           "Ideal cycle time x total count / run time"],
          ["Quality", f"{k.quality * 100:.1f} %", "Good parts / total parts"]]
    t = table(kp, [1.3 * inch, 1.3 * inch, 4.5 * inch])
    t.setStyle(TableStyle([("TEXTCOLOR", (1, 1), (1, 1), color_for(k.oee * 100)), ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold")]))
    s.append(t)
    if k.performance_capped:
        s.append(Paragraph("Note: calculated performance exceeded 100 % and was capped. Verify that the ideal cycle time is not set too high.", small))

    s.append(Paragraph("2. Production and time accounting", h2))
    rows = [["Item", "Value", "% of PPT"],
            ["Run time", fmt_hms(c.run_s), f"{c.run_s / ppt * 100:.1f} %"],
            ["Idle time (starved / blocked / no operator)", fmt_hms(c.idle_s), f"{c.idle_s / ppt * 100:.1f} %"],
            ["Fault time (breakdowns)", fmt_hms(c.fault_s), f"{c.fault_s / ppt * 100:.1f} %"],
            ["Planned stops (excluded from OEE)", fmt_hms(c.planned_s), "excluded"],
            ["Total parts / good parts / scrap", f"{c.total} / {k.good} / {c.scrap}", ""],
            ["Fault events  |  MTBF  |  MTTR", f"{c.fault_events}  |  {fmt_hms(k.mtbf_s)}  |  {fmt_hms(k.mttr_s)}", "h:mm:ss"],
            ["Speed loss  |  Quality loss (time)", f"{fmt_hms(k.speed_loss_s)}  |  {fmt_hms(k.quality_loss_s)}", "h:mm:ss"]]
    s.append(table(rows, [3.3 * inch, 2.1 * inch, 1.7 * inch]))

    s.append(Paragraph("3. Trends", h2))
    s.append(Image(io.BytesIO(_chart(samples, c, k, target_oee)), width=7.0 * inch, height=2.84 * inch))

    s.append(Paragraph("4. Alarm history (most recent first)", h2))
    if alarms:
        data = [["Time", "Alarm", "Event"]] + [[_stamp(a["ts"]), a["text"], "ACTIVE" if a["active"] else "cleared"] for a in alarms[:20]]
        s.append(table(data, [1.7 * inch, 4.0 * inch, 1.4 * inch]))
    else:
        s.append(Paragraph("No alarm events recorded in this period.", body))

    s.append(Spacer(1, 18))
    s.append(table([["Prepared by:", "", "Reviewed by:", ""], ["Date:", "", "Date:", ""]],
                   [1.0 * inch, 2.5 * inch, 1.0 * inch, 2.6 * inch], header=False))
    s.append(Spacer(1, 8))
    s.append(Paragraph("Method: OEE = Availability x Performance x Quality per the structure of ISO 22400-2:2014; planned "
                       "production time excludes planned stops. Generated automatically by SLC 500 OEE Monitor "
                       f"(open source, MIT licence) on {_stamp(datetime.now().timestamp())}.", small))
    doc.build(s)
    return path


def print_file(path: Path) -> None:
    """Send a PDF to the default printer (Windows: shell 'print' verb; macOS/Linux: lp)."""
    if sys.platform.startswith("win"):
        os.startfile(str(path), "print")                       # type: ignore[attr-defined]
    else:
        subprocess.Popen(["lp", str(path)])
