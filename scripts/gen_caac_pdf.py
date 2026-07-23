#!/usr/bin/env python3
"""Generate formal CAAC inquiry letter PDF from markdown."""
import re
import sys
from pathlib import Path
from weasyprint import HTML

MD_PATH = Path(__file__).parent.parent / "docs" / "CAAC_UOM_咨询函.md"
OUT_PATH = Path(__file__).parent.parent / "docs" / "CAAC_UOM_咨询函.pdf"

def md_to_html(md: str) -> str:
    """Simple markdown to HTML converter for the letter."""
    lines = md.split("\n")
    html_parts = []
    in_table = False
    table_rows = []
    in_list = False

    def flush_table():
        nonlocal table_rows, in_table
        if not table_rows:
            in_table = False
            return
        html = '<table class="letter-table">'
        for i, row in enumerate(table_rows):
            cells = [c.strip() for c in row.split("|") if c.strip()]
            if not cells:
                continue
            tag = "th" if i == 0 else "td"
            html += "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
        html += "</table>"
        html_parts.append(html)
        table_rows = []
        in_table = False

    for line in lines:
        stripped = line.strip()

        # Table detection
        if stripped.startswith("|") and "|" in stripped[1:]:
            # Skip separator rows
            if re.match(r'^\|[\s\-:|]+\|$', stripped):
                continue
            in_table = True
            table_rows.append(stripped)
            continue
        elif in_table:
            flush_table()

        # Headings
        if stripped.startswith("# ") and not stripped.startswith("## "):
            html_parts.append(f'<div class="doc-title">{stripped[2:]}</div>')
            continue
        if stripped.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f'<h2>{stripped[3:]}</h2>')
            continue
        if stripped.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f'<h3>{stripped[4:]}</h3>')
            continue

        # Horizontal rule
        if stripped == "---":
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append('<hr/>')
            continue

        # Bold blockquote
        if stripped.startswith("> "):
            html_parts.append(f'<div class="note">{stripped[2:]}</div>')
            continue

        # List items
        if re.match(r'^\d+\.\s', stripped):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f'<li>{stripped}</li>')
            continue
        elif stripped.startswith("- ") or stripped.startswith("• "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f'<li>{stripped[2:]}</li>')
            continue

        # Empty line
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        # Regular paragraph
        if in_list:
            html_parts.append("</ul>")
            in_list = False
        # Bold text **xxx** -> <strong>xxx</strong>
        clean = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
        html_parts.append(f'<p>{clean}</p>')

    if in_table:
        flush_table()
    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


CSS = """
@page {
    size: A4;
    margin: 2.5cm 2.8cm 2.5cm 2.8cm;
    @bottom-center {
        content: counter(page);
        font-family: "Noto Sans CJK SC", sans-serif;
        font-size: 9pt;
        color: #666;
    }
}

body {
    font-family: "Noto Sans CJK SC", "Source Han Sans SC", "SimSun", serif;
    font-size: 11pt;
    line-height: 1.8;
    color: #1a1a1a;
}

.doc-title {
    font-size: 16pt;
    font-weight: bold;
    text-align: center;
    margin: 0 0 0.8cm 0;
    line-height: 1.5;
}

h2 {
    font-size: 12.5pt;
    font-weight: bold;
    border-left: 3pt solid #1C3A5E;
    padding-left: 8pt;
    margin-top: 0.6cm;
    margin-bottom: 0.2cm;
    color: #1C3A5E;
}

h3 {
    font-size: 11.5pt;
    font-weight: bold;
    margin-top: 0.4cm;
    margin-bottom: 0.15cm;
    color: #333;
}

p {
    margin: 0.15cm 0;
    text-align: justify;
}

ul {
    margin: 0.15cm 0;
    padding-left: 0.8cm;
}

li {
    margin: 0.08cm 0;
    text-align: justify;
}

.letter-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.3cm 0;
    font-size: 10pt;
    line-height: 1.6;
}

.letter-table th {
    background-color: #1C3A5E;
    color: white;
    padding: 6pt 8pt;
    text-align: left;
    font-weight: bold;
    border: 0.5pt solid #1C3A5E;
}

.letter-table td {
    padding: 5pt 8pt;
    border: 0.5pt solid #ccc;
    vertical-align: top;
}

.letter-table tr:nth-child(even) td {
    background-color: #f8f9fa;
}

hr {
    border: none;
    border-top: 0.5pt solid #ccc;
    margin: 0.4cm 0;
}

.note {
    background-color: #fff3cd;
    padding: 8pt 12pt;
    border-left: 3pt solid #ffc107;
    margin: 0.3cm 0;
    font-size: 10pt;
    color: #856404;
}
"""

def main():
    md = MD_PATH.read_text(encoding="utf-8")
    body_html = md_to_html(md)
    full_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body_html}</body></html>"
    HTML(string=full_html).write_pdf(str(OUT_PATH))
    print(f"PDF generated: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")

if __name__ == "__main__":
    main()
