# -*- coding: utf-8 -*-
"""Probe chat responses over SSE for report evidence."""
import json
import urllib.request

TOKEN = open(r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\token.txt", encoding="utf-8").read().strip()
URL = "http://localhost:8080/api/chat/stream"
QUESTIONS = [
    "今天昆明方管 100*100*2.5*6m 多少钱一吨？",
    "100*100*1.5*6m 和 100*100*2.5*6m 最近30天的价差走势怎么样？",
    "最近有哪些规格出现价格异动或库存偏低？",
    "根据知识库中的《报价规则》，含税价怎么计算？请给出引用。",
    "库存里 100*100*2.5*6m 还有多少支？",
]
out = []
for q in QUESTIONS:
    req = urllib.request.Request(
        URL,
        data=json.dumps({"message": q}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    text = []
    artifacts = []
    events = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if line.startswith("event:"):
                events.append(line[6:].strip())
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if "text" in data:
                    text.append(data["text"])
                elif "type" in data:
                    artifacts.append(data["type"])
    answer = "".join(text)
    out.append({"q": q, "answer": answer, "artifacts": artifacts, "events": events})
    print("=" * 70)
    print("Q:", q)
    print("A:", answer)
    print("artifacts:", artifacts)

with open(r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\probe_answers.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
