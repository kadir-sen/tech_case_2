from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path so `import app...` works under pytest.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Use a temp sqlite DB for tests to avoid touching dev data.
TMP_DB = Path(tempfile.gettempdir()) / "vfc_test.db"
if TMP_DB.exists():
    TMP_DB.unlink()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP_DB}")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("VECTORSTORE", "faiss")
os.environ.setdefault("AUDIT_LOG_PATH", str(Path(tempfile.gettempdir()) / "vfc_audit.log"))

# Pre-test valid TCKN fixtures (checksum verified). These do NOT collide
# with the mock customer TCKNs stored in app.auth.mock_customer_store.
VALID_TCKN_GUARANTOR = "23456789138"
VALID_TCKN_SELLER = "34567891238"
VALID_TCKN_OTHER = "45678912316"

# Real TCKN of CUST001 — used by self-guarantor regression test.
CUST001_REAL_TCKN = "60064805492"


import pytest

from app.persistence.database import init_db


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db():
    init_db()
