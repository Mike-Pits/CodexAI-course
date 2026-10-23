from config import get_settings
from rag import OpenAIEmbedder, VectorIndex, load_chunks


def main() -> None:
    settings = get_settings()
    chunks = load_chunks(settings.knowledge_dir)
    index = VectorIndex.build(
        chunks, OpenAIEmbedder(settings.api_key, settings.embedding_model, settings.base_url)
    )
    index.save(settings.index_path)
    print(f"Индекс сохранён: {settings.index_path}\nЧанков: {len(chunks)}; модель: {settings.embedding_model}")


if __name__ == "__main__":
    main()

