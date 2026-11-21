#!/usr/bin/env bash
# Developer A：伺服器端權限檢查實測（用 curl 繞過前端，直接打後端）
# 用法：先在另一個終端機執行 python run.py，再執行 bash devA_probe.sh
# Windows 請用 Git Bash 執行。每一段的輸出都可以截圖放進報告。
B=http://localhost:5000
cd "$(mktemp -d)"

token() {  # 從頁面的 hidden 欄位取出 CSRF token
  curl -s -b "$1" -c "$1" "$B$2" | grep -o 'name="csrf" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//'
}
login() {  # 用示範帳號登入，cookie 存在 $1
  local t; t=$(token "$1" /login)
  curl -s -o /dev/null -b "$1" -c "$1" -d "csrf=$t&uid=$2" "$B/login"
}
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

login alice.jar alice
TA=$(token alice.jar /)

echo "== 1. 未登入打 API（預期 401）"
T=$(token anon.jar /login)
echo "   $(code -b anon.jar -H "X-CSRF-Token: $T" -X POST $B/api/materials/1/quiz)"

echo "== 2. 沒帶 CSRF token（預期 400，CSRF 檢查比登入檢查先執行）"
echo "   $(code -X POST $B/api/materials/1/quiz)"

echo "== 3. IDOR：alice 看 bob 的私人筆記 /materials/2（預期 403）"
echo "   $(code -b alice.jar $B/materials/2)"

echo "== 4. IDOR：alice 用 API 對 bob 的筆記出題（預期 403；若 flag 對 alice 為 OFF 會先回 404）"
echo "   $(code -b alice.jar -H "X-CSRF-Token: $TA" -X POST $B/api/materials/2/quiz)"

echo "== 5. ABAC：學生 alice 看課程統計（預期 403）"
echo "   $(code -b alice.jar $B/ta/courses/devops/stats)"
login terry.jar terry
echo "   助教 terry 看別門課 devops 的統計（預期 403）"
echo "   $(code -b terry.jar $B/ta/courses/devops/stats)"
login tina.jar tina
echo "   助教 tina 看自己的課 devops 的統計（預期 200）"
echo "   $(code -b tina.jar $B/ta/courses/devops/stats)"

echo "== 6. 非 admin 改 flag（預期 403）"
echo "   $(code -b alice.jar -d "csrf=$TA&enabled=false" $B/admin/flags/ai_quiz)"

echo "== 7. Open redirect：登入後 next 指向外部網站（預期導回站內 /）"
T=$(token x.jar /login)
curl -s -o /dev/null -w "   %{http_code} -> %{redirect_url}\n" -b x.jar -c x.jar \
  -d "csrf=$T&uid=alice" "$B/login?next=https://evil.example"

echo "== 8. flag OFF 時直接打 API（預期 404）"
echo "   先把 flags.json 的 ai_quiz.enabled 改成 false 並存檔（不用重啟），按 Enter 繼續"
read -r
echo "   $(code -b alice.jar -H "X-CSRF-Token: $TA" -X POST $B/api/materials/1/quiz)"
echo "   改回 true、rollout 改成 100 後按 Enter，預期 200"
read -r
echo "   $(code -b alice.jar -H "X-CSRF-Token: $TA" -X POST $B/api/materials/1/quiz)"
