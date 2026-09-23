# NodeSeek 自动签到

每天定时签到领鸡腿。单文件、纯标准库即可完成签到；Cloudflare 拦截和登录态失效都有兜底。

## 特点

- **单文件 `checkin.py`** —— 签到逻辑只用 python3 标准库，零第三方依赖
- **自动过盾**：被 Cloudflare 拦时，自动起浏览器过挑战、刷新 `cf_clearance` 后重试一次
- **登录态失效可救**：`--login <验证码>` 走邮箱验证码重新登录
- **`--status` 只查状态**，不签到，随时可跑
- **一键安装**：`install.sh` 按目标机器时区自动换算北京时间 08:00 写入 cron

## 快速开始

```bash
git clone https://github.com/<you>/nodeseek-checkin.git
cd nodeseek-checkin
bash install.sh --with-browser
```

安装脚本会：装 python3（必需）→ 可选装 playwright + chromium + xvfb →
把 `checkin.py` 装到 `/root/nsk/` → 提示放入登录态 → 写 cron → 跑一次自检。

**登录态从哪来**：本工具靠 NodeSeek 的会话 cookie（`/root/.nsk_session.json`）签到，
需要先做一次邮箱验证码登录（见下）。

```bash
# 1. 在手机上：NodeSeek 登录页 →「邮箱动态验证」→ 填邮箱 → 点「发送验证码」
#    （发码接口需过 Turnstile，脚本做不到，必须人工点一次）
# 2. 把邮件里的验证码填进来：
export NSK_EMAIL=你的邮箱
/opt/nsk-venv/bin/python /root/nsk/checkin.py --login <验证码>
```

## 用法

```bash
P=/opt/nsk-venv/bin/python          # 装了浏览器依赖用这个；纯签到用 python3 也行

$P /root/nsk/checkin.py              # 签到（默认手气 1~10 鸡腿）
$P /root/nsk/checkin.py --status     # 只看登录态，不签到
$P /root/nsk/checkin.py --refresh    # 手动过 Cloudflare 盾，刷新 clearance
$P /root/nsk/checkin.py --login <码>  # 邮箱验证码重新登录

NS_RANDOM=false $P /root/nsk/checkin.py   # 改成固定 5 鸡腿
```

退出码：`0` 成功/今日已签 · `1` 参数或配置缺失 · `2` 登录态失效 · `3` 其它失败

## 接口说明

| 用途 | 接口 |
|---|---|
| 签到 | `POST /api/attendance?random=true\|false` |
| 排行榜（用于验证登录态） | `GET /api/attendance/board?page=1` |
| 邮箱验证码登录 | `POST /api/account/emailSignIn {email, code}` |

## 踩过的坑（写在这里省得你再踩）

- 签到请求**必须带 `x-csrf-challenge: simple-token`**，否则返回 `high risk action`
  —— 这是缺请求头，不是风控
- 访客/匿名 curl 访问页面会被 Cloudflare 挑战；但**带完整 cookie（含 session）走 API 是通的**
- 浏览器流程用的是 `headless=False`，需要一个可用的 X display：
  本项目会把自己 exec 进 `xvfb-run -a` 重跑，避免踩到"孤儿 Xvfb 无授权"的坑
- 站点级挑战（Just a moment）浏览器通常能自行通过，约 1~2 分钟拿到 `cf_clearance`
- **密码登录走不通**：登录接口需要 Turnstile token，且 captcha 校验先于密码校验；
  邮箱验证码登录是唯一可行的自动化路径
- 若机器没有 IPv6，而 Turnstile 域名只有 AAAA 记录，需要给浏览器加
  `--host-resolver-rules=MAP brunhild.challenges.cloudflare.com <IPv4>`

## 已知限制

- 需要能直连 NodeSeek（国内机器请自备网络方案）
- 过盾/重新登录需要 playwright + chromium + xvfb（`install.sh --with-browser`）
- 登录态会过期，届时需要人工收一次邮箱验证码

## 免责声明

仅供个人账号的每日自动签到使用。请遵守 NodeSeek 的服务条款，不要用于批量注册、
多账号刷分等滥用场景。

## License

MIT
