"""โมเดลแปลภาษา Qwen3.6 35B-A3B (FP8) รันเองบน Modal ด้วย vLLM แยกจาก pakdee-llm เดิม

เปิดเป็น API แบบ OpenAI ที่ <url>/v1 ใช้ได้โดยตั้ง env ฝั่ง API (ไม่ต้องแก้โค้ด):
    LLM_BASE_URL=<url>/v1
    LLM_API_KEY=<LLM_API_KEY ใน Secret pakdee-llm-35b-key>
    LLM_MODEL=qwen
deploy: modal deploy modal_llm_35b.py   (Secret pakdee-llm-35b-key ต้องมี LLM_API_KEY)
หยุดใช้จ่าย: modal app stop pakdee-llm-35b

หมายเหตุ
- Qwen3.6 เปิดโหมด thinking เป็นค่าเริ่มต้น แต่ translate.py ไม่ได้ส่ง chat_template_kwargs
  จึงปิด thinking ฝั่งเซิร์ฟเวอร์ด้วย --default-chat-template-kwargs (ผู้เรียกยัง override ได้)
- --language-model-only ไม่โหลด vision encoder (ใช้แปลข้อความอย่างเดียว) ประหยัด VRAM
- น้ำหนัก FP8 ~36 GB, สถาปัตยกรรม hybrid (linear attention 3:1) KV cache เล็ก จึงพอดี L40S 48GB
"""
import subprocess

import modal

MODEL = "Qwen/Qwen3.6-35B-A3B-FP8"  # Apache-2.0, official FP8 checkpoint
SERVED_NAME = "qwen"
PORT = 8000
CACHE = "/llm-cache"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm==0.19.1", "huggingface_hub[hf_transfer]")
    .env({"HF_HOME": CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App("pakdee-llm-35b", image=image)
cache = modal.Volume.from_name("pakdee-llm-35b-cache", create_if_missing=True)
secret = modal.Secret.from_name("pakdee-llm-35b-key")  # LLM_API_KEY


@app.function(
    gpu="L40S",
    volumes={CACHE: cache},
    secrets=[secret],
    scaledown_window=300,  # เหมือน pakdee-llm: ค้าง 5 นาทีหลังคำขอล่าสุดแล้ว scale to zero
    timeout=60 * 30,
    max_containers=1,
)
@modal.concurrent(max_inputs=16)
@modal.web_server(PORT, startup_timeout=60 * 20)
def serve():
    import json
    import os

    cmd = [
        "vllm", "serve", MODEL,
        "--served-model-name", SERVED_NAME,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--api-key", os.environ["LLM_API_KEY"],
        "--max-model-len", "32768",
        "--gpu-memory-utilization", "0.92",
        "--enable-prefix-caching",
        "--language-model-only",
        "--reasoning-parser", "qwen3",
        "--default-chat-template-kwargs", json.dumps({"enable_thinking": False}),
    ]
    subprocess.Popen(cmd)
