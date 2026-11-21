"""伺服器端存取控制：登入、RBAC、ABAC、toggle OFF 時 API 也要被擋、CSRF。"""
import pytest

from app import create_app
from tests.conftest import write_flags

OFFICIAL = 1   # tina 上傳的 devops 官方講義
BOB_NOTE = 2   # bob 的私人筆記


# ---------- 認證 ----------
def test_pages_require_login(client):
    assert client.get("/").status_code == 302
    assert client.post(f"/api/materials/{OFFICIAL}/quiz").status_code in (400, 401)


def test_api_without_login_is_401(app):
    app.config["CSRF_DISABLED"] = True
    assert app.test_client().post(f"/api/materials/{OFFICIAL}/quiz").status_code == 401


def test_post_without_csrf_rejected(login):
    alice = login("alice")
    assert alice.c.post(f"/materials/{OFFICIAL}/reviewed").status_code == 400


def test_demo_login_disabled_in_production(flags_path):
    app = create_app({"FLAGS_PATH": str(flags_path), "APP_ENV": "production", "SECRET_KEY": "x"})
    app.config["CSRF_DISABLED"] = True
    assert app.test_client().post("/login", data={"uid": "admin"}).status_code == 404


def test_production_requires_secret_key(flags_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app({"FLAGS_PATH": str(flags_path), "APP_ENV": "production", "SECRET_KEY": None})


# ---------- ABAC：講義 ----------
def test_student_sees_official_material_of_enrolled_course(login):
    assert login("alice").get(f"/materials/{OFFICIAL}").status_code == 200


def test_student_cannot_see_other_students_note(login):
    alice = login("alice")
    assert alice.get(f"/materials/{BOB_NOTE}").status_code == 403
    assert alice.api(f"/api/materials/{BOB_NOTE}/quiz").status_code == 403


def test_ta_of_other_course_cannot_see_material(login):
    assert login("terry").get(f"/materials/{OFFICIAL}").status_code == 403


def test_student_cannot_publish_official_material(login):
    r = login("alice").post("/materials", data={"title": "x", "text": "y", "course_id": "devops"})
    assert r.status_code == 403


# ---------- RBAC / ABAC：統計與管理 ----------
@pytest.mark.parametrize("uid,code", [("alice", 403), ("tina", 200), ("terry", 403), ("admin", 200)])
def test_course_stats_matrix(app, uid, code):
    from tests.conftest import As
    assert As(app.test_client(), uid).get("/ta/courses/devops/stats").status_code == code


@pytest.mark.parametrize("uid,code", [("alice", 403), ("tina", 403), ("admin", 200)])
def test_admin_flags_only_admin(app, uid, code):
    from tests.conftest import As
    assert As(app.test_client(), uid).get("/admin/flags").status_code == code


# ---------- Toggle：ON / OFF / 切換 ----------
def test_quiz_on(login):
    r = login("alice").api(f"/api/materials/{OFFICIAL}/quiz")
    assert r.status_code == 200
    assert len(r.get_json()["questions"]) >= 3


def test_quiz_off_hidden_in_ui_and_blocked_on_server(flags_path, login):
    write_flags(flags_path, quiz=(False, 100))
    alice = login("alice")
    page = alice.get(f"/materials/{OFFICIAL}").get_data(as_text=True)
    assert "產生練習題" not in page and "標記已複習" in page          # UI 藏起來
    assert alice.api(f"/api/materials/{OFFICIAL}/quiz").status_code == 404   # 直接打 API 也擋
    assert alice.post(f"/materials/{OFFICIAL}/quiz").status_code == 404


def test_reminder_off_hidden_and_blocked(flags_path, login):
    write_flags(flags_path, remind=(True, 0))
    alice = login("alice")
    assert "複習提醒" not in alice.get(f"/materials/{OFFICIAL}").get_data(as_text=True)
    assert alice.api(f"/api/materials/{OFFICIAL}/reminders").status_code == 404


def test_reminder_on_returns_1_3_7_days(login):
    r = login("alice").api(f"/api/materials/{OFFICIAL}/reminders")
    assert r.status_code == 200 and len(r.get_json()["dates"]) == 3


def test_switch_on_to_off_at_runtime(flags_path, login):
    alice = login("alice")
    assert alice.api(f"/api/materials/{OFFICIAL}/quiz").status_code == 200
    write_flags(flags_path, quiz=(False, 100))       # kill switch，不重啟
    assert alice.api(f"/api/materials/{OFFICIAL}/quiz").status_code == 404
    write_flags(flags_path, quiz=(True, 100))        # 重新開啟
    assert alice.api(f"/api/materials/{OFFICIAL}/quiz").status_code == 200


def test_admin_kill_switch_via_console(app, flags_path):
    from tests.conftest import As
    admin = As(app.test_client(), "admin")
    assert admin.post("/admin/flags/ai_quiz", data={"enabled": "false"}).status_code == 302
    assert As(app.test_client(), "alice").api(f"/api/materials/{OFFICIAL}/quiz").status_code == 404


def test_admin_rollout_validation(app):
    from tests.conftest import As
    admin = As(app.test_client(), "admin")
    assert admin.post("/admin/flags/ai_quiz", data={"rollout": "150"}).status_code == 400
    assert admin.post("/admin/flags/nope", data={"rollout": "10"}).status_code == 404


def test_blocked_calls_are_counted(flags_path, app):
    from tests.conftest import As
    write_flags(flags_path, quiz=(False, 100))
    As(app.test_client(), "alice").api(f"/api/materials/{OFFICIAL}/quiz")
    assert app.extensions["metrics"].get("ai_quiz", "off", "blocked") == 1


# ---------- Open redirect ----------
@pytest.mark.parametrize("nxt", ["https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)"])
def test_login_next_cannot_redirect_offsite(client, nxt):
    client.get("/login")
    with client.session_transaction() as s:
        token = s["csrf"]
    r = client.post(f"/login?next={nxt}", data={"uid": "alice", "csrf": token})
    assert r.status_code == 302 and r.headers["Location"] == "/"


def test_login_next_keeps_internal_path(client):
    client.get("/login")
    with client.session_transaction() as s:
        token = s["csrf"]
    r = client.post("/login?next=/materials/1", data={"uid": "alice", "csrf": token})
    assert r.headers["Location"] == "/materials/1"
