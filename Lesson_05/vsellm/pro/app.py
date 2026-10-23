from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import ROOT, get_settings
from rag import HybridRAG, OpenAIEmbedder, VectorIndex, load_chunks


app = FastAPI(title="СУБ Оператор Pro", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


def _service() -> HybridRAG:
    settings = get_settings()
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="VSELLM_API_KEY не задан в pro/.env")
    if not settings.index_path.exists():
        raise HTTPException(status_code=503, detail="Индекс не создан. Выполните: python ingest.py")
    index = VectorIndex.load(settings.index_path)
    if index.model != settings.embedding_model:
        raise HTTPException(status_code=503, detail="Модель embeddings изменилась. Пересоздайте индекс")
    return HybridRAG(
        index,
        OpenAIEmbedder(settings.api_key, settings.embedding_model, settings.base_url),
        settings.api_key,
        settings.base_url,
        settings.chat_model,
    )


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    settings = get_settings()
    chunks = load_chunks(settings.knowledge_dir)
    return {
        "status": "ready" if settings.api_key and settings.index_path.exists() else "setup_required",
        "api_key_configured": bool(settings.api_key),
        "index_exists": settings.index_path.exists(),
        "documents": len(list(settings.knowledge_dir.glob("*.md"))),
        "chunks_before_indexing": len(chunks),
        "embedding_model": settings.embedding_model,
        "chat_model": settings.chat_model,
        "provider": "VseLLM",
        "base_url": settings.base_url,
        "search": "vector + BM25 + RRF",
    }


@app.post("/api/ask")
def ask(payload: QuestionRequest) -> dict[str, object]:
    settings = get_settings()
    try:
        result = _service().ask(
            payload.question.strip(),
            settings.vector_top_k,
            settings.bm25_top_k,
            settings.final_top_k,
            settings.min_similarity,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка гибридного RAG: {exc}") from exc
    return asdict(result)


@app.post("/api/reindex")
def reindex() -> dict[str, object]:
    settings = get_settings()
    try:
        chunks = load_chunks(settings.knowledge_dir)
        index = VectorIndex.build(
            chunks, OpenAIEmbedder(settings.api_key, settings.embedding_model, settings.base_url)
        )
        index.save(settings.index_path)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось обновить индекс: {exc}") from exc
    return {"status": "ok", "documents": len(list(settings.knowledge_dir.glob("*.md"))), "chunks": len(chunks)}

