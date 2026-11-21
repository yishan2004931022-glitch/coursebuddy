"""示範用的記憶體資料庫。之後換成 SQLite / PostgreSQL 時，只要維持同樣的方法即可。"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date


@dataclass
class User:
    id: str
    name: str
    role: str                                   # student / ta / admin
    email: str = ""
    courses: set[str] = field(default_factory=set)  # 學生：修的課；助教：帶的課


@dataclass
class Material:
    id: int
    title: str
    text: str
    owner_id: str
    course_id: str | None = None   # 有值 = 課程官方講義（助教上傳）
    reminders: list[date] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)  # 每頁文字（PDF 上傳時才有多頁）
    filename: str | None = None                     # 原始 PDF 檔名（檔案本身不保存）
    quiz: list[dict] | None = None                  # 出題結果快取：同一份講義不重複呼叫 LLM
    quiz_source: str | None = None                  # "llm" / "stub"

    def __post_init__(self) -> None:
        if not self.pages:
            self.pages = [self.text]


DEVOPS_SAMPLE = (
    "Hypothesis-Driven Development frames software delivery as scientific experiments. "
    "The key loop is Build, Measure, Learn. "
    "A Minimum Viable Feature is built just enough to test the hypothesis. "
    "Feature toggles allow controlled rollouts and act as a kill switch. "
    "A guardrail metric is a number that must not get worse during the experiment. "
    "A flag is not access control, so permissions must be checked on the server. "
    "Knight Capital lost 440 million dollars in 45 minutes after reusing an old flag. "
    "OpenFeature is a vendor-neutral API for feature flags."
)


class Store:
    def __init__(self) -> None:
        self.users: dict[str, User] = {
            "alice": User("alice", "Alice", "student", "alice@example.edu", {"devops"}),
            "bob": User("bob", "Bob", "student", "bob@example.edu", {"devops"}),
            "tina": User("tina", "Tina", "ta", "tina@example.edu", {"devops"}),
            "terry": User("terry", "Terry", "ta", "terry@example.edu", {"cloud"}),
            "admin": User("admin", "Admin", "admin", "admin@example.edu"),
        }
        self.courses = {"devops": "DevOps 軟體開發與維運", "cloud": "雲端運算"}
        self._ids = itertools.count(1)
        self.materials: dict[int, Material] = {}
        self.llm_usage: dict[tuple[str, date], int] = {}  # (user_id, 日期) → 今天呼叫 LLM 的次數
        self.add_material("HDD 與 Feature Toggles（官方講義）", DEVOPS_SAMPLE, "tina", "devops")
        self.add_material("Bob 的私人筆記", "Bob's private notes about Kubernetes pods and services.", "bob")

    def add_material(self, title, text, owner_id, course_id=None,
                     pages: list[str] | None = None, filename: str | None = None) -> Material:
        m = Material(next(self._ids), title, text, owner_id, course_id,
                     pages=list(pages or []), filename=filename)
        self.materials[m.id] = m
        return m

    def user_by_email(self, email: str) -> User | None:
        email = email.lower()
        return next((u for u in self.users.values() if u.email.lower() == email), None)
