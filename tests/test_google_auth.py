"""Google 登入（OIDC）：用假的 token 模擬 Google 的回傳，不需要真的連到 Google。"""
import pytest

from app import create_app


@pytest.fixture
def gapp(flags_path):
    app = create_app({"FLAGS_PATH": str(flags_path), "TESTING": True, "SECRET_KEY": "test",
                      "GOOGLE_CLIENT_ID": "fake-id.apps.googleusercontent.com",
                      "GOOGLE_CLIENT_SECRET": "fake-secret", "GOOGLE_ENABLED": True,
                      "LLM_API_KEY": None})
    return app


def fake_google(app, monkeypatch, **userinfo):
    info = {"sub": "1234567890", "email": "newbie@gmail.com", "email_verified": True, "name": "Newbie"}
    info.update(userinfo)
    monkeypatch.setattr(app.extensions["oauth"].google, "authorize_access_token",
                        lambda: {"userinfo": info})


def uid_after_login(client):
    with client.session_transaction() as s:
        return s.get("uid")


def test_google_enabled_shows_login_route(gapp, monkeypatch):
    # 不要真的連到 Google 拿 OIDC 設定
    monkeypatch.setattr(gapp.extensions["oauth"].google, "load_server_metadata", lambda: {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"})
    r = gapp.test_client().get("/auth/google")
    assert r.status_code == 302 and "accounts.google.com" in r.headers["Location"]


def test_first_login_creates_student_with_sub_as_id(gapp, monkeypatch):
    fake_google(gapp, monkeypatch)
    c = gapp.test_client()
    assert c.get("/auth/google/callback").status_code == 302
    uid = uid_after_login(c)
    assert uid == "google:1234567890"
    assert gapp.extensions["store"].users[uid].role == "student"


def test_same_local_part_does_not_take_over_existing_account(gapp, monkeypatch):
    # 以前用 email @ 前面那段當 ID，alice@gmail.com 會直接登入成既有的 alice（帳號接管）
    fake_google(gapp, monkeypatch, sub="999", email="alice@gmail.com")
    c = gapp.test_client()
    c.get("/auth/google/callback")
    assert uid_after_login(c) == "google:999"
    assert gapp.extensions["store"].users["alice"].email == "alice@example.edu"


def test_preprovisioned_email_maps_to_existing_account(gapp, monkeypatch):
    fake_google(gapp, monkeypatch, sub="555", email="Tina@Example.edu")
    c = gapp.test_client()
    c.get("/auth/google/callback")
    assert uid_after_login(c) == "tina"               # 管理員預先建立的助教帳號


def test_unverified_email_rejected(gapp, monkeypatch):
    fake_google(gapp, monkeypatch, email_verified=False)
    assert gapp.test_client().get("/auth/google/callback").status_code == 403


def test_email_verified_must_be_true_not_truthy(gapp, monkeypatch):
    fake_google(gapp, monkeypatch, email_verified="false")
    assert gapp.test_client().get("/auth/google/callback").status_code == 403


def test_missing_sub_rejected(gapp, monkeypatch):
    fake_google(gapp, monkeypatch, sub=None)
    assert gapp.test_client().get("/auth/google/callback").status_code == 403


def test_domain_restriction(gapp, monkeypatch):
    gapp.config["ALLOWED_EMAIL_DOMAIN"] = "mail.ntust.edu.tw"
    fake_google(gapp, monkeypatch, email="someone@gmail.com")
    assert gapp.test_client().get("/auth/google/callback").status_code == 403
    fake_google(gapp, monkeypatch, email="b11233030@mail.ntust.edu.tw")
    assert gapp.test_client().get("/auth/google/callback").status_code == 302


def test_domain_suffix_trick_rejected(gapp, monkeypatch):
    gapp.config["ALLOWED_EMAIL_DOMAIN"] = "ntust.edu.tw"
    fake_google(gapp, monkeypatch, email="evil@fakentust.edu.tw")
    assert gapp.test_client().get("/auth/google/callback").status_code == 403
