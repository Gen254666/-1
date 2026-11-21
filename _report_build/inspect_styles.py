# -*- coding: utf-8 -*-
"""Inspect template default fonts and styles."""
from docx import Document
from docx.oxml.ns import qn

SRC = r"C:\Users\Lenovo\Desktop\课程实验报告模板-智能体开发平台模式(1).docx"
doc = Document(SRC)
for name in ["Normal", "Heading 1", "Heading 2", "List Paragraph", "Plain Text"]:
    st = doc.styles[name]
    f = st.font
    rpr = st.element.find(qn("w:rPr"))
    ea = None
    if rpr is not None:
        rf = rpr.find(qn("w:rFonts"))
        if rf is not None:
            ea = rf.get(qn("w:eastAsia"))
    print(name, "font=", f.name, "size=", f.size, "bold=", f.bold, "eastAsia=", ea)
sec = doc.sections[0]
print("page", sec.page_width, sec.page_height, sec.left_margin, sec.right_margin)
print("cols", len(doc.tables))
for i, t in enumerate(doc.tables):
    print(i, "rows", len(t.rows), "cols", len(t.columns), "style", t.style.name if t.style else None,
          "autofit", t.autofit)
