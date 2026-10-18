# -*- coding: utf-8 -*-
"""本地学科知识库：不依赖网络或 LLM，可被 dispatcher/API/脚本复用。"""
from __future__ import annotations
import argparse, json, os, re
from typing import Any, Dict, List
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_db.json")

def load(path: str = _PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)

def subjects(path: str = _PATH) -> List[str]:
    return list(load(path).get("subjects", {}).keys())

def _resolve(subject: str, db: Dict[str, Any]) -> str:
    s = subject.strip().lower()
    for name, data in db.get("subjects", {}).items():
        if s == name.lower() or s in [str(a).lower() for a in data.get("aliases", [])]:
            return name
    return ""

def search(query: str, subject: str = "", limit: int = 5, path: str = _PATH) -> List[Dict[str, Any]]:
    db = load(path)
    names = [_resolve(subject, db)] if subject else list(db.get("subjects", {}))
    query_text = query.strip().lower()
    terms = [x for x in re.split(r"\s+|[,，。；;、]", query_text) if x]
    out = []
    for name in names:
        if not name: continue
        for topic, item in db["subjects"][name].get("topics", {}).items():
            hay = " ".join([name, topic, item.get("summary", ""), " ".join(item.get("pitfalls", []))]).lower()
            score = sum(1 for term in terms if term in hay) if terms else 1
            # 中文问题通常没有空格，整句分词会错过主题名；主题名直接
            # 出现在问题中时优先命中（例如“傅里叶变换是什么”）。
            if topic.lower() in query_text:
                score += 3
            if score:
                out.append({"subject": name, "topic": topic, "score": score, "summary": item.get("summary", ""), "formulas": item.get("formulas", []), "pitfalls": item.get("pitfalls", [])})
    out.sort(key=lambda x: (-x["score"], x["subject"], x["topic"]))
    return out[:max(1, limit)]

def format_results(results: List[Dict[str, Any]]) -> str:
    if not results: return "知识库中没有找到匹配内容。可用科目：" + "、".join(subjects())
    lines = []
    for r in results:
        lines.append("【%s / %s】%s" % (r["subject"], r["topic"], r["summary"]))
        if r["formulas"]: lines.append("公式：" + "；".join(r["formulas"]))
        if r["pitfalls"]: lines.append("易错点：" + "；".join(r["pitfalls"]))
    return "\n".join(lines)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="查询本地四科知识库")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--subject", default="")
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    print("可用科目：" + "、".join(subjects()) if not args.query and not args.subject else format_results(search(args.query, args.subject, args.limit)))
