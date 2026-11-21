"""PDF 上傳：正常上傳、各種惡意 / 不合格檔案被擋、權限、出題附頁碼。"""
import io

from pypdf import PdfReader, PdfWriter

from tests.pdfgen import make_pdf

LECTURE = [
    "Gradient descent updates parameters to minimize the training loss.\n"
    "The learning rate controls the step size of each update.",
    "Backpropagation computes gradients layer by layer.\n"
    "Overfitting happens when a model memorizes training examples.",
    "Regularization techniques such as dropout reduce overfitting.\n"
    "Transformers use attention to weigh relationships between tokens.",
]


def latest(app):
    store = app.extensions["store"]
    return store.materials[max(store.materials)]


def count(app):
    return len(app.extensions["store"].materials)


# ---------- 正常流程 ----------
def test_upload_pdf_creates_material_with_pages(app, login):
    alice = login("alice")
    r = alice.upload("ML_week3.pdf", make_pdf(LECTURE))
    assert r.status_code == 302
    m = latest(app)
    assert m.owner_id == "alice" and m.course_id is None
    assert m.title == "ML_week3"                      # 標題留空 → 用檔名
    assert m.filename == "ML_week3.pdf" and len(m.pages) == 3
    assert "Backpropagation" in m.pages[1]
    page = alice.get(r.headers["Location"]).get_data(as_text=True)
    assert "第 3 頁" in page and "Transformers" in page


def test_quiz_from_pdf_has_page_numbers(app, login):
    alice = login("alice")
    alice.upload("ml.pdf", make_pdf(LECTURE), title="ML")
    r = alice.api(f"/api/materials/{latest(app).id}/quiz")
    qs = r.get_json()["questions"]
    assert r.status_code == 200 and len(qs) >= 3
    assert all(1 <= q["page"] <= 3 for q in qs)


def test_uploaded_pdf_is_private_to_owner(app, login):
    login("alice").upload("mine.pdf", make_pdf(LECTURE))
    mid = latest(app).id
    from tests.conftest import As
    bob = As(app.test_client(), "bob")
    assert bob.get(f"/materials/{mid}").status_code == 403
    assert bob.api(f"/api/materials/{mid}/quiz").status_code == 403


def test_ta_can_upload_official_pdf_for_own_course(app, login):
    login("tina").upload("official.pdf", make_pdf(LECTURE), course_id="devops")
    assert latest(app).course_id == "devops"


def test_student_cannot_upload_official_pdf(app, login):
    before = count(app)
    r = login("alice").upload("x.pdf", make_pdf(LECTURE), course_id="devops")
    assert r.status_code == 403 and count(app) == before


def test_text_paste_still_works(app, login):
    r = login("alice").post("/materials", data={"title": "notes", "text": "Some lecture text."})
    assert r.status_code == 302 and latest(app).pages == ["Some lecture text."]


# ---------- 被擋的檔案 ----------
def _rejected(app, login, filename, data, message):
    before = count(app)
    alice = login("alice")
    r = alice.upload(filename, data)
    assert r.status_code == 302 and count(app) == before
    assert message in alice.get("/").get_data(as_text=True)


def test_reject_wrong_extension(app, login):
    _rejected(app, login, "slides.exe", make_pdf(LECTURE), "只接受 .pdf")


def test_reject_fake_pdf_by_magic_bytes(app, login):
    # 副檔名是 .pdf，但內容其實是 HTML / 執行檔
    _rejected(app, login, "evil.pdf", b"<html><script>alert(1)</script></html>", "不是有效的 PDF")
    _rejected(app, login, "evil.pdf", b"MZ\x90\x00" + b"\x00" * 100, "不是有效的 PDF")


def test_reject_corrupted_pdf(app, login):
    _rejected(app, login, "broken.pdf", b"%PDF-1.4\n" + b"\x00garbage" * 50, "無法讀取")


def test_reject_scanned_pdf_without_text(app, login):
    _rejected(app, login, "scan.pdf", make_pdf(["", ""]), "讀不到 PDF 裡的文字")


def test_reject_too_many_pages(app, login):
    _rejected(app, login, "huge.pdf", make_pdf(["Page text here."] * 61), "太多頁")


def test_reject_encrypted_pdf(app, login):
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(LECTURE))))
    w.encrypt("secret", algorithm="RC4-128")
    buf = io.BytesIO()
    w.write(buf)
    _rejected(app, login, "locked.pdf", buf.getvalue(), "密碼保護")


def test_reject_file_over_size_limit(app, login):
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024
    before = count(app)
    alice = login("alice")
    r = alice.upload("big.pdf", b"%PDF-1.4\n" + b"0" * (100 * 1024))
    assert r.status_code == 302 and count(app) == before
    assert "檔案太大" in alice.get("/").get_data(as_text=True)


def test_filename_path_is_stripped(app, login):
    login("alice").upload("../../etc/passwd.pdf", make_pdf(LECTURE))
    assert latest(app).filename == "passwd.pdf"


def test_upload_requires_login_and_csrf(app, login):
    c = app.test_client()
    r = c.post("/materials", data={"pdf": (io.BytesIO(make_pdf(LECTURE)), "a.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 400                       # 沒有 CSRF token


def test_stub_options_unique_ignoring_case():
    from app.features import generate_quiz
    qs = generate_quiz(["Gradient Descent overview.", "Gradient descent minimizes loss. Learning rate matters."])
    for q in qs:
        assert len({o.lower() for o in q["options"]}) == 4 and q["answer"] in q["options"]
        assert not q["question"].startswith("•")
