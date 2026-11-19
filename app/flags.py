"""Feature flags：flags.json + 雜湊分桶 + 熱重載 + kill switch。

和老師範例的差別：
1. 熱重載：每次判斷前檢查 flags.json 是否被修改，改檔後「不用重啟」就生效（真正的 kill switch）。
2. 壞檔保護：flags.json 寫壞（JSON 格式錯誤）時，沿用上一份正確設定，不讓整個服務掛掉。
3. include_users：指定使用者強制 ON（permission flag，方便 Demo 與截圖）。
4. owner / expires：每個 flag 都要有負責人與到期日，避免 flag debt（老師投影片 Knight Capital 案例）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import date

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    on: bool
    reason: str          # unknown_flag / kill_switch / included_user / rollout
    bucket: int | None = None

    @property
    def variant(self) -> str:
        return "on" if self.on else "off"


def bucket_of(flag: str, user_id: str) -> int:
    """同一個使用者對同一個 flag 永遠落在同一個桶（0–99）。"""
    h = hashlib.sha256(f"{flag}:{user_id}".encode()).hexdigest()
    return int(h, 16) % 100


class FlagStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._flags: dict = {}
        self._reload_if_changed()

    # ---------- 讀取 ----------
    def _reload_if_changed(self) -> None:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            log.warning("flags file %s not found; all flags OFF", self.path)
            self._flags, self._stamp = {}, None
            return
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp == self._stamp:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.error("flags file invalid (%s); keeping last good config", e)
            return
        self._flags, self._stamp = data, stamp
        log.info("flags reloaded: %s", {k: v.get("enabled") for k, v in data.items()})

    def all(self) -> dict:
        with self._lock:
            self._reload_if_changed()
            return json.loads(json.dumps(self._flags))  # deep copy

    def evaluate(self, flag: str, user_id: str) -> Decision:
        with self._lock:
            self._reload_if_changed()
            f = self._flags.get(flag)
        if f is None:
            return Decision(False, "unknown_flag")
        if not f.get("enabled", False):
            return Decision(False, "kill_switch")
        if user_id in f.get("include_users", []):
            return Decision(True, "included_user")
        b = bucket_of(flag, user_id)
        return Decision(b < int(f.get("rollout", 100)), "rollout", b)

    def is_on(self, flag: str, user_id: str) -> bool:
        return self.evaluate(flag, user_id).on

    @staticmethod
    def is_expired(meta: dict, today: date | None = None) -> bool:
        exp = meta.get("expires")
        return bool(exp) and date.fromisoformat(exp) < (today or date.today())

    # ---------- 寫入（管理員頁面 / kill switch） ----------
    def update(self, flag: str, **changes) -> dict:
        with self._lock:
            self._reload_if_changed()
            if flag not in self._flags:
                raise KeyError(flag)
            data = json.loads(json.dumps(self._flags))
            data[flag].update(changes)
            # 原子寫入：先寫暫存檔再 rename，避免寫到一半被讀到
            d = os.path.dirname(os.path.abspath(self.path))
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, self.path)
            self._stamp = None
            self._reload_if_changed()
            return data[flag]
