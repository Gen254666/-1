# -*- coding: utf-8 -*-
"""Remaining six test cases for the report's test matrix."""
import json
import time
import urllib.error
import urllib.request

TOKEN = open(r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\token.txt", encoding="utf-8").read().strip()
URL = "http://localhost:8080/api/chat/stream"
CASES = [
    ("查价", "150*150*3.0*6m 方管多少钱一吨？"),
    ("走势", "200*200*5.75*6m 方管最近一个月的价格走势怎么样？"),
    ("异动", "有没有价格异动的规格？"),
    ("知识", "我们公司主要做哪些品类和哪些地区？"),
    ("知识", "报价以什么价格为准？最终成交价怎么定？"),
    ("边界", "你好，你能做什么？"),
]


def ask(question):
    req = urllib.request.Request(
        URL,
        data=json.dumps({"message": question}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    started = time.time()
    text, artifacts, http_error = [], [], None
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if "text" in data:
                        text.append(data["text"])
                    elif data.get("type"):
                        artifacts.append(data["type"])
    except urllib.error.HTTPError as exc:
        http_error = exc.read().decode("utf-8")
    return {
        "answer": "".join(text),
        "artifacts": artifacts,
        "elapsed": round(time.time() - started, 2),
        "http_error": http_error,
    }


results = []
for kind, question in CASES:
    r = ask(question)
    results.append({"kind": kind, "question": question, **r})
    print(kind, question, r["elapsed"], r["artifacts"])
    print("  ", (r["answer"] or r["http_error"] or "")[:260].replace("\n", " "))
    time.sleep(3)

with open(
    r"C:\Users\Lenovo\Desktop\钢材市场行情分析\_report_build\test_suite_extra.json",
    "w",
    encoding="utf-8",
) as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)
print("saved", len(results))
