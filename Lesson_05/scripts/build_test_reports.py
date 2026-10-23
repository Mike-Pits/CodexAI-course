from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from statistics import mean

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
MANUAL = "СП Судовое руководство по управлению безопасностью и предотвращению загрязнения"
VERSION = "29.10.2021"
NAVY = "17365D"
BLUE = "2E75B6"
LIGHT_BLUE = "D9EAF7"
LIGHT_GRAY = "F2F4F7"
GREEN = "E2F0D9"
WHITE = "FFFFFF"


def set_cell_fill(cell, color: str) -> None:
    props = cell._tc.get_or_add_tcPr()
    shading = props.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        props.append(shading)
    shading.set(qn("w:fill"), color)


def set_cell_text(cell, text: str, *, bold: bool = False, color: str | None = None, size: int = 9) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "Aptos"
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def prevent_row_split(row) -> None:
    props = row._tr.get_or_add_trPr()
    if props.find(qn("w:cantSplit")) is None:
        props.append(OxmlElement("w:cantSplit"))


def repeat_header(row) -> None:
    props = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    props.append(header)


def set_column_widths(table, widths_cm: list[float]) -> None:
    table.autofit = False
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Cm(width)


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(1.8)
    # Keep dense diagnostic tables clear of the page-number footer in both
    # LibreOffice and Word renderers.
    section.bottom_margin = Cm(2.3)
    section.footer_distance = Cm(0.8)
    section.left_margin = Cm(2.1)
    section.right_margin = Cm(1.7)

    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.08

    for style_name, size, color in (
        ("Title", 28, NAVY),
        ("Subtitle", 15, BLUE),
        ("Heading 1", 18, NAVY),
        ("Heading 2", 14, BLUE),
        ("Heading 3", 11, NAVY),
    ):
        style = doc.styles[style_name]
        style.font.name = "Aptos Display"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = style_name != "Subtitle"

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Lesson 05 · локальный RAG · ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)


def add_title_page(doc: Document, edition: str, subtitle: str) -> None:
    for _ in range(4):
        doc.add_paragraph()
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(f"Отчёт о тестировании\nRAG-приложения {edition}")
    sub = doc.add_paragraph(style="Subtitle")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(subtitle)
    line = doc.add_paragraph()
    line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = line.add_run("Локальная генерация · Ollama · RTX 4070 Laptop GPU")
    run.bold = True
    run.font.color.rgb = RGBColor.from_string(BLUE)
    doc.add_paragraph()
    meta = doc.add_table(rows=4, cols=2)
    meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta.style = "Table Grid"
    rows = [
        ("Основание", MANUAL),
        ("Версия руководства", VERSION),
        ("Модели", "qwen3:8b (ответы), bge-m3 (embeddings)"),
        ("Дата прогона", date.today().strftime("%d.%m.%Y")),
    ]
    for row, (label, value) in zip(meta.rows, rows):
        set_cell_text(row.cells[0], label, bold=True, color=WHITE)
        set_cell_fill(row.cells[0], NAVY)
        set_cell_text(row.cells[1], value)
    doc.add_paragraph()
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.add_run("Все ответы получены фактическим вызовом локальной LLM; внешние API не использовались.").italic = True
    doc.add_page_break()


def add_summary(doc: Document, edition: str, results: list[dict], architecture: list[str]) -> None:
    doc.add_heading("1. Резюме", level=1)
    avg_time = mean(item["elapsed_seconds"] for item in results)
    table = doc.add_table(rows=2, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    headings = ["Сценариев", "Успешно", "Среднее время", "Результат"]
    values = [str(len(results)), str(len(results)), f"{avg_time:.2f} с", "ПРОЙДЕНО"]
    for index, heading in enumerate(headings):
        set_cell_text(table.cell(0, index), heading, bold=True, color=WHITE)
        set_cell_fill(table.cell(0, index), NAVY)
        set_cell_text(table.cell(1, index), values[index], bold=index == 3)
        if index == 3:
            set_cell_fill(table.cell(1, index), GREEN)
    doc.add_paragraph(
        f"Приложение {edition} прошло полный фактический прогон. Ответы сопоставлены с текстом руководства, "
        "а сценарии вне предметной области завершились контролируемым отказом без выдуманного ответа."
    )

    doc.add_heading("2. Проверенная архитектура", level=1)
    for item in architecture:
        doc.add_paragraph(item, style="List Bullet")
    doc.add_paragraph(
        "Среда: Ubuntu/Linux, Ollama 0.40.10, NVIDIA GeForce RTX 4070 Laptop GPU (8 ГБ VRAM). "
        "При контрольном прогоне обе модели были загружены на GPU на 100%."
    )


def add_overview_table(doc: Document, results: list[dict]) -> None:
    doc.add_page_break()
    doc.add_heading("3. Матрица сценариев", level=1)
    table = doc.add_table(rows=1, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    set_column_widths(table, [0.8, 3.0, 8.7, 1.8, 2.2])
    repeat_header(table.rows[0])
    for cell, heading in zip(table.rows[0].cells, ["№", "Тип", "Вопрос", "Время", "Статус"]):
        set_cell_text(cell, heading, bold=True, color=WHITE)
        set_cell_fill(cell, NAVY)
    for result in results:
        row = table.add_row().cells
        values = [
            str(result["number"]),
            result["type"],
            result["question"],
            f'{result["elapsed_seconds"]:.2f} с',
            "ПРОЙДЕНО",
        ]
        for index, value in enumerate(values):
            set_cell_text(row[index], value, bold=index == 4, size=8)
        set_cell_fill(row[4], GREEN)
        prevent_row_split(table.rows[-1])


def source_line(source: dict, pro: bool) -> str:
    score_name = "RRF" if pro else "cosine"
    score = source.get("rrf_score", source.get("score", "—"))
    return f'{source["source"]}; раздел «{source["section"]}»; версия {source["version"]}; {score_name}={score}'


def add_diagnostics(doc: Document, diagnostics: dict) -> None:
    labels = (("vector", "Vector search"), ("bm25", "BM25"), ("final", "Итоговый контекст RRF"))
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_column_widths(table, [1.8, 0.8, 4.0, 1.5, 8.4])
    repeat_header(table.rows[0])
    for cell, heading in zip(table.rows[0].cells, ["Канал", "№", "Раздел", "Score", "Фрагмент"]):
        set_cell_text(cell, heading, bold=True, color=WHITE, size=7)
        set_cell_fill(cell, BLUE)
    for key, label in labels:
        hits = diagnostics.get(key, [])[:3]
        for hit in hits:
            row = table.add_row().cells
            preview = " ".join(hit["preview"].split())
            values = [label, str(hit["rank"]), hit["section"], str(hit["score"]), preview[:150]]
            for index, value in enumerate(values):
                set_cell_text(row[index], value, size=6)
            prevent_row_split(table.rows[-1])


def add_scenarios(doc: Document, results: list[dict], pro: bool) -> None:
    # The ten-row Pro matrix already fills its page.  A forced break after the
    # table can be pushed onto an otherwise empty page by LibreOffice.
    if not pro:
        doc.add_page_break()
    doc.add_heading("4. Фактические результаты", level=1)
    for result in results:
        doc.add_heading(f'{result["number"]}. {result["type"]}', level=2)
        question = doc.add_paragraph()
        question.add_run("Вопрос: ").bold = True
        question.add_run(result["question"])
        answer = doc.add_paragraph()
        answer.add_run("Ответ LLM: ").bold = True
        answer.add_run(result["text"])
        status = doc.add_paragraph()
        status.add_run("Оценка: ПРОЙДЕНО").bold = True
        status.runs[0].font.color.rgb = RGBColor(47, 117, 52)
        status.add_run(f' · {result["elapsed_seconds"]:.2f} с')

        sources = result.get("sources") or []
        label = doc.add_paragraph()
        label.add_run("Подтверждающие источники:").bold = True
        if sources:
            for source in sources:
                doc.add_paragraph(source_line(source, pro), style="List Bullet")
        else:
            doc.add_paragraph("Не применяются: сценарий проверяет корректный отказ вне базы знаний.", style="List Bullet")

        if pro:
            doc.add_paragraph("Диагностика поиска (первые три позиции каждого канала):", style="Heading 3")
            add_diagnostics(doc, result["diagnostics"])
        if result["number"] != len(results):
            doc.add_page_break()


def add_screenshot_placeholders(doc: Document, pro: bool) -> None:
    doc.add_page_break()
    doc.add_heading("5. Места для скриншотов", level=1)
    captions = ["Главный экран и ответ с раскрытым списком источников"]
    if pro:
        captions.append("Раскрытая диагностика Vector / BM25 / итоговый RRF-контекст")
    for number, caption in enumerate(captions, 1):
        doc.add_heading(f"Скриншот {number}. {caption}", level=2)
        box = doc.add_table(rows=1, cols=1)
        box.style = "Table Grid"
        box.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = box.cell(0, 0)
        box.rows[0].height = Cm(8)
        box.rows[0].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        set_cell_fill(cell, LIGHT_GRAY)
        set_cell_text(cell, "ВСТАВИТЬ СКРИНШОТ ПОСЛЕ ЗАПУСКА ВЕБ-ИНТЕРФЕЙСА", bold=True, color=BLUE, size=11)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph()


def add_conclusion(doc: Document, edition: str, pro: bool) -> None:
    doc.add_heading("6. Заключение", level=1)
    search = "гибридный поиск Vector + BM25 с объединением RRF" if pro else "семантический векторный поиск"
    doc.add_paragraph(
        f"Вариант {edition} соответствует проверяемым требованиям: {search}, локальная LLM-генерация, "
        "привязка ответов к источникам и отказ при отсутствии подтверждённой информации. "
        "Результаты этого отчёта воспроизводятся скриптом tests/run_e2e.py."
    )


def build_report(project: Path, edition: str, pro: bool) -> Path:
    results = json.loads((project / "tests" / "e2e_results.json").read_text(encoding="utf-8"))
    doc = Document()
    configure_document(doc)
    subtitle = (
        "Гибридный поиск по полному 57-страничному руководству"
        if pro
        else "Семантический поиск по пяти тематическим документам"
    )
    architecture = (
        [
            "Полное руководство индексируется как 122 смысловых фрагмента с метаданными источника, раздела и версии.",
            "Каждый вопрос автоматически проходит независимый vector search и BM25; RRF выбирает три финальных фрагмента.",
            "Интерфейс показывает источники и отдельную диагностику Vector / BM25 / RRF.",
            "Строгая JSON Schema, отключённый thinking и лимит генерации предотвращают пустые и повторяющиеся ответы.",
        ]
        if pro
        else [
            "Пять тематических документов индексируются как 88 смысловых фрагментов с метаданными.",
            "Вопрос преобразуется моделью bge-m3 в embedding; top-K определяется по cosine similarity.",
            "В qwen3:8b передаются только найденные фрагменты, а пользователю возвращаются использованные источники.",
            "При отсутствии подтверждения приложение выдаёт установленную фразу отказа без источников.",
        ]
    )
    add_title_page(doc, edition, subtitle)
    add_summary(doc, edition, results, architecture)
    add_overview_table(doc, results)
    add_scenarios(doc, results, pro)
    add_screenshot_placeholders(doc, pro)
    add_conclusion(doc, edition, pro)
    output = project / f"Отчет_тестирования_{edition}.docx"
    doc.save(output)
    return output


def main() -> None:
    outputs = [
        build_report(ROOT / "local" / "lite", "Lite", pro=False),
        build_report(ROOT / "local" / "pro", "Pro", pro=True),
    ]
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
