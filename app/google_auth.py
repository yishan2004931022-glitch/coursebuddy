"""Google 登入（OAuth 2.0 / OIDC）—— Developer A 接手的部分。

只有設定 GOOGLE_CLIENT_ID 時才會啟用。需要：pip install Authlib
步驟：
1. Google Cloud Console → APIs & Services → Credentials → 建立 OAuth client（Web application）
2. Authorized redirect URI 填 http://localhost:5000/auth/google/callback
3. 把 client id / secret 放進 .env（本機）或 GitHub Secrets（CI/部署），不要 commit
4. ALLOWED_EMAIL_DOMAIN 設成學校信箱網域，只允許校內帳號登入

注意：此檔案未在骨架的自動測試中執行，接手後請自行加測試。
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

    @app.get("/auth/google")
    def google_login():
        return oauth.google.authorize_redirect(url_for("google_callback", _external=True))

    @app.get("/auth/google/callback")
    def google_callback():
        token = oauth.google.authorize_access_token()  # 會驗證 state 與 id_token 簽章
        info = token.get("userinfo") or {}
        email = info.get("email", "")
        domain = current_app.config["ALLOWED_EMAIL_DOMAIN"]
        if not info.get("email_verified") or (domain and not email.endswith("@" + domain)):
            abort(403)
        store = current_app.extensions["store"]
        user = store.user_by_email(email)
        if user is None:  # 第一次登入的人預設為學生；助教 / 管理員由管理員指派
            uid = email.split("@")[0]
            user = store.users.setdefault(uid, User(uid, info.get("name", uid), "student", email))
        session.clear()
        session["uid"] = user.id
        csrf_token()
        return redirect(url_for("main.dashboard"))
