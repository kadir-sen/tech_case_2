from __future__ import annotations

import re
from pathlib import Path

from app.rag.vectorstore import Document


_HEADING_RE = re.compile(r"^##\s+(.+)$")


def chunk_markdown(path: Path) -> list[Document]:
    """Split a markdown FAQ doc into ``Document`` chunks by ``##`` headings.

    Each chunk's metadata carries the heading so we can cite the source in
    the final answer.
    """
    text = path.read_text(encoding="utf-8")
    docs: list[Document] = []

    current_heading: str | None = None
    current_lines: list[str] = []
    chunk_idx = 0

    def flush() -> None:
        nonlocal chunk_idx, current_lines
        if not current_lines:
            return
        body = "\n".join(current_lines).strip()
        if not body:
            current_lines = []
            return
        full_text = (current_heading or "") + "\n" + body
        docs.append(
            Document(
                id=f"{path.stem}-{chunk_idx:03d}",
                text=full_text.strip(),
                metadata={
                    "source": str(path.name),
                    "heading": current_heading or "",
                },
            )
        )
        chunk_idx += 1
        current_lines = []

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            current_heading = m.group(1).strip()
            continue
        if line.startswith("# "):
            # Document-level title, skip.
            continue
        current_lines.append(line)
    flush()
    return docs


def default_faq_path() -> Path:
    return Path(__file__).parent / "documents" / "vehicle_finance_faq.md"
