"""Offline quality scorer for Pakdee dubbing outputs (not part of the app request path).

Three separate scores, never combined into one number:
  A. audio (objective)          -> tools/quality/audio.py
  B. translation rules          -> tools/quality/rules.py (reuses backend/app/pipeline/translate_quality.py)
  C. naturalness / meaning      -> NOT scored; exported as a rating sheet for humans or an LLM later

Run from the repo root:  python -m tools.quality.score <exports_dir> --out <dir>
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
