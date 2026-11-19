"""每個 flag、每個狀態（on/off）的事件計數，給 Operator 監控與 HDD 比較用。

事件：
- exposure        使用者看到某個版本（分母）
- practice        有開始複習（ON：產生題目；OFF：按「標記已複習」）
- quiz_reported   使用者回報 AI 題目有誤（H1 防護指標）
- reminder_set    加入複習排程
- reminder_optout 關閉提醒（H2 防護指標）
- blocked         toggle OFF 的使用者直接打 API 被擋
正式上線時改送到 Prometheus / 資料庫。
"""
from __future__ import annotations

import threading
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._c: Counter = Counter()
        self._lock = threading.Lock()

    def record(self, flag: str, variant: str, event: str) -> None:
        with self._lock:
            self._c[(flag, variant, event)] += 1

    def get(self, flag: str, variant: str, event: str) -> int:
        return self._c[(flag, variant, event)]

    def table(self, flags: list[str]) -> list[dict]:
        events = ["exposure", "practice", "quiz_reported", "reminder_set", "reminder_optout", "blocked"]
        rows = []
        for f in flags:
            for v in ("on", "off"):
                row = {"flag": f, "variant": v}
                row.update({e: self.get(f, v, e) for e in events})
                rows.append(row)
        return rows
