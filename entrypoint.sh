#!/bin/bash
# 容器入口:自己起一个 Xvfb 虚拟显示(headless=False 的浏览器需要),
# 然后交给 checkin.py。不用 xvfb-run —— 本镜像里它等不到 Xvfb 就绪信号会卡死。
set -u

if [ "${NSK_NO_X:-0}" != "1" ]; then
  mkdir -p /tmp/.X11-unix
  Xvfb :99 -screen 0 1440x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
  XVFB_PID=$!
  trap 'kill "$XVFB_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 60); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.1
  done
  export DISPLAY=:99
  export NSK_XVFB=1        # 告诉 checkin.py 别再去 exec xvfb-run
fi

# 容器每次 hostname 都不同,Chromium 会把这些残留锁当成"另一台机器正在用这个 profile"
# → 清掉锁文件,让持久化 profile(存放 session/cf_clearance)能被正常复用
if [ -n "${NSK_PROFILE:-}" ] && [ -d "${NSK_PROFILE}" ]; then
  rm -f "${NSK_PROFILE}"/SingletonLock "${NSK_PROFILE}"/SingletonCookie "${NSK_PROFILE}"/SingletonSocket 2>/dev/null || true
fi

exec python3 /app/checkin.py "$@"
