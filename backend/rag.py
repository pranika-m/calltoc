"""Knowledge base ingestion and ChromaDB semantic search (RAG)."""

import logging
from pathlib import Path
from typing import Any

from backend.config import ROOT_DIR

logger = logging.getLogger(__name__)

KB_DIR = ROOT_DIR / "knowledge_base"
CHROMA_DIR = ROOT_DIR / "chroma_db"
COLLECTION_NAME = "company_knowledge_base"


def _get_chroma_client():
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _get_collection():
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _chunk_text(text: str, chunk_words: int = 320, overlap_words: int = 40) -> list[str]:
    """Split markdown text into overlapping word chunks (~300-450 tokens)."""
    words = text.split()
    if not words:
        return []
    if len(words) <= chunk_words:
        return [" ".join(words)]

    chunks: list[str] = []
    step = max(1, chunk_words - overlap_words)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_words])
        if chunk:
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def _split_sections(text: str) -> list[str]:
    """Split a markdown document into '## ' sections, keeping the document title.

    Section-level chunks retrieve far more precisely than one chunk per file,
    and long sections still fall back to overlapping word chunks.
    """
    lines = text.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("# ")), "")
    sections: list[str] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("## ") and current:
            sections.append("\n".join(current).strip())
            current = [line]
        elif not current and line.startswith("# "):
            continue
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())

    chunks: list[str] = []
    for section in sections:
        if not section:
            continue
        body = f"{title}\n{section}" if title else section
        chunks.extend(_chunk_text(body))
    return chunks


def ingest_knowledge_base(kb_dir: Path = KB_DIR) -> int:
    """Load all markdown files from knowledge_base/, chunk them, and store in ChromaDB."""
    if not kb_dir.exists():
        logger.warning("Knowledge base directory not found: %s", kb_dir)
        return 0

    client = _get_chroma_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []

    for md_file in sorted(kb_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8").strip()
        for idx, chunk in enumerate(_split_sections(content)):
            ids.append(f"{md_file.name}::{idx}")
            documents.append(chunk)
            metadatas.append({"source": md_file.name})

    if documents:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("Indexed %d knowledge base chunks from %s", len(documents), kb_dir)
    return len(documents)


def search_knowledge_base(
    query: str,
    top_k: int = 3,
    min_similarity: float = 0.35,
) -> dict[str, Any]:
    """Retrieve relevant knowledge base chunks above the similarity threshold.

    Documented answers score above 0.45 against these section-level chunks while
    only loosely related questions land near 0.30, so 0.35 is what makes the
    agent admit it does not know instead of answering from an unrelated section.
    """
    if not query.strip():
        return {"found": False, "results": [], "message": "Empty query."}

    collection = _get_collection()
    if collection.count() == 0:
        ingest_knowledge_base()
        collection = _get_collection()
        if collection.count() == 0:
            return {
                "found": False,
                "results": [],
                "message": "Knowledge base is empty.",
            }

    raw = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    matches: list[dict[str, Any]] = []
    for doc, meta, dist in zip(docs, metas, distances):
        similarity = round(1.0 - float(dist), 4)
        if similarity >= min_similarity:
            matches.append(
                {
                    "source": (meta or {}).get("source", "unknown"),
                    "text": doc,
                    "similarity": similarity,
                }
            )

    if not matches:
        return {
            "found": False,
            "results": [],
            "message": "No relevant information found in the company knowledge base.",
        }

    return {"found": True, "results": matches}
