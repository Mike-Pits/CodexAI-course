from pathlib import Path

import numpy as np

from rag import BM25Index, Chunk, VectorIndex, chunk_markdown, reciprocal_rank_fusion


def test_chunk_markdown_keeps_section_and_version(tmp_path: Path) -> None:
    source = tmp_path / "manual.md"
    source.write_text(
        '---\nsource: "Руководство"\nsection: "СУБ"\nversion: "29.10.2021"\n---\n\n'
        "## 11. Несоответствия\n\nДонесение оформляется по форме Д-8.",
        encoding="utf-8",
    )
    chunks = chunk_markdown(source)
    assert chunks[0].section == "11. Несоответствия"
    assert chunks[0].version == "29.10.2021"


def test_bm25_prioritizes_exact_form_code() -> None:
    chunks = [
        Chunk("a", "manual", "11", "2021", "Донесение о несоответствии оформляется по форме Д-8."),
        Chunk("b", "manual", "10", "2021", "Учения проводятся по аварийному расписанию."),
    ]
    hits = BM25Index(chunks).search("форма Д-8", top_k=2)
    assert hits[0].chunk.id == "a"


def test_rrf_merges_channels_and_removes_duplicates() -> None:
    chunks = [
        Chunk("a", "manual", "A", "2021", "alpha"),
        Chunk("b", "manual", "B", "2021", "beta"),
        Chunk("c", "manual", "C", "2021", "gamma"),
    ]
    vector = VectorIndex(chunks, np.eye(3), "test")
    vector_hits = vector.search(np.asarray([1.0, 0.4, 0.0]), top_k=2, min_score=-1)
    bm25_hits = BM25Index(chunks).search("beta", top_k=2)
    fused = reciprocal_rank_fusion(vector_hits, bm25_hits, top_k=3)
    assert fused[0].chunk.id == "b"
    assert len({hit.chunk.id for hit in fused}) == len(fused)


def test_vector_search_is_semantic_cosine_channel() -> None:
    chunks = [Chunk("a", "manual", "A", "2021", "one"), Chunk("b", "manual", "B", "2021", "two")]
    index = VectorIndex(chunks, np.asarray([[1.0, 0.0], [0.0, 1.0]]), "test")
    assert index.search(np.asarray([0.8, 0.2]), 1, -1)[0].chunk.id == "a"

