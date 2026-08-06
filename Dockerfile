FROM python:3.9-slim-bullseye

WORKDIR /app

# ★ 优化：换成腾讯云自己的 apt 镜像源——构建环境本来就在腾讯云内网，
#   走腾讯自己的镜像源是内网直连，比默认的 Debian 官方源(经常很慢/超时)快得多，
#   这一步不影响任何功能，只是换个下载地址
RUN sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g; s|security.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       fonts-wqy-zenhei \
       fonts-wqy-microhei \
       && rm -rf /var/lib/apt/lists/*

# ★ 优化：pip 同样换成腾讯云镜像源，理由同上——默认 PyPI 官方源在国内构建
#   环境访问经常很慢，是"RUN 这一步耗时长"最常见的原因，换镜像源通常
#   能把这几行的耗时从几分钟/几十分钟砍到几十秒
# ★ 顺带清理：原来这里有一行 `python -c "import matplotlib.pyplot" || true`，
#   放在 pip install matplotlib 之前，必然导入失败，被 || true 悄悄吞掉，
#   没有任何实际作用，直接删掉
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple/ gunicorn
COPY requirements.txt /app/
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple/ -r requirements.txt

COPY . /app/

EXPOSE 8080

ENV PYTHONUNBUFFERED=1
ENV FORCE_SQLITE=true
ENV DB_PATH=/workspace/data/bloodtrack.db

# 非 root 运行（安全最佳实践）
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# 声明暴露 8080 端口
EXPOSE 8080
ENV PORT=8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "8", "--timeout", "0", "app:app"]