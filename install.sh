#!/usr/bin/env bash
# NodeSeek 签到 —— 新机器一键安装
#
# 用法（在这台新机器上，root 跑）：
#   bash install.sh                 # 只装签到（python3 标准库，零额外依赖）
#   bash install.sh --with-browser  # 额外装 playwright+xvfb，支持过盾/重新登录
#
# 需要同目录下有 checkin.py；如果有 .nsk_session.json 也会一并装好（登录态）。
set -euo pipefail

DIR=/root/nsk
SESSION=/root/.nsk_session.json
VENV=/opt/nsk-venv
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_BROWSER=0
[ "${1:-}" = "--with-browser" ] && WITH_BROWSER=1

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\n❌ %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 跑"
[ -f "$HERE/checkin.py" ] || die "同目录下找不到 checkin.py"

# ---------- 1. python3 ----------
say "1/5 检查 python3"
if ! command -v python3 >/dev/null 2>&1; then
  echo "  没装 python3，尝试用 apt 装…"
  (apt-get update -qq && apt-get install -y -qq python3) || die "装 python3 失败，请手动装"
fi
python3 -c 'import sys; assert sys.version_info >= (3,8)' || die "python3 版本太低（要 3.8+）"
echo "  ✓ $(python3 -V)"

# ---------- 2. 脚本 ----------
say "2/5 安装脚本到 $DIR"
mkdir -p "$DIR"
install -m 755 "$HERE/checkin.py" "$DIR/checkin.py"
[ -f "$HERE/README.md" ] && install -m 644 "$HERE/README.md" "$DIR/README.md"
echo "  ✓ $DIR/checkin.py"

# ---------- 3. 登录态 ----------
say "3/5 安装登录态"
if [ -f "$HERE/.nsk_session.json" ]; then
  install -m 600 "$HERE/.nsk_session.json" "$SESSION"
  echo "  ✓ 已从安装包写入 $SESSION"
elif [ -f "$SESSION" ]; then
  echo "  ✓ 本机已有 $SESSION，跳过"
else
  echo "  ⚠️ 没找到登录态文件！"
  echo "     请从旧机器拷一份过来："
  echo "       scp root@旧机器:/root/.nsk_session.json /root/"
  echo "     （这是登录凭据，别走微信/邮件明文传）"
fi

# ---------- 4. 浏览器依赖（可选）----------
if [ "$WITH_BROWSER" = "1" ]; then
  say "4/5 装浏览器依赖（playwright + chromium + xvfb）"
  (apt-get update -qq && apt-get install -y -qq python3-venv xvfb ca-certificates) || die "装系统依赖失败"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q playwright
  # --with-deps 让 playwright 自己装 chromium 需要的系统库（比自己列 apt 包可靠）
  "$VENV/bin/playwright" install --with-deps chromium >/dev/null 2>&1 || \
    "$VENV/bin/playwright" install chromium || die "装 chromium 失败"
  echo "  ✓ $VENV（chromium 已就绪，浏览器流程会自动用 xvfb-run 起虚拟屏）"
  PY="$VENV/bin/python"
else
  say "4/5 跳过浏览器依赖（只装签到；要过盾/重新登录再加 --with-browser）"
  echo "  ⚠️ 注意：不带浏览器时，万一 Cloudflare 拦了签到，只能靠 --login 手动救"
  PY="$(command -v python3)"
fi

# ---------- 5. cron ----------
say "5/5 配置每日定时任务"
# 北京时间 08:00 = 该机本地时间多少点：本地偏移(秒)/3600
read -r CRON_H CRON_M < <(python3 - <<'PY'
import time
off = -time.timezone if not time.localtime().tm_isdst else -time.altzone  # 本地相对 UTC 的秒数（东为正）
sec = (8 * 3600 - (8 * 3600 - off)) % 86400   # 北京 08:00 对应的本地时刻（当天秒数）
print(sec // 3600, (sec % 3600) // 60)
PY
)
LINE="$CRON_M $CRON_H * * * $PY $DIR/checkin.py >> $DIR/cron.out 2>&1"
if command -v crontab >/dev/null 2>&1; then
  (crontab -l 2>/dev/null | grep -v 'nsk/checkin.py'; echo "$LINE") | crontab -
  echo "  ✓ 已写入 crontab: $LINE"
  echo "    （本机时区 $(date +%Z)，对应北京时间 08:00）"
else
  echo "  ⚠️ 没有 crontab 命令（装 cron 后自己加这行）："
  echo "    $LINE"
fi

# ---------- 自检 ----------
say "自检"
if [ -f "$SESSION" ]; then
  "$PY" "$DIR/checkin.py" --status || true
else
  echo "  跳过（还没有登录态文件）"
fi
say "完成"
echo "手动签到: $PY $DIR/checkin.py"
[ "$WITH_BROWSER" = "1" ] && echo "过盾:     $PY $DIR/checkin.py --refresh"
echo "重新登录: $PY $DIR/checkin.py --login <邮件验证码>"
