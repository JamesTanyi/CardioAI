FROM python:3.9-slim-bullseye

WORKDIR /app

# 强制 pip 使用官方源，彻底屏蔽清华镜像
RUN mkdir -p /root/.pip && echo "[global]\nindex-url = https://pypi.org/simple" > /root/.pip/pip.conf

RUN apt-get update && apt-get install -y \
    build-essential \
    gfortran \
    libatlas-base-dev \
    liblapack-dev \
    libblas-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

EXPOSE 80

# 设置环境变量，确保日志即时打印
ENV PYTHONUNBUFFERED=1
CMD exec gunicorn --bind :80 --workers 1 --threads 8 --timeout 0 app:app
