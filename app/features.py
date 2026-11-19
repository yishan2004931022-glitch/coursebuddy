"""兩個實驗功能的商業邏輯。

ai_quiz：目前是「規則式假題目」（MVF），之後換成真的 LLM。
LLM 的 API key 只從環境變數讀取（本機 .env、CI 由 GitHub Secrets 注入），絕不寫進程式碼。
"""
from __future__ import annotations

import os
import random
import re
from datetime import date, timedelta

REVIEW_OFFSETS = (1, 3, 7)  # 間隔重複：第 1、3、7 天


def review_schedule(start: date) -> list[date]:
    return [start + timedelta(days=d) for d in REVIEW_OFFSETS]


def llm_configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def generate_quiz(text: str, n: int = 5, seed: int = 0) -> list[dict]:
    """把講義的句子挖空成選擇題。TODO：設定 LLM_API_KEY 後改呼叫 LLM。"""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s*", text) if s.strip()]
    words = sorted({w for w in re.findall(r"[A-Za-z][A-Za-z-]{4,}", text)}, key=str.lower)
    rng = random.Random(seed)
    quiz = []
    for s in sentences:
        cands = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{4,}", s)]
        if not cands:
            continue
        answer = max(cands, key=len)
        distractors = [w for w in words if w.lower() != answer.lower()]
        if len(distractors) < 3:
            continue
        options = rng.sample(distractors, 3) + [answer]
        rng.shuffle(options)
        quiz.append({
            "question": s.replace(answer, "_____", 1),
            "options": options,
            "answer": answer,
        })
        if len(quiz) == n:
            break
    return quiz
