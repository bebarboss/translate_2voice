#!/usr/bin/env python3
"""เติม ciphertext ของเลขผู้เสียภาษีและเลขบัญชี ดู python -m app.pii_backfill"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pii_backfill import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
