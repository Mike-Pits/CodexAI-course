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
        api_key=os.getenv("VSELLM_API_KEY", ""),
        base_url=os.getenv("VSELLM_BASE_URL", "https://api.vsellm.ru/v1"),
        chat_model=os.getenv("VSELLM_CHAT_MODEL", "openai/gpt-4.1-mini"),
        embedding_model=os.getenv("VSELLM_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        vector_top_k=int(os.getenv("VECTOR_TOP_K", "8")),
        bm25_top_k=int(os.getenv("BM25_TOP_K", "8")),
        final_top_k=int(os.getenv("FINAL_TOP_K", "6")),
        min_similarity=float(os.getenv("MIN_SIMILARITY", "0.20")),
        knowledge_dir=ROOT / "knowledge",
        index_path=ROOT / "data" / "index.json",
    )

