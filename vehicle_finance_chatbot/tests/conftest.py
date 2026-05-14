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

# Pre-test valid TCKN fixtures (checksum verified).
VALID_TCKN_GUARANTOR = "23456789138"
VALID_TCKN_SELLER = "34567891238"
VALID_TCKN_OTHER = "45678912316"


import pytest

from app.persistence.database import init_db


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db():
    init_db()


@pytest.fixture(scope="session", autouse=True)
def _stub_llm_extractor():
    """Wire the deterministic stub extractor for all tests so the LLM
    code path is never hit in CI. Production code remains untouched —
    it always builds a real ``LLMExtractor``."""
    from app.chatbot import nodes as _nodes  # noqa: F401  (ensures package import)
    from app.chatbot.chains.dev_extractor import StubExtractor
    from app.chatbot.nodes import intent_node as _intent_module

    _intent_module.reset_default_extractor()
    _intent_module._extractor = StubExtractor()
    yield
    _intent_module.reset_default_extractor()
