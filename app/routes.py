from __future__ import annotations

from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

from .auth import (can_view_course_stats, can_view_material, csrf_token, feature_required,
                   login_required, role_required)
from .features import generate_quiz, llm_configured, review_schedule

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


def _pop_quiz(mid: int):
    data = session.pop("quiz", None)
    return data["q"] if data and data.get("mid") == mid else None


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
    return redirect(request.args.get("next") or url_for("main.dashboard"))


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
    title = request.form.get("title", "").strip()
    text = request.form.get("text", "").strip()
    if not title or not text:
        flash("標題和內容都要填")
        return redirect(url_for("main.dashboard"))
    course_id = request.form.get("course_id") or None
    # 只有助教能把講義設成某門課的官方講義，而且只能是自己帶的課
    if course_id and not (g.user.role == "ta" and course_id in g.user.courses):
        abort(403)
    m = store().add_material(title, text, g.user.id, course_id)
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
                           quiz=_pop_quiz(mid), today=date.today())


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
    session["quiz"] = {"mid": mid, "q": generate_quiz(m.text, seed=mid)}
    metrics().record(FLAG_QUIZ, "on", "practice")
    return redirect(url_for("main.material", mid=mid) + "#quiz")


@bp.post("/api/materials/<int:mid>/quiz")
@feature_required(FLAG_QUIZ)
def quiz_api(mid):
    m = get_material_or_403(mid)
    metrics().record(FLAG_QUIZ, "on", "practice")
    return jsonify(material_id=mid, source="llm" if llm_configured() else "stub",
                   questions=generate_quiz(m.text, seed=mid))


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
