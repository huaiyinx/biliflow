FROM python:3.12-slim

# 系统依赖: ffmpeg 用于音频提取, curl 用于健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# yt-dlp (单独安装，更新频繁)
RUN pip3 install --no-cache-dir yt-dlp

# 工作目录
WORKDIR /app

# 应用代码
COPY app/ .

# 启动
EXPOSE 8866
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8866"]
