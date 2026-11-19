"""Feature flag 本身的單元測試：kill switch、rollout、分桶穩定、熱重載、壞檔保護。"""
from datetime import date

from app.flags import FlagStore, bucket_of
from tests.conftest import write_flags


def test_unknown_flag_is_off(flags_path):
    assert FlagStore(str(flags_path)).evaluate("nope", "alice").reason == "unknown_flag"


def test_kill_switch_beats_rollout_and_include(flags_path):
    write_flags(flags_path, quiz=(False, 100), ai_quiz={"include_users": ["alice"]})
    d = FlagStore(str(flags_path)).evaluate("ai_quiz", "alice")
    assert (d.on, d.reason) == (False, "kill_switch")


def test_rollout_0_and_100(flags_path):
    write_flags(flags_path, quiz=(True, 0), remind=(True, 100))
    fs = FlagStore(str(flags_path))
    users = [f"user-{i}" for i in range(200)]
    assert not any(fs.is_on("ai_quiz", u) for u in users)
    assert all(fs.is_on("spaced_reminder", u) for u in users)


def test_rollout_50_is_roughly_half_and_sticky(flags_path):
    write_flags(flags_path, quiz=(True, 50))
    fs = FlagStore(str(flags_path))
    users = [f"user-{i}" for i in range(1000)]
    first = [fs.is_on("ai_quiz", u) for u in users]
    assert 400 < sum(first) < 600
    assert first == [fs.is_on("ai_quiz", u) for u in users]  # 同一人永遠同一組


def test_buckets_independent_per_flag():
    # 同一個人在兩個實驗被分到的組別不該完全一樣，否則兩個實驗會互相干擾
    users = [f"user-{i}" for i in range(200)]
    a = [bucket_of("ai_quiz", u) < 50 for u in users]
    b = [bucket_of("spaced_reminder", u) < 50 for u in users]
    assert a != b


def test_include_users_forced_on(flags_path):
    write_flags(flags_path, quiz=(True, 0), ai_quiz={"include_users": ["alice"]})
    fs = FlagStore(str(flags_path))
    assert fs.evaluate("ai_quiz", "alice").reason == "included_user"
    assert not fs.is_on("ai_quiz", "bob")


def test_hot_reload_without_restart(flags_path):
    fs = FlagStore(str(flags_path))
    assert fs.is_on("ai_quiz", "alice")
    write_flags(flags_path, quiz=(False, 100))  # 有人改了檔案（kill switch）
    assert not fs.is_on("ai_quiz", "alice")


def test_broken_file_keeps_last_good_config(flags_path):
    fs = FlagStore(str(flags_path))
    flags_path.write_text("{ this is not json")
    assert fs.is_on("ai_quiz", "alice")


def test_update_writes_file(flags_path):
    fs = FlagStore(str(flags_path))
    fs.update("ai_quiz", enabled=False)
    assert '"enabled": false' in flags_path.read_text()
    assert not FlagStore(str(flags_path)).is_on("ai_quiz", "alice")


def test_expiry():
    assert FlagStore.is_expired({"expires": "2026-12-31"}, today=date(2027, 1, 1))
    assert not FlagStore.is_expired({"expires": "2026-12-31"}, today=date(2026, 12, 31))
