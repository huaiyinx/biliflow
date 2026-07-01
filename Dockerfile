FROM python:3.12-slim

# 系统依赖: ffmpeg 用于音视频处理, tesseract 用于关键帧 OCR, curl 用于健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# bili-cli 热修补: 某些 DASH 视频的 detect_best_streams 会在 audio 下载前崩溃
COPY patch_bili_cli.py .
RUN python patch_bili_cli.py

# 工作目录
WORKDIR /app

# 应用代码
COPY app/ .

# 启动
EXPOSE 8866
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8866"]
