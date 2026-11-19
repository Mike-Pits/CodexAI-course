# Домашнее задание 09: AI-агенты и MCP

Исходные задания `ДЗ lite .odt` и `ДЗ Pro.odt` сохранены без изменений.

Выполнение идёт последовательно: сначала `lite/` (погода), после проверки — `pro/` (Excel).

## Выбор модели

Рекомендуемый API-вариант для этого небольшого проекта: `gpt-4.1-mini`, поддерживает function calling через Chat Completions. Настройки находятся в `.env.example`; секрет хранится только в локальном `.env`.

Бесплатный вариант, обнаруженный на компьютере: Ollama `qwen3:8b`. Проверки выполняются на ней. Небольшая модель может ошибаться в параметрах: приложение ограничивает инструменты, проверяет координаты и не подменяет MCP вымышленными результатами.

Документация: https://developers.openai.com/api/docs/models/gpt-4.1-mini и https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create .

## Готовые результаты

- `lite/`: чат погоды, инструкция `lite/README.md`, реальные вызовы и ответы `lite/evidence/verification.json`.
- `pro/`: чат и таблица заявок, инструкция и описание MCP в `pro/README.md`, итоговая книга `pro/data/requests.xlsx`, журнал обязательных сценариев `pro/evidence/verification.json`.
- `REPORT.md`: что проверено и ограничения.

## Быстрый запуск с установленной Ollama

```bash
# Из корня проекта
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd lite
npm ci
cp .env.ollama.example .env
npm start
# В другом терминале из корня:
cd pro
cp .env.ollama.example .env
npm start
```

Lite: http://127.0.0.1:3000. Pro: http://127.0.0.1:3001.
Сервис Ollama должен работать, модель `qwen3:8b` должна быть загружена (`ollama pull qwen3:8b`). В архив не включаются `.env`, виртуальное окружение, node_modules и временные тестовые книги.
