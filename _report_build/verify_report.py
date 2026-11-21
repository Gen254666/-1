# -*- coding: utf-8 -*-
"""Verify the generated report."""
from docx import Document

PATH = r"C:\Users\Lenovo\Desktop\钢材市场行情分析\钢材市场行情分析系统-实验报告.docx"
doc = Document(PATH)
texts = [p.text for p in doc.paragraphs]
placeholders = [t for t in texts if "在此处填写" in t or "在此处插入图片" in t]
print("paragraphs:", len(texts))
print("images:", len(doc.inline_shapes))
print("tables:", len(doc.tables))
print("placeholders left:", placeholders)
print("empty paragraphs:", sum(1 for t in texts if not t.strip()))
for i, t in enumerate(doc.tables):
    print(f"table{i}: {len(t.rows)}x{len(t.columns)} first={t.rows[0].cells[0].text!r} "
          f"last={t.rows[-1].cells[-1].text[:30]!r}")
chars = sum(len(t) for t in texts)
print("chars:", chars)
for t in texts:
    if "图 " in t and t.startswith("图 "):
        print("caption:", t)
