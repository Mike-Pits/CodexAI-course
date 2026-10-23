from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from docx import Document


DOCUMENTS = [
    (
        "01_ответственность_капитана.md",
        "6. ОТВЕТСТВЕННОСТЬ И ПОЛНОМОЧИЯ КАПИТАНА",
        "7. ЭКИПАЖ СУДНА",
    ),
    (
        "02_подготовка_персонала.md",
        "8. ОЗНАКОМЛЕНИЕ И ПОДГОТОВКА ПЕРСОНАЛА НА СУДНЕ",
        "9. СУДОВЫЕ ОПЕРАЦИИ",
    ),
    (
        "03_аварийная_готовность.md",
        "10. ГОТОВНОСТЬ К АВАРИЙНЫМ СИТУАЦИЯМ",
        "11. СООБЩЕНИЯ О НЕСООТВЕТСТВИЯХ, АВАРИЯХ И ОПАСНЫХ СИТУАЦИЯХ",
    ),
    (
        "04_несоответствия_и_опасные_ситуации.md",
        "11. СООБЩЕНИЯ О НЕСООТВЕТСТВИЯХ, АВАРИЯХ И ОПАСНЫХ СИТУАЦИЯХ",
        "ТЕХНИЧЕСКАЯ ЭКСПЛУАТАЦИЯ И ОБСЛУЖИВАНИЕ СУДОВ",
    ),
    (
        "05_управление_документацией.md",
        "13. УПРАВЛЕНИЕ ДОКУМЕНТАЦИЕЙ",
        "14. ПРОВЕРКИ, АНАЛИЗ И ОЦЕНКА СУБ СО СТОРОНЫ КОМПАНИИ",
    ),
]


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def convert_if_needed(source: Path, workdir: Path, soffice: str) -> Path:
    if source.suffix.lower() == ".docx":
        return source
    subprocess.run(
        [soffice, "--headless", "--convert-to", "docx", "--outdir", str(workdir), str(source)],
        check=True,
    )
    converted = workdir / f"{source.stem}.docx"
    if not converted.exists():
        raise RuntimeError("LibreOffice не создал DOCX")
    return converted


def find_index(paragraphs: list[str], title: str, start: int = 0) -> int:
    for index in range(start, len(paragraphs)):
        if paragraphs[index] == title:
            return index
    raise ValueError(f"Раздел не найден: {title}")


def markdown_section(paragraphs: list[str]) -> str:
    lines: list[str] = []
    for text in paragraphs:
        if not text:
            continue
        if re.match(r"^\d+(?:\.\d+)*\s+[^.]{2,100}$", text) or text.isupper():
            lines.extend([f"## {text}", ""])
        else:
            lines.extend([text, ""])
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Извлечь пять документов Lite из Судового руководства")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "knowledge")
    parser.add_argument("--soffice", default="soffice")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lite-kb-") as temp:
        docx = convert_if_needed(args.source.resolve(), Path(temp), args.soffice)
        document = Document(docx)
        paragraphs = [normalized(p.text) for p in document.paragraphs]
        # Пропускаем содержание: реальные разделы начинаются со второго появления раздела 1.
        content_start = find_index(paragraphs, "1. ОБЩИЕ ПОЛОЖЕНИЯ", 60)
        for filename, start_title, end_title in DOCUMENTS:
            start = find_index(paragraphs, start_title, content_start)
            end = find_index(paragraphs, end_title, start + 1)
            body = markdown_section(paragraphs[start:end])
            header = (
                "---\n"
                f'source: "СП Судовое руководство по СУБ — {start_title}"\n'
                f'section: "{start_title}"\n'
                'version: "29.10.2021"\n'
                "---\n\n"
            )
            (args.output / filename).write_text(header + body, encoding="utf-8")
            print(f"Создан {filename}: {end - start} абзацев")


if __name__ == "__main__":
    main()

