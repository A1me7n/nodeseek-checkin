# NodeSeek 自动签到 —— 容器版
# 签到逻辑纯标准库；Cloudflare 过盾/邮箱登录需要 Playwright Chromium(+Xvfb 虚拟显示)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai

# Xvfb(给 headless=False 的浏览器当虚拟显示) + 中文字体(挑战页渲染更真实) + 时区
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb xauth tzdata ca-certificates fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

# Playwright + Chromium(--with-deps 会补系统库)
RUN pip install --no-cache-dir playwright \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache/pip

COPY checkin.py /app/checkin.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
WORKDIR /app

# 状态文件靠挂载传入:会话 / 邮箱 / 日志 / 浏览器 profile
# 路径用环境变量指定(见 README):NSK_STATE / NSK_PROFILE / NSK_LOG / NSK_EMAIL_FILE
ENTRYPOINT ["/app/entrypoint.sh"]
