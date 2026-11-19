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
python -m pytest -v           # 34 個測試
```

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
  features.py     # 出題（目前是規則式假題目）、複習排程
  metrics.py      # 每個 flag × 每個狀態的事件計數
  google_auth.py  # Google OIDC 登入（設定 GOOGLE_CLIENT_ID 後啟用，尚未測試）
  store.py        # 記憶體資料庫（之後換成真的 DB）
flags.json        # feature flags 設定
tests/            # pytest：flag 邏輯 + 伺服器端存取控制 + ON/OFF/切換
.github/
  dependabot.yml  # 每週掃 pip 與 GitHub Actions
  workflows/ci.yml# push / PR 時跑測試，secrets 由 GitHub Secrets 注入
docs/screenshots/ # ON / OFF / 控制台 / 403 截圖
```

## 已完成 vs 待完成

| 項目 | 狀態 |
|---|---|
| 兩個功能的 toggle、kill switch、熱重載、rollout | ✅ 完成，有測試 |
| 伺服器端擋 OFF 的 API（回 404）、RBAC、ABAC、CSRF | ✅ 完成，有測試 |
| 各狀態監控（曝光、複習、回報、關閉提醒、被擋次數） | ✅ 記憶體版；之後接 DB / Prometheus |
| Google 登入（OIDC） | 🟡 程式碼已寫，需 Developer A 申請 OAuth client 並測試 |
| 真的 LLM 出題 | 🟡 目前是假題目；設定 `LLM_API_KEY` 後由 Developer 串接 |
| PDF 上傳 | ⬜ 目前貼文字 |
| 資料庫、部署 | ⬜ |

## 推上 GitHub 之後要做的設定

1. **Dependabot**：Settings → Code security → 開 *Dependabot alerts* 和 *Dependabot security updates*（`dependabot.yml` 已放好）。
2. **Push protection**：Settings → Code security → *Secret scanning* → 開 *Push protection*。
3. **Secrets**：Settings → Environments → 建 `ci` → 加 `SECRET_KEY`、`LLM_API_KEY`（之後再加 `GOOGLE_CLIENT_SECRET`）。
4. **Project 看板**：Projects → New project → Board，每個 Task 開一張 issue，填負責人和截止日。

## 各角色寫報告時可以用的東西

| 角色 | 去哪裡找證據 |
|---|---|
| PM | 上面的「已完成 vs 待完成」表、GitHub Project 看板截圖 |
| Developer A（認證授權） | `app/auth.py`、`app/google_auth.py`、`tests/test_access.py`、截圖 `08_terry_403.png` |
| Developer B（SCA、密鑰） | Dependabot 頁面截圖、`.github/dependabot.yml`、`ci.yml` 的 secrets 注入、`.env.example`、`.gitignore` |
| Designer | 截圖 `03`、`04`（ON）與 `06`（OFF）、兩個假設 |
| QA / Operator | `flags.json`、`app/flags.py`、`tests/`、截圖 `05`、`07`（控制台與監控） |

⚠️ 每個人要用自己的話寫、自己重新截圖，不能交一樣的報告。
