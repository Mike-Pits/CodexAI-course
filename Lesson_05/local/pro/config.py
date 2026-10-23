from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Load a small .env file without overwriting exported environment variables."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    chat_model: str
    embedding_model: str
    vector_top_k: int
    bm25_top_k: int
    final_top_k: int
    min_similarity: float
    knowledge_dir: Path
    index_path: Path


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        api_key=os.getenv("LOCAL_LLM_API_KEY", "ollama"),
        base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
        chat_model=os.getenv("LOCAL_CHAT_MODEL", "qwen3:8b"),
        embedding_model=os.getenv("LOCAL_EMBEDDING_MODEL", "bge-m3"),
        vector_top_k=int(os.getenv("VECTOR_TOP_K", "8")),
        bm25_top_k=int(os.getenv("BM25_TOP_K", "8")),
        final_top_k=int(os.getenv("FINAL_TOP_K", "3")),
        min_similarity=float(os.getenv("MIN_SIMILARITY", "0.20")),
        knowledge_dir=ROOT / "knowledge",
        index_path=ROOT / "data" / "index.json",
    )

