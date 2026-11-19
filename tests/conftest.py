import json
import re

import pytest

from app import create_app


def write_flags(path, quiz=(True, 100), remind=(True, 100), **extra):
    data = {
        "ai_quiz": {"enabled": quiz[0], "rollout": quiz[1], "include_users": [],
                    "owner": "QA", "expires": "2099-12-31", **extra.get("ai_quiz", {})},
        "spaced_reminder": {"enabled": remind[0], "rollout": remind[1], "include_users": [],
                            "owner": "QA", "expires": "2099-12-31", **extra.get("spaced_reminder", {})},
    }
    path.write_text(json.dumps(data))


@pytest.fixture
def flags_path(tmp_path):
    p = tmp_path / "flags.json"
    write_flags(p)
    return p


@pytest.fixture
def app(flags_path):
    return create_app({"FLAGS_PATH": str(flags_path), "TESTING": True, "SECRET_KEY": "test"})


@pytest.fixture
def client(app):
    return app.test_client()


class As:
    """以某個示範帳號登入，並自動帶 CSRF token。"""

    def __init__(self, client, uid):
        self.c = client
        self.c.get("/login")
        self.token = self._token()
        r = self.post("/login", data={"uid": uid})
        assert r.status_code == 302
        self.token = self._token()  # 登入後 session 重建，token 也換新

    def _token(self):
        with self.c.session_transaction() as s:
            return s["csrf"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf", self.token)
        return self.c.post(url, data=data, **kw)

    def api(self, url):
        return self.c.post(url, headers={"X-CSRF-Token": self.token})


@pytest.fixture
def login(client):
    return lambda uid: As(client, uid)
