# -*- coding: utf-8 -*-
"""Dump the course report template structure for inspection."""
import sys

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

SRC = r"C:\Users\Lenovo\Desktop\课程实验报告模板-智能体开发平台模式(1).docx"
OUT = r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\template_dump.txt"


def iter_block_items(parent):
    from docx.oxml.ns import qn

    body = parent.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


doc = Document(SRC)
lines = []
lines.append(f"section: {doc.sections[0].page_width}x{doc.sections[0].page_height} margins "
             f"L{doc.sections[0].left_margin} R{doc.sections[0].right_margin} T{doc.sections[0].top_margin}")
idx = 0
for block in iter_block_items(doc):
    if isinstance(block, Paragraph):
        txt = block.text
        style = block.style.name if block.style is not None else ""
        fmt = []
        if block.paragraph_format.alignment is not None:
            fmt.append(f"align={block.paragraph_format.alignment}")
        if block.paragraph_format.first_line_indent is not None:
            fmt.append(f"indent={block.paragraph_format.first_line_indent}")
        runs = []
        for r in block.runs[:4]:
            f = r.font
            runs.append(f"[{r.text[:20]!r} font={f.name} sz={f.size} b={f.bold}]")
        lines.append(f"P{idx:03d} <{style}> {' '.join(fmt)} :: {txt!r}")
        if runs:
            lines.append("      runs: " + " ".join(runs))
        idx += 1
    else:
        lines.append(f"TABLE rows={len(block.rows)} cols={len(block.columns)}")
        for ri, row in enumerate(block.rows[:6]):
            cells = [c.text.replace("\n", "|")[:30] for c in row.cells]
            lines.append(f"   R{ri}: {cells}")
        idx += 1

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print(f"wrote {OUT} blocks={idx}")
print("styles:", sorted({p.style.name for p in doc.paragraphs}))
