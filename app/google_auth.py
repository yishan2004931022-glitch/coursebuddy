"""Google 登入（OAuth 2.0 / OIDC）—— Developer A 接手的部分。

只有設定 GOOGLE_CLIENT_ID 時才會啟用。需要：pip install Authlib
步驟：
1. Google Cloud Console → APIs & Services → Credentials → 建立 OAuth client（Web application）
2. Authorized redirect URI 填 http://localhost:5000/auth/google/callback
3. 把 client id / secret 放進 .env（本機）或 GitHub Secrets（CI/部署），不要 commit
4. ALLOWED_EMAIL_DOMAIN 設成學校信箱網域，只允許校內帳號登入

測試：tests/test_google_auth.py 用假的 token 模擬 Google 回傳，不需要真的連到 Google。

安全重點：
- 使用者 ID 用 Google 的 `sub`（永久不變、全球唯一），不用 email 的 @ 前面那段：
  否則 alice@gmail.com 會被當成既有的 alice 帳號登入（帳號接管）。
- 只接受 email_verified = true；可用 ALLOWED_EMAIL_DOMAIN 限制只有學校信箱能登入。
- 登入後 session.clear() 換新 session（防 session fixation）。
"""
from __future__ import annotations

from flask import abort, current_app, redirect, session, url_for

from .auth import csrf_token
from .store import User


def init_google(app):
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    app.extensions["oauth"] = oauth

    @app.get("/auth/google")
    def google_login():
        return oauth.google.authorize_redirect(url_for("google_callback", _external=True))

    @app.get("/auth/google/callback")
    def google_callback():
        token = oauth.google.authorize_access_token()  # 會驗證 state 與 id_token 簽章
        info = token.get("userinfo") or {}
        sub, email = info.get("sub"), (info.get("email") or "").lower()
        domain = current_app.config["ALLOWED_EMAIL_DOMAIN"].lower()
        if not sub or not email or info.get("email_verified") is not True:
            abort(403)
        if domain and not email.endswith("@" + domain):
            abort(403)
        store = current_app.extensions["store"]
        uid = f"google:{sub}"
        # 先找綁過這個 Google 帳號的人；再找管理員預先建立、email 相同的帳號（例如助教）
        user = store.users.get(uid) or store.user_by_email(email)
        if user is None:  # 第一次登入的人預設為學生；助教 / 管理員由管理員指派
            user = User(uid, info.get("name") or email, "student", email)
            store.users[uid] = user
        session.clear()
        session["uid"] = user.id
        csrf_token()
        return redirect(url_for("main.dashboard"))
