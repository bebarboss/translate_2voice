# Dubbing API บน Docker
# ค่าเริ่มต้น (ML=0): ส่งขั้นที่ใช้การ์ดจอไป Modal (WORKER=modal) image เล็ก ไม่มี PyTorch ไม่ต้องตั้งค่า GPU ใน Docker
#                     คีย์ Modal รับผ่าน MODAL_TOKEN_ID / MODAL_TOKEN_SECRET ใน .env
# ML=1: รันโมเดลบนการ์ดจอเครื่องนี้ (Docker Desktop + WSL2) ใช้กับ docker-compose.gpu.yml
FROM python:3.11-slim

ARG ML=0

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface

# ffmpeg (มี libass สำหรับฝังซับ) + ฟอนต์ Noto Sans Thai / Noto Sans (+ ตัวคอมไพล์สำหรับแพ็กเกจ ML ที่ไม่มี wheel)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-core fontconfig libsndfile1 \
    && if [ "$ML" = "1" ]; then apt-get install -y --no-install-recommends git build-essential; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt constraints-docker.txt ./
# ML=1: PyTorch รุ่นเดียวกับที่ทดสอบบนเครื่องแล้ว (CUDA 12.6 รองรับ GTX 16xx ขึ้นไป)
#       แล้วติดตั้งทุกแพ็กเกจเท่ากับ .venv ที่ใช้งานได้จริง (pip freeze ของ requirements-ml.txt) แบบ --no-deps
#       เพราะ f5-tts-th ประกาศ numpy<=1.26.4 แต่ใช้กับ numpy 2.x ได้ pip ปกติจะแก้ dependency ไม่ผ่าน
#       torchcodec จาก PyPI สร้างกับ CUDA 13 (หา libnvrtc.so.13 ไม่เจอ) ต้องใช้รุ่น cu126 ให้ตรงกับ PyTorch
RUN if [ "$ML" = "1" ]; then \
        pip install torch==2.14.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu126 \
        && pip install --no-deps -r constraints-docker.txt \
        && pip install --no-deps --force-reinstall torchcodec==0.17.0 --index-url https://download.pytorch.org/whl/cu126; \
    else \
        pip install -r requirements.txt modal; \
    fi

# faster-whisper (CTranslate2) หา cuDNN/cuBLAS จากแพ็กเกจ nvidia-* ที่มากับ PyTorch (ML=1)
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib

COPY app ./app
COPY run.py ./

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"
CMD ["python", "run.py"]
