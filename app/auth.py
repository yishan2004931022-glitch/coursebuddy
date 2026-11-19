"""認證與授權。所有檢查都在伺服器端執行：前端藏按鈕不算存取控制。

- login_required：沒登入 → 導向登入頁（API 回 401）
- role_required：RBAC，依角色擋
- can_view_material：ABAC，依「這份講義屬於誰 / 哪門課」與「使用者修哪些課」判斷
- feature_required：toggle 為 OFF 的使用者直接打 API 也會被擋（回 404，不洩漏功能存在）
"""
from __future__ import annotations

import secrets
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

from .store import Material, User


def load_user() -> None:
    uid = session.get("uid")
    g.user = current_app.extensions["store"].users.get(uid) if uid else None


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_protect() -> None:
    """所有 POST 都要帶 CSRF token：表單用 hidden 欄位，API 用 X-CSRF-Token header。"""
    if request.method != "POST" or current_app.config.get("CSRF_DISABLED"):
        return
    sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
    if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
        abort(400, "CSRF token missing or invalid")


def _deny_unauthenticated():
    if request.path.startswith("/api/"):
        abort(401)
    return redirect(url_for("main.login", next=request.path))


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.user is None:
            return _deny_unauthenticated()
        return view(*a, **kw)
    return wrapper


def role_required(*roles: str):
    def deco(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if g.user is None:
                return _deny_unauthenticated()
            if g.user.role not in roles:
                abort(403)
            return view(*a, **kw)
        return wrapper
    return deco


def feature_required(flag: str):
    def deco(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if g.user is None:
                return _deny_unauthenticated()
            if not current_app.extensions["flags"].is_on(flag, g.user.id):
                current_app.extensions["metrics"].record(flag, "off", "blocked")
                abort(404)
            return view(*a, **kw)
        return wrapper
    return deco


def can_view_material(user: User, m: Material) -> bool:
    if user.role == "admin" or m.owner_id == user.id:
        return True
    # 課程官方講義：修這門課的學生、帶這門課的助教都能看
    return m.course_id is not None and m.course_id in user.courses


def can_view_course_stats(user: User, course_id: str) -> bool:
    # 助教只能看自己帶的課（ABAC），管理員全部
    return user.role == "admin" or (user.role == "ta" and course_id in user.courses)
