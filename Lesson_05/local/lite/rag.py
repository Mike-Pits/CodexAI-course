from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from openai import OpenAI


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    section: str
    version: str
    text: str


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[dict[str, str | float]]
    diagnostics: list[dict[str, str | float]]


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"')
    return values, text[match.end() :]


def chunk_markdown(path: Path, max_chars: int = 1800, overlap_chars: int = 250) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    metadata, body = _front_matter(raw)
    source = metadata.get("source", path.name)
    version = metadata.get("version", "не указана")
    section = metadata.get("section", path.stem)
    chunks: list[Chunk] = []
    current_section = section
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n\n".join(item for item in buffer if item).strip()
        if not text:
            buffer = []
            return
        chunk_id = f"{path.stem}:{len(chunks) + 1}"
        chunks.append(Chunk(chunk_id, source, current_section, version, text))
        if overlap_chars:
            tail = text[-overlap_chars:]
            first_break = tail.find("\n")
            buffer = [tail[first_break + 1 :] if first_break >= 0 else tail]
        else:
            buffer = []

    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        heading = HEADING_RE.match(block)
        if heading:
            flush()
            current_section = heading.group(2).strip()
            buffer = [block]
            continue
        projected = len("\n\n".join(buffer + [block]))
        if buffer and projected > max_chars:
            flush()
        buffer.append(block)
    flush()
    return chunks


def load_chunks(knowledge_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        chunks.extend(chunk_markdown(path))
    if not chunks:
        raise RuntimeError(f"В {knowledge_dir} не найдено документов .md")
    return chunks


def _normalized(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        if not api_key:
            raise RuntimeError("LOCAL_LLM_API_KEY не задан")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        response = self.client.embeddings.create(model=self.model, input=list(texts))
        ordered = sorted(response.data, key=lambda item: item.index)
        return np.asarray([item.embedding for item in ordered], dtype=np.float32)


class VectorIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, model: str) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Количество чанков и embeddings не совпадает")
        self.chunks = chunks
        self.embeddings = _normalized(np.asarray(embeddings, dtype=np.float32))
        self.model = model

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: OpenAIEmbedder, batch_size: int = 64) -> "VectorIndex":
        vectors: list[np.ndarray] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors.append(embedder.embed([chunk.text for chunk in batch]))
        return cls(chunks, np.vstack(vectors), embedder.model)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "embedding_model": self.model,
            "chunks": [asdict(chunk) for chunk in self.chunks],
            "embeddings": self.embeddings.tolist(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "VectorIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        chunks = [Chunk(**item) for item in payload["chunks"]]
        return cls(chunks, np.asarray(payload["embeddings"], dtype=np.float32), payload["embedding_model"])

    def search(self, query_vector: np.ndarray, top_k: int = 5, min_score: float = -1.0) -> list[SearchHit]:
        query = _normalized(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
        if query.shape[0] != self.embeddings.shape[1]:
            raise ValueError("Размерность запроса не совпадает с индексом")
        scores = self.embeddings @ query
        order = np.argsort(-scores)[:top_k]
        return [SearchHit(self.chunks[i], float(scores[i])) for i in order if scores[i] >= min_score]


SYSTEM_PROMPT = """Ты — помощник по судовой системе управления безопасностью.
Отвечай только по предоставленному контексту. Не используй догадки и внешние знания.
Если контекст не подтверждает ответ, прямо скажи: «В базе знаний нет подтверждённой информации для ответа на этот вопрос».
Верни JSON с полями answer (строка) и used_chunk_ids (массив идентификаторов).
В answer давай ясный ответ на русском языке и ставь ссылки вида [Источник: название, раздел].
Отвечай кратко и не добавляй сведения, о которых не спрашивали.
В used_chunk_ids перечисляй только те фрагменты, на которые действительно опирается ответ."""

ANSWER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "rag_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "minLength": 1},
                "used_chunk_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "used_chunk_ids"],
            "additionalProperties": False,
        },
    },
}


class LiteRAG:
    def __init__(
        self, index: VectorIndex, embedder: OpenAIEmbedder, api_key: str, base_url: str, chat_model: str
    ) -> None:
        self.index = index
        self.embedder = embedder
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.chat_model = chat_model

    def ask(self, question: str, top_k: int, min_similarity: float) -> Answer:
        query_vector = self.embedder.embed([question])[0]
        hits = self.index.search(query_vector, top_k=top_k, min_score=min_similarity)
        diagnostics = [
            {
                "chunk_id": hit.chunk.id,
                "source": hit.chunk.source,
                "section": hit.chunk.section,
                "score": round(hit.score, 4),
                "preview": hit.chunk.text[:280],
            }
            for hit in hits
        ]
        if not hits:
            return Answer(
                "В базе знаний нет подтверждённой информации для ответа на этот вопрос.",
                [],
                diagnostics,
            )
        context = "\n\n".join(
            f"CHUNK_ID: {hit.chunk.id}\nИСТОЧНИК: {hit.chunk.source}\nРАЗДЕЛ: {hit.chunk.section}\n"
            f"ВЕРСИЯ: {hit.chunk.version}\nТЕКСТ:\n{hit.chunk.text}"
            for hit in hits
        )
        response = self.client.chat.completions.create(
            model=self.chat_model,
            response_format=ANSWER_RESPONSE_FORMAT,
            temperature=0,
            seed=0,
            max_tokens=700,
            reasoning_effort="none",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"КОНТЕКСТ:\n{context}\n\nВОПРОС:\n{question}"},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"answer": raw, "used_chunk_ids": [hit.chunk.id for hit in hits]}
        allowed_ids = {hit.chunk.id for hit in hits}
        used_ids = {chunk_id for chunk_id in (result.get("used_chunk_ids") or []) if chunk_id in allowed_ids}
        no_answer = str(result.get("answer", "")).strip().startswith(
            "В базе знаний нет подтверждённой информации"
        )
        if not no_answer and not used_ids:
            used_ids.add(hits[0].chunk.id)
        sources: list[dict[str, str | float]] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits:
            key = (hit.chunk.source, hit.chunk.section)
            if hit.chunk.id in used_ids and key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "source": hit.chunk.source,
                        "section": hit.chunk.section,
                        "version": hit.chunk.version,
                        "score": round(hit.score, 4),
                    }
                )
        return Answer(str(result.get("answer", "")).strip(), sources, diagnostics)


def unique_sources(chunks: Iterable[Chunk]) -> int:
    return len({chunk.source for chunk in chunks})

