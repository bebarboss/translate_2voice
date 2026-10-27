# Dubbing API บน Docker (ใช้การ์ดจอ NVIDIA ผ่าน Docker Desktop + WSL2)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface

# ffmpeg (มี libass สำหรับฝังซับ) + ฟอนต์ Noto Sans Thai / Noto Sans + ตัวคอมไพล์สำหรับแพ็กเกจที่ไม่มี wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-core fontconfig git build-essential libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch รุ่นเดียวกับที่ทดสอบบนเครื่องแล้ว (CUDA 12.6 รองรับ GTX 16xx ขึ้นไป) แล้วล็อกไว้ไม่ให้แพ็กเกจอื่นเปลี่ยน
RUN pip install torch==2.14.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu126 \
    && printf 'torch==2.14.1\ntorchaudio==2.11.0\n' > /tmp/constraints.txt

COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements-ml.txt -c /tmp/constraints.txt

# faster-whisper (CTranslate2) หา cuDNN/cuBLAS จากแพ็กเกจ nvidia-* ที่มากับ PyTorch
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib

COPY app ./app
COPY run.py ./

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"
CMD ["python", "run.py"]
