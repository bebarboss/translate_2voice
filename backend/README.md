# Pakdee — Backend

FastAPI + pipeline พากย์ (`app/`), Modal GPU (`modal_app.py`), เทสต์และสคริปต์

```bash
# จากรากโปรเจกต์ (มี .venv + .env)
.venv\Scripts\activate          # หรือ source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python run.py                   # http://localhost:8000/docs
pytest -q
```

บน VPS: image build จากโฟลเดอร์นี้ — ดู `../deploy/` และ `../docs/deploy-vps.md`
