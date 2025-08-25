FROM crpi-v2fmzydhnzmlpzjc.cn-shanghai.personal.cr.aliyuncs.com/machenkai/python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# 安装 7z 解包工具（tar + xz-utils）和证书
RUN apt-get update && apt-get install -y --no-install-recommends \
    xz-utils tar ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷贝 requirements.txt（利用缓存）
COPY requirements.txt ./

# 安装 Python 依赖（走阿里云镜像源）
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    && rm -rf /root/.cache/pip

# 拷贝项目代码到 /app
COPY . /app

EXPOSE 12082

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12082", "--log-level", "warning", "--no-access-log"]
