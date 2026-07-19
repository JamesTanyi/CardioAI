FROM python:3.9-slim-bullseye

WORKDIR /app

# 安装 gunicorn
RUN pip install --no-cache-dir gunicorn

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

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