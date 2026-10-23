from pathlib import Path

import numpy as np

from rag import Chunk, VectorIndex, chunk_markdown


def test_chunk_markdown_preserves_metadata(tmp_path: Path) -> None:
    source = tmp_path / "sample.md"
    source.write_text(
        '---\nsource: "Руководство"\nsection: "Раздел 1"\nversion: "2021"\n---\n\n'
        "## 1. Правила\n\nКапитан контролирует выполнение требований.",
        encoding="utf-8",
    )
    chunks = chunk_markdown(source, max_chars=500)
    assert len(chunks) == 1
    assert chunks[0].source == "Руководство"
    assert chunks[0].section == "1. Правила"
    assert chunks[0].version == "2021"


def test_vector_search_uses_cosine_similarity() -> None:
    chunks = [
        Chunk("a", "doc-a", "A", "1", "аварийная готовность"),
        Chunk("b", "doc-b", "B", "1", "управление документами"),
    ]
    index = VectorIndex(chunks, np.asarray([[1.0, 0.0], [0.0, 1.0]]), "test")
    hits = index.search(np.asarray([0.9, 0.1]), top_k=1)
    assert hits[0].chunk.id == "a"
    assert hits[0].score > 0.99


def test_vector_search_respects_threshold() -> None:
    chunks = [Chunk("a", "doc-a", "A", "1", "текст")]
    index = VectorIndex(chunks, np.asarray([[1.0, 0.0]]), "test")
    assert index.search(np.asarray([0.0, 1.0]), min_score=0.1) == []

