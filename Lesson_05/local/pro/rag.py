from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

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
class RankedHit:
    chunk: Chunk
    score: float
    rank: int = 0


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[dict[str, str | float]]
    diagnostics: dict[str, list[dict[str, str | float | int]]]


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TOKEN_RE = re.compile(r"[a-zа-яё0-9]+(?:[-/.][a-zа-яё0-9]+)*", re.IGNORECASE)


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


def chunk_markdown(path: Path, max_chars: int = 1800, overlap_chars: int = 220) -> list[Chunk]:
    metadata, body = _front_matter(path.read_text(encoding="utf-8"))
    source = metadata.get("source", path.name)
    version = metadata.get("version", "не указана")
    current_section = metadata.get("section", path.stem)
    chunks: list[Chunk] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n\n".join(buffer).strip()
        if not text:
            buffer = []
            return
        chunks.append(Chunk(f"{path.stem}:{len(chunks) + 1}", source, current_section, version, text))
        tail = text[-overlap_chars:] if overlap_chars else ""
        first_break = tail.find("\n")
        buffer = [tail[first_break + 1 :] if first_break >= 0 else tail] if tail else []

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
        if buffer and len("\n\n".join(buffer + [block])) > max_chars:
            flush()
        buffer.append(block)
    flush()
    return chunks


def load_chunks(knowledge_dir: Path) -> list[Chunk]:
    chunks = [chunk for path in sorted(knowledge_dir.glob("*.md")) for chunk in chunk_markdown(path)]
    if not chunks:
        raise RuntimeError(f"В {knowledge_dir} не найдено документов .md")
    return chunks


def _normalized(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def tokenize(text: str) -> list[str]:
    return [token.lower().replace("ё", "е") for token in TOKEN_RE.findall(text)]


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
        vectors = [
            embedder.embed([chunk.text for chunk in chunks[start : start + batch_size]])
            for start in range(0, len(chunks), batch_size)
        ]
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
        return cls(
            [Chunk(**item) for item in payload["chunks"]],
            np.asarray(payload["embeddings"], dtype=np.float32),
            payload["embedding_model"],
        )

    def search(self, query_vector: np.ndarray, top_k: int, min_score: float) -> list[RankedHit]:
        query = _normalized(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
        if query.shape[0] != self.embeddings.shape[1]:
            raise ValueError("Размерность запроса не совпадает с индексом")
        scores = self.embeddings @ query
        order = np.argsort(-scores)[:top_k]
        return [
            RankedHit(self.chunks[i], float(scores[i]), rank)
            for rank, i in enumerate(order, 1)
            if scores[i] >= min_score
        ]


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.documents = [tokenize(f"{chunk.section} {chunk.text}") for chunk in chunks]
        self.term_frequencies = [Counter(document) for document in self.documents]
        self.lengths = [len(document) for document in self.documents]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1)
        document_frequency: Counter[str] = Counter()
        for document in self.documents:
            document_frequency.update(set(document))
        total = len(self.documents)
        self.idf = {
            term: math.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, top_k: int) -> list[RankedHit]:
        terms = tokenize(query)
        scores: list[float] = []
        for frequency, length in zip(self.term_frequencies, self.lengths):
            score = 0.0
            for term in terms:
                tf = frequency.get(term, 0)
                if not tf:
                    continue
                denominator = tf + self.k1 * (1 - self.b + self.b * length / max(self.avg_length, 1.0))
                score += self.idf.get(term, 0.0) * (tf * (self.k1 + 1)) / denominator
            scores.append(score)
        order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        return [
            RankedHit(self.chunks[index], scores[index], rank)
            for rank, index in enumerate(order[:top_k], 1)
            if scores[index] > 0
        ]


def reciprocal_rank_fusion(
    vector_hits: list[RankedHit], bm25_hits: list[RankedHit], top_k: int, rrf_k: int = 60
) -> list[RankedHit]:
    chunks: dict[str, Chunk] = {}
    scores: Counter[str] = Counter()
    for channel in (vector_hits, bm25_hits):
        for rank, hit in enumerate(channel, 1):
            chunks[hit.chunk.id] = hit.chunk
            scores[hit.chunk.id] += 1.0 / (rrf_k + rank)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
    return [RankedHit(chunks[chunk_id], scores[chunk_id], rank) for rank, chunk_id in enumerate(ordered, 1)]


SYSTEM_PROMPT = """Ты — оператор поддержки по судовой системе управления безопасностью.
Отвечай только по предоставленному контексту, без догадок и внешних знаний.
Если контекст не подтверждает ответ, сообщи: «В базе знаний нет подтверждённой информации для ответа на этот вопрос».
Верни JSON с полями answer и used_chunk_ids. Ответ пиши по-русски, с конкретными условиями и исключениями.
В тексте используй ссылки [Источник: Судовое руководство по СУБ, раздел X].
Отвечай кратко и не добавляй сведения, о которых не спрашивали.
В used_chunk_ids указывай только действительно использованные фрагменты."""

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


def diagnostic_rows(hits: list[RankedHit]) -> list[dict[str, str | float | int]]:
    return [
        {
            "rank": hit.rank,
            "chunk_id": hit.chunk.id,
            "source": hit.chunk.source,
            "section": hit.chunk.section,
            "score": round(hit.score, 5),
            "preview": hit.chunk.text[:320],
        }
        for hit in hits
    ]


class HybridRAG:
    def __init__(
        self, index: VectorIndex, embedder: OpenAIEmbedder, api_key: str, base_url: str, chat_model: str
    ) -> None:
        self.index = index
        self.embedder = embedder
        self.bm25 = BM25Index(index.chunks)
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.chat_model = chat_model

    def ask(
        self,
        question: str,
        vector_top_k: int,
        bm25_top_k: int,
        final_top_k: int,
        min_similarity: float,
    ) -> Answer:
        query_vector = self.embedder.embed([question])[0]
        vector_hits = self.index.search(query_vector, vector_top_k, min_similarity)
        bm25_hits = self.bm25.search(question, bm25_top_k)
        fused_hits = reciprocal_rank_fusion(vector_hits, bm25_hits, final_top_k)
        diagnostics = {
            "vector": diagnostic_rows(vector_hits),
            "bm25": diagnostic_rows(bm25_hits),
            "final": diagnostic_rows(fused_hits),
        }
        if not fused_hits:
            return Answer(
                "В базе знаний нет подтверждённой информации для ответа на этот вопрос.", [], diagnostics
            )
        context = "\n\n".join(
            f"CHUNK_ID: {hit.chunk.id}\nИСТОЧНИК: {hit.chunk.source}\nРАЗДЕЛ: {hit.chunk.section}\n"
            f"ВЕРСИЯ: {hit.chunk.version}\nТЕКСТ:\n{hit.chunk.text}"
            for hit in fused_hits
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
            result = {"answer": raw, "used_chunk_ids": [hit.chunk.id for hit in fused_hits]}
        allowed_ids = {hit.chunk.id for hit in fused_hits}
        used_ids = {chunk_id for chunk_id in (result.get("used_chunk_ids") or []) if chunk_id in allowed_ids}
        no_answer = str(result.get("answer", "")).strip().startswith(
            "В базе знаний нет подтверждённой информации"
        )
        if not no_answer and not used_ids:
            used_ids.add(fused_hits[0].chunk.id)
        sources: list[dict[str, str | float]] = []
        seen: set[tuple[str, str]] = set()
        for hit in fused_hits:
            key = (hit.chunk.source, hit.chunk.section)
            if hit.chunk.id in used_ids and key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "source": hit.chunk.source,
                        "section": hit.chunk.section,
                        "version": hit.chunk.version,
                        "rrf_score": round(hit.score, 5),
                    }
                )
        return Answer(str(result.get("answer", "")).strip(), sources, diagnostics)

