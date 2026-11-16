"""โมเดลแปลภาษาของ Pakdee รันเองบน Modal ด้วย vLLM (ทางเลือกแทน Typhoon API)

เปิดเป็น API แบบ OpenAI ที่ <url>/v1 ใช้ได้ทันทีโดยตั้ง env ฝั่ง API:
    TYPHOON_BASE_URL=<url>/v1
    TYPHOON_API_KEY=<LLM_API_KEY ใน Secret pakdee-llm>
    TYPHOON_MODEL=qwen
deploy: modal deploy modal_llm.py   (Secret pakdee-llm ต้องมี LLM_API_KEY)
ไม่ได้ผูกกับ modal_app.py: ไม่ deploy ก็ไม่มีผลกับระบบเดิม
"""
import subprocess

import modal

MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"  # รุ่นเดียวกับฐานของ Typhoon v2.5 30B-A3B
SERVED_NAME = "qwen"
PORT = 8000
CACHE = "/llm-cache"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm==0.10.2", "transformers==4.56.2", "huggingface_hub[hf_transfer]")
    .env({"HF_HOME": CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_USE_V1": "1"})
)

app = modal.App("pakdee-llm", image=image)
cache = modal.Volume.from_name("pakdee-llm-cache", create_if_missing=True)
secret = modal.Secret.from_name("pakdee-llm")  # LLM_API_KEY


@app.function(
    gpu="L40S",
    volumes={CACHE: cache},
    secrets=[secret],
    scaledown_window=300,  # ค้างไว้ 5 นาทีหลังคำขอล่าสุด ลด cold start ระหว่างขั้นแปลหลายรอบ
    timeout=60 * 30,
    max_containers=1,
)
@modal.concurrent(max_inputs=16)
@modal.web_server(PORT, startup_timeout=60 * 15)
def serve():
    import os

    cmd = [
        "vllm", "serve", MODEL,
        "--served-model-name", SERVED_NAME,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--api-key", os.environ["LLM_API_KEY"],
        "--max-model-len", "32768",
        "--gpu-memory-utilization", "0.92",
        "--enable-prefix-caching",
    ]
    subprocess.Popen(cmd)
