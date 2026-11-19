from __future__ import annotations

import logging
import os
import secrets

from flask import Flask

from .auth import csrf_protect, csrf_token, load_user
from .flags import FlagStore
from .metrics import Metrics
from .store import Store


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    env = os.environ.get("APP_ENV", "development")
    app.config.update(
        APP_ENV=env,
        FLAGS_PATH=os.environ.get("FLAGS_PATH", os.path.join(os.path.dirname(__file__), "..", "flags.json")),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID"),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET"),
        ALLOWED_EMAIL_DOMAIN=os.environ.get("ALLOWED_EMAIL_DOMAIN", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(env == "production"),
    )
    app.config.update(config or {})
    app.config["DEMO_LOGIN"] = app.config["APP_ENV"] != "production"
    app.config["GOOGLE_ENABLED"] = bool(app.config["GOOGLE_CLIENT_ID"])

    # 密鑰只從環境變數來；正式環境沒設定就拒絕啟動
    if not app.config["SECRET_KEY"]:
        if app.config["APP_ENV"] == "production":
            raise RuntimeError("SECRET_KEY must be set in production")
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    logging.basicConfig(level=logging.INFO)
    app.extensions["store"] = Store()
    app.extensions["flags"] = FlagStore(app.config["FLAGS_PATH"])
    app.extensions["metrics"] = Metrics()
    app.before_request(load_user)
    app.before_request(csrf_protect)
    app.jinja_env.globals["csrf_token"] = csrf_token

    from .routes import bp
    app.register_blueprint(bp)

    if app.config["GOOGLE_ENABLED"]:
        from .google_auth import init_google
        init_google(app)
    return app
