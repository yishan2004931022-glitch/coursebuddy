"""PDF 上傳：檢查 + 抽文字（Developer B：上傳安全）。

上傳的檔案是「不可信任的輸入」，所以：
1. 大小上限：Flask MAX_CONTENT_LENGTH（預設 10 MB），超過直接回 413，不會整個讀進記憶體。
2. 副檔名 + magic bytes 雙重檢查：只看副檔名或瀏覽器給的 Content-Type 都可以被偽造，
   所以還要確認檔案開頭真的是 `%PDF-`。
3. 頁數上限：避免超大 PDF 拖垮伺服器（也限制之後送進 LLM 的量）。
4. 拒絕加密 PDF：打不開也不嘗試破解。
5. 抽不到文字（多半是掃描檔）就拒絕，並提示使用者。
6. 原始檔案不落地：只保留抽出來的文字，不存使用者上傳的二進位檔，減少攻擊面。
"""
from __future__ import annotations

import io
import logging
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)

MAX_PAGES = 60
MAX_CHARS = 200_000          # 抽出的文字總長度上限
MIN_CHARS = 40               # 少於這個字數視為掃描檔 / 空白 PDF
PDF_MAGIC = b"%PDF-"


class PDFError(ValueError):
    """給使用者看的錯誤訊息（不含內部細節）。"""


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract_pages(filename: str, data: bytes,
                  max_pages: int = MAX_PAGES, max_chars: int = MAX_CHARS) -> list[str]:
    """回傳每一頁的文字（index 0 = 第 1 頁）。不合格就丟 PDFError。"""
    if not filename or not filename.lower().endswith(".pdf"):
        raise PDFError("只接受 .pdf 檔案")
    # PDF 規格允許 %PDF- 前面有少量垃圾位元組，所以看前 1024 bytes
    if PDF_MAGIC not in data[:1024]:
        raise PDFError("這個檔案不是有效的 PDF")

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise PDFError("PDF 有密碼保護，請先解除加密再上傳")
        n = len(reader.pages)
        if n == 0:
            raise PDFError("PDF 沒有任何頁面")
        if n > max_pages:
            raise PDFError(f"PDF 太多頁（{n} 頁），上限是 {max_pages} 頁")

        pages, total = [], 0
        for page in reader.pages:
            t = _clean(page.extract_text() or "")
            total += len(t)
            if total > max_chars:
                raise PDFError("PDF 文字量太大，請拆成幾份再上傳")
            pages.append(t)
    except PDFError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, RecursionError) as e:
        # 損毀或惡意構造的 PDF：記 log，但不把內部錯誤丟給使用者
        log.warning("PDF parse failed for %r: %s", filename, e)
        raise PDFError("PDF 無法讀取，檔案可能已損毀") from None

    if sum(len(p) for p in pages) < MIN_CHARS:
        raise PDFError("讀不到 PDF 裡的文字（可能是掃描檔或圖片），請上傳可選取文字的 PDF")
    return pages
