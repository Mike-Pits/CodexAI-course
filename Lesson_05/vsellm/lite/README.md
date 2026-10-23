# СУБ Помощник Lite

Локальный веб-чат с настоящим RAG по пяти тематическим документам, извлечённым из «Судового руководства по управлению безопасностью и предотвращением загрязнения». Приложение обращается к OpenAI-совместимому API VseLLM, сохраняет локальный векторный индекс и ищет чанки по косинусному сходству. Вся база в prompt не передаётся.

## Быстрый запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Впишите VSELLM_API_KEY в .env
python ingest.py
uvicorn app:app --reload
```

Откройте <http://127.0.0.1:8000>. Проверка состояния доступна на <http://127.0.0.1:8000/api/health>.

## Docker

После заполнения `.env`:

```bash
docker compose run --rm lite-rag python ingest.py
docker compose up --build
```

## Как устроен RAG

1. `scripts/prepare_kb.py` выделяет из исходного Word-файла пять самостоятельных документов.
2. `rag.py` делит Markdown по разделам на перекрывающиеся смысловые чанки и сохраняет метаданные источника, раздела и версии.
3. `ingest.py` получает embeddings `openai/text-embedding-3-small` через `https://api.vsellm.ru/v1` и создаёт локальный JSON-векторный индекс.
4. Для вопроса строится embedding, выполняется top-K поиск по cosine similarity и только найденные чанки передаются `openai/gpt-4.1-mini` через VseLLM.
5. Модель возвращает ответ и идентификаторы реально использованных чанков. Интерфейс показывает соответствующие источники.

## Повторное извлечение базы

```bash
python scripts/prepare_kb.py "../СП Судовое рук по СУБ.doc" \
  --soffice /path/to/soffice
```

После изменения документов снова выполните `python ingest.py`.

## Тесты

```bash
pytest -q
```

Пять обязательных end-to-end вопросов находятся в `tests/e2e_questions.json`. Фактические ответы и источники фиксируются в отчёте `Отчет_тестирования_Lite.docx`.

