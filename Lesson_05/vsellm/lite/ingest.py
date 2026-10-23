from __future__ import annotations

from config import get_settings
from rag import OpenAIEmbedder, VectorIndex, load_chunks, unique_sources


def main() -> None:
    settings = get_settings()
    chunks = load_chunks(settings.knowledge_dir)
    embedder = OpenAIEmbedder(settings.api_key, settings.embedding_model, settings.base_url)
    index = VectorIndex.build(chunks, embedder)
    index.save(settings.index_path)
    print(
        f"Индекс сохранён: {settings.index_path}\n"
        f"Документов: {unique_sources(chunks)}; чанков: {len(chunks)}; модель: {settings.embedding_model}"
    )


if __name__ == "__main__":
    main()

