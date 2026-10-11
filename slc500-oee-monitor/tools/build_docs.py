"""Builds PDFs (guide, article) and the article web page from the Markdown sources.

Run from the repository root:   python tools/build_plc.py && python tools/build_docs.py
Requires: reportlab, markdown
"""
import html
import re
import textwrap
from datetime import date
from pathlib import Path

import markdown
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageTemplate, Paragraph,
                                Preformatted, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
NAVY, BLUE, GREY = colors.HexColor("#0F172A"), colors.HexColor("#0369A1"), colors.HexColor("#475569")

S = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=NAVY, spaceAfter=4),
    "sub": ParagraphStyle("sub", fontName="Helvetica-Oblique", fontSize=11.5, leading=15, textColor=BLUE, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=NAVY, spaceBefore=14, spaceAfter=5, keepWithNext=1),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=BLUE, spaceBefore=9, spaceAfter=3, keepWithNext=1),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9.6, leading=13.4, spaceAfter=5),
    "li": ParagraphStyle("li", fontName="Helvetica", fontSize=9.6, leading=13.2, leftIndent=20, bulletIndent=6, spaceAfter=2.5),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.2, leading=10.2),
    "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8.2, leading=10.2, textColor=colors.white),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=6.9, leading=8.3, backColor=colors.HexColor("#F1F5F9"),
                           borderPadding=4, leftIndent=4, spaceBefore=3, spaceAfter=6),
    "quote": ParagraphStyle("quote", fontName="Helvetica", fontSize=9.4, leading=13, textColor=NAVY),
}


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier" size="8.6">\1</font>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<i>\1</i>", text)
    return text


def expand_includes(md: str) -> str:
    def repl(m):
        body = (ROOT / m.group(1)).read_text(encoding="utf-8").split("\n", 1)[1]
        body = body.replace("## Data table map", "### A. Data table map")
        body = re.sub(r"## Rungs \(", "### B. Ladder rungs (", body)
        return body
    return re.sub(r"\{\{include:(.+?)\}\}", repl, md)


def make_table(rows, avail):
    lens = [max(len(re.sub(r"[`*]", "", r[c])) for r in rows) for c in range(len(rows[0]))]
    weights = [min(max(l, 9), 70) ** 0.85 for l in lens]
    widths = [avail * w / sum(weights) for w in weights]
    data = [[Paragraph(inline(c), S["cellh"] if i == 0 else S["cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def md_to_story(md: str, avail: float):
    lines, story, i = md.split("\n"), [], 0
    para: list[str] = []

    def flush():
        if para:
            story.append(Paragraph(inline(" ".join(para)), S["p"]))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush()
            block = []
            i += 1
            while not lines[i].startswith("```"):
                l = lines[i]
                block += textwrap.wrap(l, 104, subsequent_indent="      ") or [""] if l.lstrip().startswith(";") and len(l) > 104 else [l]
                i += 1
            story.append(KeepTogether(Preformatted("\n".join(block), S["code"])))
        elif ln.startswith("# "):
            flush(); story.append(Paragraph(inline(ln[2:]), S["title"]))
        elif ln.startswith("## "):
            flush(); story.append(Paragraph(inline(ln[3:]), S["h2"]))
            story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1"), spaceAfter=4))
        elif ln.startswith("### "):
            flush(); story.append(Paragraph(inline(ln[4:]), S["h3"]))
        elif ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            story += [make_table(rows, avail), Spacer(1, 7)]
            continue
        elif ln.startswith("> "):
            flush()
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i][1:].strip()); i += 1
            box = Table([[Paragraph(inline(" ".join(q)), S["quote"])]], colWidths=[avail])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E0F2FE")),
                                     ("LINEBEFORE", (0, 0), (0, -1), 3, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                     ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
            story += [box, Spacer(1, 8)]
            continue
        elif re.match(r"^\d+\. ", ln):
            flush(); n, txt = ln.split(". ", 1)
            story.append(Paragraph(inline(txt), S["li"], bulletText=f"{n}."))
        elif ln.startswith("- "):
            flush(); story.append(Paragraph(inline(ln[2:]), S["li"], bulletText="\u2022"))
        elif re.fullmatch(r"\*[^*].*\*", ln.strip()) and story and len(story) == 1:
            story.append(Paragraph(inline(ln.strip()), S["sub"]))
        elif not ln.strip():
            flush()
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return story


def build_pdf(md_path: Path, pdf_path: Path, header: str):
    md = expand_includes(md_path.read_text(encoding="utf-8"))
    title = md.split("\n", 1)[0][2:]

    def deco(canv, doc):
        canv.saveState()
        canv.setFont("Helvetica", 7.5); canv.setFillColor(GREY)
        canv.drawString(0.75 * inch, 10.55 * inch, header)
        canv.drawRightString(7.75 * inch, 10.55 * inch, f"Rev 1.0 - {date.today():%Y-%m-%d}")
        canv.setStrokeColor(colors.HexColor("#CBD5E1")); canv.line(0.75 * inch, 10.5 * inch, 7.75 * inch, 10.5 * inch)
        canv.drawString(0.75 * inch, 0.5 * inch, "MIT licence - provided as is; validate before production use")
        canv.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
        canv.restoreState()

    doc = BaseDocTemplate(str(pdf_path), pagesize=letter, title=title, author="[Author Name]", subject=header)
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(0.75 * inch, 0.75 * inch, 7.0 * inch, 9.6 * inch, id="f")], onPage=deco)])
    doc.build(md_to_story(md, 7.0 * inch))
    print("wrote", pdf_path)


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="author" content="[Author Name]">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"TechArticle","headline":{jtitle},"description":{jdesc},
"author":{{"@type":"Person","name":"[Author Name]"}},"datePublished":"{today}","inLanguage":"en-US",
"about":["Overall Equipment Effectiveness","Legacy PLC modernization","Smart manufacturing"]}}
</script>
<style>
:root{{--bg:#fff;--fg:#0f172a;--muted:#475569;--accent:#0369a1;--line:#cbd5e1;--soft:#f1f5f9;--callout:#e0f2fe;--code:#f1f5f9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--fg:#e6edf7;--muted:#9fb1cc;--accent:#38bdf8;--line:#2a3b57;--soft:#152033;--callout:#10304a;--code:#152033}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 Georgia,'Times New Roman',serif}}
header.site{{border-bottom:1px solid var(--line);padding:14px 20px;font:600 14px system-ui,sans-serif;letter-spacing:.06em;color:var(--accent)}}
main{{max-width:820px;margin:0 auto;padding:32px 20px 64px}}
h1{{font:800 clamp(28px,5vw,40px)/1.15 system-ui,sans-serif;margin:.2em 0 .3em}}
h2{{font:700 25px/1.25 system-ui,sans-serif;margin:2em 0 .5em;padding-bottom:.25em;border-bottom:2px solid var(--line)}}
h1+p em{{font:italic 20px/1.4 Georgia,serif;color:var(--accent)}}
p,li{{margin:.7em 0}}blockquote{{margin:1.4em 0;padding:1px 20px;background:var(--callout);border-left:5px solid var(--accent);border-radius:4px}}
table{{width:100%;border-collapse:collapse;margin:1.3em 0;font:15px/1.45 system-ui,sans-serif;display:block;overflow-x:auto}}
th{{background:#0f172a;color:#fff;text-align:left}}th,td{{border:1px solid var(--line);padding:7px 10px;vertical-align:top}}
tr:nth-child(even) td{{background:var(--soft)}}code{{background:var(--code);padding:1px 5px;border-radius:3px;font-size:.88em}}
a{{color:var(--accent)}}footer{{max-width:820px;margin:0 auto;padding:0 20px 40px;font:14px system-ui,sans-serif;color:var(--muted)}}
@media print{{header.site{{display:none}}body{{font-size:11pt}}a{{color:inherit}}}}
</style>
</head>
<body>
<header class="site">ENGINEERING &amp; MANUFACTURING TECHNOLOGY</header>
<main><article>
{body}
</article></main>
<footer>&copy; {year} [Author Name]. Code and documentation released under the MIT licence.</footer>
</body>
</html>
"""


def build_html(md_path: Path, out: Path):
    md = md_path.read_text(encoding="utf-8")
    title = md.split("\n", 1)[0][2:]
    desc = re.search(r"\*\*Summary\.\*\*\s*(.+)", md).group(1).strip()
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    import json
    out.write_text(HTML.format(title=html.escape(title), desc=html.escape(desc, quote=True), jtitle=json.dumps(title),
                               jdesc=json.dumps(desc), today=date.today().isoformat(), year=date.today().year, body=body),
                   encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    build_pdf(ROOT / "docs/Implementation_Guide.md", ROOT / "docs/Implementation_Guide.pdf", "SLC 500 OEE Monitor - Implementation Guide v1.0")
    build_pdf(ROOT / "docs/Article.md", ROOT / "docs/Article.pdf", "Engineering article")
    build_html(ROOT / "docs/Article.md", ROOT / "site/index.html")
