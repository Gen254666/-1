# -*- coding: utf-8 -*-
"""Check run properties in the generated report."""
from docx import Document
from docx.oxml.ns import qn

PATH = r"C:\Users\Lenovo\Desktop\钢材市场行情分析\钢材市场行情分析系统-实验报告.docx"
doc = Document(PATH)
for p in doc.paragraphs:
    if p.text.startswith("本项目源于"):
        print("paragraph style:", p.style.name)
        print("pPr:", p._p.pPr.xml[:600] if p._p.pPr is not None else None)
        r = p.runs[0]
        print("run rPr:", r._element.rPr.xml[:600] if r._element.rPr is not None else None)
        print("italic:", r.italic, "font:", r.font.name, "size:", r.font.size)
        break
st = doc.styles["Normal"]
print("Normal italic:", st.font.italic)
print("Normal xml:", st.element.xml[:800])
