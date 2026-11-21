# -*- coding: utf-8 -*-
"""Second probe: knowledge answer and inventory summary."""
import json
import urllib.request

TOKEN = open(r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\token.txt", encoding="utf-8").read().strip()
URL = "http://localhost:8080/api/chat/stream"
QUESTIONS = [
    "根据知识库中的《报价规则》，含税价怎么计算？请给出引用。",
    "今天昆明宝象库一共多少条库存规格？",
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
    with urllib.request.urlopen(req, timeout=240) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
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
    out.append({"q": q, "answer": answer, "artifacts": artifacts})
    print("Q:", q)
    print("A:", answer)
    print("artifacts:", artifacts)
    print("-" * 60)

with open(
    r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\probe_answers2.json", "w", encoding="utf-8"
) as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
