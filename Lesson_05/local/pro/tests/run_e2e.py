from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from config import get_settings
from rag import HybridRAG, OpenAIEmbedder, VectorIndex, load_chunks


def main() -> None:
    settings = get_settings()
    embedder = OpenAIEmbedder(settings.api_key, settings.embedding_model, settings.base_url)
    if not settings.index_path.exists():
        VectorIndex.build(load_chunks(settings.knowledge_dir), embedder).save(settings.index_path)
    index = VectorIndex.load(settings.index_path)
    service = HybridRAG(index, embedder, settings.api_key, settings.base_url, settings.chat_model)
    scenarios = json.loads((HERE / "e2e_questions.json").read_text(encoding="utf-8"))
    results = []
    for number, scenario in enumerate(scenarios, 1):
        started = time.perf_counter()
        answer = service.ask(
            scenario["question"],
            settings.vector_top_k,
            settings.bm25_top_k,
            settings.final_top_k,
            settings.min_similarity,
        )
        results.append(
            {
                "number": number,
                **scenario,
                "elapsed_seconds": round(time.perf_counter() - started, 2),
                **asdict(answer),
            }
        )
        print(f"[{number}/{len(scenarios)}] {scenario['type']}: {answer.text[:100]}")
    (HERE / "e2e_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

