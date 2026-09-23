#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NodeSeek 每日签到（单文件版）

  python3 checkin.py                # 签到（默认试试手气）
  python3 checkin.py --status       # 只看登录态，不签到
  python3 checkin.py --refresh      # 只刷 Cloudflare clearance
  python3 checkin.py --login <验证码>  # 邮箱验证码重新登录

  NS_RANDOM=false ... checkin.py                      # 改成固定 5 鸡腿

签到被 Cloudflare 拦会自动过盾重试一次。退出码：0 成功/已签 · 2 登录态失效 · 3 其它失败。
过盾/登录要 playwright + 一个 X display（本机 D-Bus 环境用 xvfb-run；容器版见 Dockerfile）。
文件路径都能用环境变量覆盖：NSK_STATE / NSK_PROFILE / NSK_LOG / NSK_EMAIL_FILE。
"""
import glob
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

BASE = "https://www.nodeseek.com"
# 路径都可用环境变量覆盖（容器/自定义目录部署用），默认值兼容老部署
STATE = os.environ.get("NSK_STATE", "/root/.nsk_session.json")        # 会话 {ua, cookies{}}，权限 600
PROFILE = os.environ.get("NSK_PROFILE", "/root/.nsk-ch-profile")      # 持久化浏览器 profile
LOG = os.environ.get("NSK_LOG", "/root/nsk/checkin.log")              # 运行日志（JSONL，超 200 行自动截半）
EMAIL_FILE = os.environ.get("NSK_EMAIL_FILE", "/root/.nsk_email")     # 一行邮箱地址（600）；也可用环境变量 NSK_EMAIL


def email():
    """登录用的邮箱：环境变量 NSK_EMAIL 优先，其次 /root/.nsk_email（都不含在代码里）"""
    v = (os.environ.get("NSK_EMAIL") or "").strip()
    if not v and os.path.exists(EMAIL_FILE):
        with open(EMAIL_FILE) as f:
            v = f.read().strip()
    return v


# ---------------- 会话 ----------------
def load_session():
    with open(STATE) as f:
        st = json.load(f)
    cookies = st.get("cookies") or {}
    return st.get("ua", ""), "; ".join("%s=%s" % kv for kv in cookies.items())


def save_session(ua, cookies):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"ua": ua, "cookies": cookies}, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    try:
        os.replace(tmp, STATE)         # 原子替换，避免读到半截
    except OSError:
        # 容器里 STATE 是 bind-mount 的单文件，rename 会 EBUSY → 退化为原地覆盖
        with open(STATE, "w") as f:
            with open(tmp) as g:
                f.write(g.read())
        os.chmod(STATE, 0o600)
        os.remove(tmp)


# ---------------- 接口 ----------------
def api(path, method="GET", ua=None, cookie=None, timeout=30):
    """返回 (status, body)。x-csrf-challenge 少了会返回 high risk action（不是风控）"""
    if ua is None:
        ua, cookie = load_session()
    req = urllib.request.Request(
        BASE + path,
        data=b"" if method == "POST" else None,
        method=method,
        headers={"User-Agent": ua, "Cookie": cookie,
                 "Accept": "application/json, text/plain, */*",
                 "Accept-Language": "zh-CN,zh;q=0.9",
                 "Origin": BASE, "Referer": BASE + "/board",
                 "x-csrf-challenge": "simple-token",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, "EXC: %r" % (e,)


def classify(status, body):
    """接口返回 → (动作, 中文说明)"""
    low = body.lower()
    if "just a moment" in low or "<!doctype html" in low or "请稍候" in body:
        return "cf_blocked", "被 Cloudflare 拦下"
    try:
        j = json.loads(body)
    except Exception:
        return "failed", "返回无法解析（HTTP %s）" % status
    msg = j.get("message", "")
    if j.get("success"):
        gain = j.get("gain") or (j.get("record") or {}).get("gain")
        return "checked_in", "签到成功，获得鸡腿 %s 个" % (gain if gain is not None else "?")
    if "已完成签到" in msg or "已签到" in msg:
        return "already", msg
    if "USER NOT FOUND" in body or "未登录" in msg:
        return "session_expired", "登录态失效"
    return "failed", msg or ("HTTP %s" % status)


def today_top(ua, cookie):
    try:
        _, b = api("/api/attendance/board?page=1", ua=ua, cookie=cookie)
        lst = json.loads(b).get("list", [])
        if lst:
            return " ｜ 今日榜首 %s %s" % (lst[0].get("member_name"), lst[0].get("gain"))
    except Exception:
        pass
    return ""


def log(obj):
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        with open(LOG) as f:
            lines = f.readlines()
        if len(lines) > 200:
            with open(LOG, "w") as f:
                f.writelines(lines[-100:])
    except Exception:
        pass


# ---------------- 浏览器（只在过盾/登录时用）----------------
def _browser():
    """起持久化浏览器（headless=False，需要 X display）。

    本机 DISPLAY 常是别的 xvfb-run 留下的孤儿 Xvfb（没授权），所以把自己的
    进程 exec 进 `xvfb-run -a` 重跑一遍，由它挑空闲编号并配好 XAUTHORITY。
    """
    if os.environ.get("NSK_XVFB") != "1" and shutil.which("xvfb-run"):
        sys.stdout.flush()
        sys.stderr.flush()
        os.execve(shutil.which("xvfb-run"),
                  ["xvfb-run", "-a", "-s", "-screen 0 1440x900x24", sys.executable] + sys.argv,
                  dict(os.environ, NSK_XVFB="1"))

    from playwright.sync_api import sync_playwright
    hits = sorted(glob.glob("/root/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    kwargs = dict(headless=False,
                  args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                        "--disable-dev-shm-usage", "--window-size=1440,900", "--lang=zh-CN",
                        # 本机无 IPv6，Turnstile 域名只有 AAAA，手动映射到 IPv4
                        "--host-resolver-rules=MAP brunhild.challenges.cloudflare.com 104.18.16.146"],
                  locale="zh-CN", timezone_id="Asia/Shanghai",
                  viewport={"width": 1440, "height": 900})
    if hits:
        kwargs["executable_path"] = hits[-1]
    p = sync_playwright().start()
    return p, p.chromium.launch_persistent_context(PROFILE, **kwargs)


def _cookies(ctx):
    return {c["name"]: c["value"] for c in ctx.cookies() if "nodeseek" in c.get("domain", "")}


def cmd_refresh():
    """过 Cloudflare 挑战，刷新 cf_clearance 并写回会话"""
    p, ctx = _browser()
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/board", wait_until="domcontentloaded", timeout=60000)
        ok = False
        for i in range(36):                     # 最多等 180s
            page.wait_for_timeout(5000)
            t = page.title()
            if "请稍候" not in t and "moment" not in t.lower():
                ok = True
                break
            if i in (6, 14, 22):                # 卡太久就重载，给 CF 一个新访问
                try:
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    pass
        ua = page.evaluate("() => navigator.userAgent")
        cookies = _cookies(ctx)
    finally:
        ctx.close()
        p.stop()

    if not ok:
        print("refresh: 没能过 Cloudflare 挑战")
        return 1
    if "session" not in cookies:
        print("refresh: 过了挑战但会话已失效（要重新登录）")
        return 2
    save_session(ua, cookies)
    print("refresh: ok（cookies: %s）" % ",".join(cookies))
    return 0


def cmd_login(code):
    """邮箱验证码登录 —— 验证码必须用户本人在手机上点「发送验证码」拿到"""
    addr = email()
    if not addr:
        print("❌ 没配置邮箱：请 export NSK_EMAIL=你的邮箱，或把邮箱写进 %s" % EMAIL_FILE)
        return 1
    p, ctx = _browser()
    bodies = []
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", lambda r: bodies.append((r.status, r.text()[:200]))
                if "/api/account/emailSignIn" in r.url else None)
        page.goto(BASE + "/emailSignIn.html", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        page.fill("input[placeholder='Email']", addr)
        page.fill("input[placeholder='Validation Code']", code)
        page.wait_for_timeout(600)
        page.click("button:has-text('登录')")
        page.wait_for_timeout(9000)
        ua = page.evaluate("() => navigator.userAgent")
        cookies = _cookies(ctx)
    finally:
        ctx.close()
        p.stop()

    if "session" not in cookies:
        print("❌ 登录失败，接口返回: %s" % (bodies,))
        print("   常见原因：验证码过期/已用，或没先在手机上点「发送验证码」")
        return 2
    save_session(ua, cookies)
    print("✅ 登录成功（cookies: %s）" % ",".join(cookies))
    return 0


# ---------------- 主流程 ----------------
def cmd_status():
    ua, cookie = load_session()
    st, body = api("/api/attendance/board?page=1", ua=ua, cookie=cookie)
    try:
        n = len(json.loads(body).get("list", []))
    except Exception:
        n = 0
    if n:
        print("✅ 登录态正常" + today_top(ua, cookie))
        return 0
    print("⚠️ 登录态可能已失效（HTTP %s）: %s" % (st, body[:120]))
    return 2


def cmd_checkin():
    rnd = os.environ.get("NS_RANDOM", "true")     # true=试试手气 false=固定5鸡腿
    ua, cookie = load_session()
    status, body = api("/api/attendance?random=%s" % rnd, "POST", ua=ua, cookie=cookie)
    action, note = classify(status, body)

    if action == "cf_blocked":                    # 自愈：过盾后重试一次
        log({"ts": time.time(), "action": "cf_blocked", "healing": True})
        if cmd_refresh() == 0:
            ua, cookie = load_session()
            time.sleep(3)
            status, body = api("/api/attendance?random=%s" % rnd, "POST", ua=ua, cookie=cookie)
            action, note = classify(status, body)
        note += "（已过盾重试）"

    log({"ts": time.time(), "action": action, "note": note, "status": status, "raw": body[:300]})

    if action in ("checked_in", "already"):
        print("%s NodeSeek：%s%s" % ("✅" if action == "checked_in" else "☑️",
                                     note, today_top(ua, cookie)))
        return 0
    if action == "session_expired":
        print("⚠️ NodeSeek 签到失败：登录态已失效，需要重新登录（--login <验证码>）")
        return 2
    print("❌ NodeSeek 签到失败：%s" % note)
    return 3


def main(argv):
    if argv[:1] == ["--status"]:
        return cmd_status()
    if argv[:1] == ["--refresh"]:
        return cmd_refresh()
    if argv[:1] == ["--login"]:
        if len(argv) < 2:
            print("用法: checkin.py --login <邮件验证码>")
            return 1
        return cmd_login(argv[1].strip())
    try:
        return cmd_checkin()
    except FileNotFoundError:
        print("⚠️ NodeSeek 签到失败：会话文件读不到，需要重新登录（--login <验证码>）")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
