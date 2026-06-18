FROM python:3.9-slim-bullseye

WORKDIR /app

# 用 pip 默认源（CloudBase 在国内，用官方源反而慢；依赖都是纯 wheel，不需要编译）
COPY requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 80

ENV PYTHONUNBUFFERED=1
ENV FORCE_SQLITE=true
# ★ 使用持久化数据目录，避免容器重启丢失数据
ENV DB_PATH=/workspace/data/bloodtrack.db

CMD exec gunicorn --bind :80 --workers 1 --threads 8 --timeout 0 app:app
