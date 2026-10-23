from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from docx import Document


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def convert(source: Path, workdir: Path, soffice: str) -> Path:
    if source.suffix.lower() == ".docx":
        return source
    subprocess.run(
        [soffice, "--headless", "--convert-to", "docx", "--outdir", str(workdir), str(source)],
        check=True,
    )
    target = workdir / f"{source.stem}.docx"
    if not target.exists():
        raise RuntimeError("LibreOffice не создал DOCX")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Извлечь полный текст Судового руководства для Pro")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "knowledge")
    parser.add_argument("--soffice", default="soffice")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pro-kb-") as temp:
        docx_path = convert(args.source.resolve(), Path(temp), args.soffice)
        document = Document(docx_path)
        paragraphs = list(document.paragraphs)
        start = next(
            index
            for index, paragraph in enumerate(paragraphs[60:], 60)
            if normalized(paragraph.text) == "1. ОБЩИЕ ПОЛОЖЕНИЯ"
        )
        lines = [
            "---",
            'source: "СП Судовое руководство по управлению безопасностью и предотвращением загрязнения"',
            'section: "Судовое руководство по СУБ"',
            'version: "29.10.2021"',
            "---",
            "",
            "# Судовое руководство по управлению безопасностью и предотвращением загрязнения",
            "",
        ]
        for paragraph in paragraphs[start:]:
            text = normalized(paragraph.text)
            if not text:
                continue
            style = paragraph.style.name
            if style == "Мой заголовок 1":
                lines.extend([f"## {text}", ""])
            elif style == "Мой заголовок 2":
                lines.extend([f"### {text}", ""])
            elif style == "Мой заголовок 3":
                lines.extend([f"#### {text}", ""])
            else:
                lines.extend([text, ""])
        output = args.output / "Судовое_руководство_СУБ.md"
        output.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        print(f"Создан {output.name}: {len(paragraphs) - start} абзацев")


if __name__ == "__main__":
    main()

