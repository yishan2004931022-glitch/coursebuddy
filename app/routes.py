from __future__ import annotations

import os
from datetime import date
from urllib.parse import urlsplit

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

from .auth import (can_view_course_stats, can_view_material, csrf_token, feature_required,
                   login_required, role_required)
from .features import llm_configured, make_quiz, review_schedule
from .pdf_ingest import PDFError, extract_pages

bp = Blueprint("main", __name__)

FLAG_QUIZ = "ai_quiz"
FLAG_REMIND = "spaced_reminder"


def store():
    return current_app.extensions["store"]


def flags():
    return current_app.extensions["flags"]


def metrics():
    return current_app.extensions["metrics"]


def get_material_or_403(mid: int):
    m = store().materials.get(mid)
    if m is None:
        abort(404)
    if not can_view_material(g.user, m):
        abort(403)
    return m


def _pop_quiz(m):
    # session（cookie）只記「剛剛產生了哪份講義的題目」，題目本身存在伺服器端，避免 cookie 超過 4 KB
    return m.quiz if session.pop("quiz_mid", None) == m.id else None


def _safe_next(target: str | None) -> str:
    """只允許站內相對路徑，防止 open redirect（/login?next=https://evil.com）。"""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("main.dashboard")
    parts = urlsplit(target)
    return target if not parts.scheme and not parts.netloc else url_for("main.dashboard")


class QuotaExceeded(Exception):
    pass


def get_or_make_quiz(m):
    """同一份講義只出一次題（快取），LLM 呼叫計入每人每天的配額。"""
    if m.quiz is not None:
        return m.quiz, m.quiz_source
    cfg = current_app.config
    if llm_configured(cfg):
        key = (g.user.id, date.today())
        used = store().llm_usage.get(key, 0)
        if used >= cfg["QUIZ_DAILY_LIMIT"]:
            raise QuotaExceeded()
        store().llm_usage[key] = used + 1
    m.quiz, m.quiz_source = make_quiz(m.pages, cfg, seed=m.id)
    return m.quiz, m.quiz_source


def too_large(e):
    """上傳超過 MAX_CONTENT_LENGTH。"""
    limit = current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    if request.path.startswith("/api/"):
        return jsonify(error=f"file too large (max {limit} MB)"), 413
    flash(f"檔案太大，上限是 {limit} MB")
    return redirect(url_for("main.dashboard"))


# ---------------- 登入 ----------------
@bp.get("/login")
def login():
    return render_template("login.html", users=store().users.values(),
                           demo=current_app.config["DEMO_LOGIN"],
                           google=current_app.config["GOOGLE_ENABLED"])


@bp.post("/login")
def login_post():
    # 示範登入：只在開發環境開放，正式環境一律走 Google OIDC
    if not current_app.config["DEMO_LOGIN"]:
        abort(404)
    uid = request.form.get("uid", "")
    if uid not in store().users:
        abort(400)
    session.clear()          # 防 session fixation：登入時換新 session
    session["uid"] = uid
    csrf_token()             # 新 session 產生新的 CSRF token
    return redirect(_safe_next(request.args.get("next")))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ---------------- 一般頁面 ----------------
@bp.get("/")
@login_required
def dashboard():
    visible = [m for m in store().materials.values() if can_view_material(g.user, m)]
    return render_template("dashboard.html", materials=visible, courses=store().courses)


@bp.post("/materials")
@login_required
def create_material():
    course_id = request.form.get("course_id") or None
    # 只有助教能把講義設成某門課的官方講義，而且只能是自己帶的課（先檢查權限再處理檔案）
    if course_id and not (g.user.role == "ta" and course_id in g.user.courses):
        abort(403)

    title = request.form.get("title", "").strip()[:120]
    upload = request.files.get("pdf")
    pages, filename = None, None
    if upload and upload.filename:
        # 檔名只拿來顯示，不拿來存檔，所以不會有 path traversal；仍去掉路徑、限制長度
        filename = os.path.basename(upload.filename.replace("\\", "/"))[:120]
        try:
            pages = extract_pages(filename, upload.read())
        except PDFError as e:
            flash(str(e))
            return redirect(url_for("main.dashboard"))
        text = "\n".join(pages)
        title = title or os.path.splitext(filename)[0]
    else:
        text = request.form.get("text", "").strip()
        if not text:
            flash("請上傳 PDF，或貼上講義文字")
            return redirect(url_for("main.dashboard"))
    if not title:
        flash("請填寫標題")
        return redirect(url_for("main.dashboard"))

    m = store().add_material(title, text, g.user.id, course_id, pages=pages, filename=filename)
    current_app.logger.info("material %s created by %s (%s, %d pages)",
                            m.id, g.user.id, "pdf" if filename else "text", len(m.pages))
    return redirect(url_for("main.material", mid=m.id))


@bp.get("/materials/<int:mid>")
@login_required
def material(mid):
    m = get_material_or_403(mid)
    dq = flags().evaluate(FLAG_QUIZ, g.user.id)
    dr = flags().evaluate(FLAG_REMIND, g.user.id)
    metrics().record(FLAG_QUIZ, dq.variant, "exposure")
    metrics().record(FLAG_REMIND, dr.variant, "exposure")
    return render_template("material.html", m=m, dq=dq, dr=dr,
                           quiz=_pop_quiz(m), today=date.today())


@bp.post("/materials/<int:mid>/reviewed")
@login_required
def mark_reviewed(mid):
    """OFF 組的對照行為：自己看講義、手動標記已複習。"""
    get_material_or_403(mid)
    metrics().record(FLAG_QUIZ, flags().evaluate(FLAG_QUIZ, g.user.id).variant, "practice")
    flash("已標記複習完成")
    return redirect(url_for("main.material", mid=mid))


# ---------------- 功能 1：AI 自動出題（ai_quiz） ----------------
@bp.post("/materials/<int:mid>/quiz")
@feature_required(FLAG_QUIZ)
def quiz_page(mid):
    m = get_material_or_403(mid)
    try:
        get_or_make_quiz(m)
    except QuotaExceeded:
        flash("今天的 AI 出題次數已用完，明天再來吧")
        return redirect(url_for("main.material", mid=mid))
    session["quiz_mid"] = mid
    metrics().record(FLAG_QUIZ, "on", "practice")
    return redirect(url_for("main.material", mid=mid) + "#quiz")


@bp.post("/api/materials/<int:mid>/quiz")
@feature_required(FLAG_QUIZ)
def quiz_api(mid):
    m = get_material_or_403(mid)
    try:
        questions, source = get_or_make_quiz(m)
    except QuotaExceeded:
        return jsonify(error="daily quiz limit reached"), 429
    metrics().record(FLAG_QUIZ, "on", "practice")
    return jsonify(material_id=mid, source=source, questions=questions)


@bp.post("/materials/<int:mid>/quiz/report")
@feature_required(FLAG_QUIZ)
def quiz_report(mid):
    get_material_or_403(mid)
    metrics().record(FLAG_QUIZ, "on", "quiz_reported")
    flash("已回報這題有誤，謝謝！")
    return redirect(url_for("main.material", mid=mid))


# ---------------- 功能 2：間隔重複提醒（spaced_reminder） ----------------
@bp.post("/materials/<int:mid>/reminders")
@feature_required(FLAG_REMIND)
def set_reminders(mid):
    m = get_material_or_403(mid)
    m.reminders = review_schedule(date.today())
    metrics().record(FLAG_REMIND, "on", "reminder_set")
    return redirect(url_for("main.material", mid=mid))


@bp.post("/materials/<int:mid>/reminders/off")
@feature_required(FLAG_REMIND)
def cancel_reminders(mid):
    m = get_material_or_403(mid)
    m.reminders = []
    metrics().record(FLAG_REMIND, "on", "reminder_optout")
    return redirect(url_for("main.material", mid=mid))


@bp.post("/api/materials/<int:mid>/reminders")
@feature_required(FLAG_REMIND)
def reminders_api(mid):
    m = get_material_or_403(mid)
    m.reminders = review_schedule(date.today())
    metrics().record(FLAG_REMIND, "on", "reminder_set")
    return jsonify(material_id=mid, dates=[d.isoformat() for d in m.reminders])


# ---------------- 助教：課程統計（ABAC） ----------------
@bp.get("/ta/courses/<course_id>/stats")
@role_required("ta", "admin")
def course_stats(course_id):
    if course_id not in store().courses:
        abort(404)
    if not can_view_course_stats(g.user, course_id):
        abort(403)
    mats = [m for m in store().materials.values() if m.course_id == course_id]
    return render_template("stats.html", course=store().courses[course_id], mats=mats)


# ---------------- 管理員：flag 控制台 + 監控 ----------------
@bp.get("/admin/flags")
@role_required("admin")
def admin_flags():
    all_flags = flags().all()
    return render_template("admin_flags.html", flags=all_flags,
                           expired={k: flags().is_expired(v) for k, v in all_flags.items()},
                           rows=metrics().table(list(all_flags)))


@bp.post("/admin/flags/<name>")
@role_required("admin")
def admin_update_flag(name):
    changes = {}
    if "enabled" in request.form:
        changes["enabled"] = request.form["enabled"] == "true"
    if "rollout" in request.form:
        r = int(request.form["rollout"])
        if not 0 <= r <= 100:
            abort(400)
        changes["rollout"] = r
    try:
        flags().update(name, **changes)
    except KeyError:
        abort(404)
    current_app.logger.warning("flag %s changed by %s: %s", name, g.user.id, changes)
    return redirect(url_for("main.admin_flags"))


@bp.get("/healthz")
def healthz():
    return {"status": "ok"}
