# CourseBuddy · AI 課程複習助手

上傳講義 → AI 自動出練習題 → 依間隔重複提醒複習。
DevOps 課程 A10 / 期末專案。兩個實驗功能都包在 feature toggle 裡（Hypothesis-Driven Development）。

| Flag | 假設 | 成功指標 | 防護指標 |
|---|---|---|---|
| `ai_quiz` | H1：上傳講義後自動產生 5 題選擇題，會讓更多人真的開始複習 | 「開始複習」/「曝光」比例，ON 比 OFF 高 30% | 題目回報有誤率 < 10%、每次出題 API 成本不超過上限 |
| `spaced_reminder` | H2：第 1、3、7 天提醒複習，會提高 7 天內回訪率 | 7 天回訪率提高 25% | 關閉提醒比例 < 15% |

決策規則：達標 → rollout 到 100% 後移除 flag；沒差異 → 關掉並刪掉 flag 與程式碼。
樣本：以使用者 ID 雜湊 50/50 分流，12/1–12/14。樣本小，結果屬方向性證據。

---

## 快速開始

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python run.py                 # http://localhost:5000
python -m pytest -v           # 80 個測試
```

要用真的 AI 出題：把 `.env.example` 複製成 `.env`，填 `LLM_API_KEY` 和 `LLM_MODEL`（任何 OpenAI 相容 API，例如 OpenAI、Gemini）。
沒填就自動用規則式示範題目，其他功能都照常運作。

開發模式的登入頁可以直接選示範帳號：

| 帳號 | 角色 | 修 / 帶的課 | 用來示範 |
|---|---|---|---|
| Alice、Bob | student | DevOps | 一般學生；Bob 有一份私人筆記，Alice 看不到 |
| Tina | ta | DevOps | 可上傳官方講義、看 DevOps 課程統計 |
| Terry | ta | 雲端運算 | 看不到 DevOps 的講義和統計（ABAC） |
| Admin | admin | — | Flag 控制台、kill switch、監控 |

## 切換 ON / OFF（三種方法）

1. **管理員頁面**：用 Admin 登入 → 右上「Flag 控制台」→ 調 rollout 或按「關閉（全部 OFF）」。
2. **直接改 `flags.json`**：存檔後下一個請求就生效，**不用重啟**。
   - `"enabled": false` → kill switch，所有人 OFF
   - `"rollout": 0 / 50 / 100` → 0%、一半、全部的人 ON
   - `"include_users": ["alice"]` → 指定的人強制 ON（截圖、內測用）
3. 正式環境可改用 OpenFeature + Unleash / Flagsmith，`is_on()` 的呼叫點不用改。

開發模式下，講義頁頂端會顯示目前兩個 flag 的狀態與原因（kill_switch / rollout + bucket / included_user），方便截圖。

## 專案結構

```
app/
  flags.py        # flag 判斷：雜湊分桶、熱重載、壞檔保護、owner / expires
  auth.py         # 登入檢查、RBAC、ABAC、feature_required、CSRF
  routes.py       # 所有頁面與 API
  pdf_ingest.py   # PDF 上傳檢查與抽文字（magic bytes、大小、頁數、加密、掃描檔）
  features.py     # 出題：LLM（含 prompt injection 防護、輸出驗證）＋ 規則式備案、複習排程
  metrics.py      # 每個 flag × 每個狀態的事件計數
  google_auth.py  # Google OIDC 登入（設定 GOOGLE_CLIENT_ID 後啟用，尚未測試）
  store.py        # 記憶體資料庫（之後換成真的 DB）
flags.json        # feature flags 設定
tests/            # pytest：flag、存取控制、ON/OFF/切換、PDF 上傳、LLM 出題、Google 登入
.github/
  dependabot.yml  # 每週掃 pip 與 GitHub Actions
  workflows/ci.yml# push / PR 時跑測試，secrets 由 GitHub Secrets 注入
docs/screenshots/ # ON / OFF / 控制台 / 403 / PDF 上傳截圖
docs/security/    # pip-audit 升級前後的掃描結果
```

## 已完成 vs 待完成

| 項目 | 狀態 |
|---|---|
| 兩個功能的 toggle、kill switch、熱重載、rollout | ✅ 完成，有測試 |
| 伺服器端擋 OFF 的 API（回 404）、RBAC、ABAC、CSRF | ✅ 完成，有測試 |
| 各狀態監控（曝光、複習、回報、關閉提醒、被擋次數） | ✅ 記憶體版；之後接 DB / Prometheus |
| Google 登入（OIDC） | 🟡 程式碼完成、有測試（mock）；還要申請 OAuth client 實際登入一次 |
| 真的 LLM 出題 | 🟡 程式碼完成、有測試（mock）；還要填 API key 實際跑一次 |
| PDF 上傳（含安全檢查）、題目附出處頁碼 | ✅ 完成，有測試 |
| SCA：Dependabot + CI 的 pip-audit | ✅ 完成；Authlib 1.6.5 有 22 個已知漏洞，已升級到 1.9.10 |
| 資料庫、部署 | ⬜ |

## 推上 GitHub 之後要做的設定

1. **Dependabot**：Settings → Code security → 開 *Dependabot alerts* 和 *Dependabot security updates*（`dependabot.yml` 已放好）。
2. **Push protection**：Settings → Code security → *Secret scanning* → 開 *Push protection*。
3. **Secrets**：Settings → Environments → 建 `ci` → Secrets 加 `SECRET_KEY`、`LLM_API_KEY`（之後再加 `GOOGLE_CLIENT_SECRET`）；Variables 加 `LLM_MODEL`（不是機密）。
4. **Project 看板**：Projects → New project → Board，每個 Task 開一張 issue，填負責人和截止日。

## 各角色寫報告時可以用的東西

| 角色 | 去哪裡找證據 |
|---|---|
| PM | 上面的「已完成 vs 待完成」表、GitHub Project 看板截圖 |
| Developer A（認證授權） | `app/auth.py`、`app/google_auth.py`（用 `sub` 當 ID 防帳號接管）、`routes.py` 的 `_safe_next`（防 open redirect）、`tests/test_access.py`、`tests/test_google_auth.py`、截圖 `08_terry_403.png` |
| Developer B（SCA、密鑰、上傳安全） | Dependabot 頁面截圖、`docs/security/pip-audit-*.md`、`ci.yml` 的 `sca` job 與 secrets 注入、`.env.example`、`app/pdf_ingest.py`、`app/features.py`（prompt injection、輸出驗證、配額）、`tests/test_upload.py`、`tests/test_llm_quiz.py`、截圖 `11`、`13` |
| Designer | 截圖 `03`、`04`（ON）與 `06`（OFF）、兩個假設 |
| QA / Operator | `flags.json`、`app/flags.py`、`tests/`、截圖 `05`、`07`（控制台與監控） |

⚠️ 每個人要用自己的話寫、自己重新截圖，不能交一樣的報告。

## PDF 上傳與 AI 出題的安全設計（Developer B）

| 風險 | 做法 | 程式 / 測試 |
|---|---|---|
| 偽裝成 PDF 的惡意檔 | 副檔名 + 檔頭 magic bytes `%PDF-` 雙重檢查 | `pdf_ingest.py`、`test_reject_fake_pdf_by_magic_bytes` |
| 超大檔案 / 超多頁拖垮伺服器 | `MAX_CONTENT_LENGTH`（10 MB，超過回 413）、最多 60 頁、文字上限 20 萬字 | `test_reject_file_over_size_limit`、`test_reject_too_many_pages` |
| 損毀 / 加密 / 掃描檔 | 解析錯誤統一回友善訊息，不洩漏內部錯誤；加密與讀不到文字的都拒絕 | `test_reject_corrupted_pdf` 等 |
| 路徑穿越 | 檔名只用來顯示、去掉路徑；原始檔案不落地，只存抽出的文字 | `test_filename_path_is_stripped` |
| 看到別人的講義 | 上傳的講義預設私人，沿用 ABAC 檢查 | `test_uploaded_pdf_is_private_to_owner` |
| Prompt injection（講義裡藏指令） | system prompt 明講講義是資料；講義包在 `<document>` 裡並移除偽造標籤 | `test_document_cannot_close_its_own_tag` |
| LLM 亂回 / 幻覺格式 | 輸出當成不可信任的輸入：4 個不重複選項、答案必須在選項內、頁碼在範圍內、長度上限 | `test_validation_drops_bad_questions` |
| API 成本被刷爆 | 同一份講義只出題一次（快取）、每人每天上限 `QUIZ_DAILY_LIMIT`、送出文字上限、timeout | `test_quiz_is_cached_per_material`、`test_daily_quota` |
| LLM 掛掉 | 自動退回規則式題目，功能不中斷 | `test_fallback_to_stub` |
| API key 外洩 | 只從環境變數讀（本機 `.env`、CI 用 GitHub Secrets）；錯誤 log 不印 response 內容 | `.env.example`、`ci.yml` |

