from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUTPUT = "Решение ДЗ Lite.docx"


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=110, start=120, bottom=110, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_borders(cell, color="D9D9D9", size="8"):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        node = borders.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:color"), color)


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def keep_with_next(paragraph):
    paragraph.paragraph_format.keep_with_next = True


def remove_paragraph_border(paragraph_or_style):
    element = paragraph_or_style._p if hasattr(paragraph_or_style, "_p") else paragraph_or_style.element
    p_pr = element.get_or_add_pPr()
    border = p_pr.find(qn("w:pBdr"))
    if border is not None:
        p_pr.remove(border)


def add_heading(doc, text, level=1):
    p = doc.add_paragraph(text, style=f"Heading {level}")
    keep_with_next(p)
    return p


doc = Document()
section = doc.sections[0]
section.page_width = Inches(8.5)
section.page_height = Inches(11)
section.top_margin = Inches(0.62)
section.bottom_margin = Inches(0.58)
section.left_margin = Inches(0.68)
section.right_margin = Inches(0.68)

styles = doc.styles
normal = styles["Normal"]
normal.font.name = "Aptos"
normal.font.size = Pt(10.5)
normal.font.color.rgb = RGBColor(0, 0, 0)
normal.paragraph_format.space_after = Pt(5)
normal.paragraph_format.line_spacing = 1.08

title_style = styles["Title"]
title_style.font.name = "Aptos Display"
title_style.font.size = Pt(24)
title_style.font.bold = True
title_style.font.color.rgb = RGBColor(0, 0, 0)
title_style.paragraph_format.space_after = Pt(7)
remove_paragraph_border(title_style)

for style_name, size, before, after in (
    ("Heading 1", 15, 8, 4),
    ("Heading 2", 12, 6, 3),
):
    style = styles[style_name]
    style.font.name = "Aptos Display"
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)
    style.paragraph_format.keep_with_next = True

doc.core_properties.title = "Путь голоса через AI агента"
doc.core_properties.subject = "Решение домашнего задания Lite"

title = doc.add_paragraph("Путь голоса через AI агента", style="Title")
remove_paragraph_border(title)
subtitle = doc.add_paragraph("Решение домашнего задания Lite")
subtitle.style = styles["Subtitle"]
subtitle.runs[0].font.color.rgb = RGBColor(0, 0, 0)
subtitle.paragraph_format.space_after = Pt(7)

intro = doc.add_paragraph(
    "Документ показывает, как голосовой помощник понимает просьбу «Можно завтра после шести?», "
    "проверяет учебное расписание и отвечает голосом. Помощник сообщает только результат проверки: "
    "он не оформляет запись и не придумывает данные."
)
intro.paragraph_format.space_after = Pt(7)

add_heading(doc, "1 Путь одной реплики")

flow = doc.add_paragraph()
flow.alignment = WD_ALIGN_PARAGRAPH.CENTER
flow.paragraph_format.space_after = Pt(6)
run = flow.add_run("Микрофон  →  STT  →  AI агент  →  Расписание  →  TTS  →  Динамик")
run.bold = True
run.font.size = Pt(11)
run.font.color.rgb = RGBColor(31, 78, 121)

headers = ("Этап", "Что получает", "Что передаёт дальше")
rows = (
    ("1  Микрофон", "Голос пользователя", "Цифровой аудиопоток"),
    ("2  STT", "Аудиопоток", "Текст «Можно завтра после шести?»"),
    ("3  AI агент", "Распознанный текст", "Запрос проверить завтра после 18:00"),
    ("4  Расписание", "Параметры даты и времени", "18:30 свободно; 19:00 занято"),
    ("5  TTS", "Проверенный текст ответа", "Синтезированный аудиопоток"),
    ("6  Динамик", "Аудиопоток ответа", "Голосовой ответ пользователю"),
)
table = doc.add_table(rows=1, cols=3)
table.alignment = WD_TABLE_ALIGNMENT.CENTER
table.autofit = False
widths = (Inches(1.45), Inches(2.35), Inches(3.15))
for i, header in enumerate(headers):
    cell = table.rows[0].cells[i]
    cell.width = widths[i]
    set_cell_shading(cell, "1F4E79")
    set_cell_margins(cell)
    set_cell_borders(cell)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(header)
    r.bold = True
    r.font.color.rgb = RGBColor(255, 255, 255)
    r.font.size = Pt(9.5)
set_repeat_table_header(table.rows[0])

for row_idx, values in enumerate(rows, start=1):
    cells = table.add_row().cells
    for i, value in enumerate(values):
        cells[i].width = widths[i]
        set_cell_margins(cells[i])
        set_cell_borders(cells[i])
        cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if row_idx % 2 == 0:
            set_cell_shading(cells[i], "EEF4F8")
        p = cells[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(value)
        r.font.size = Pt(9.3)
        if i == 0:
            r.bold = True

doc.add_paragraph(
    "AI агент формирует окончательный ответ только после того, как расписание вернуло результат проверки."
)

add_heading(doc, "2 Реплики помощника")
p = doc.add_paragraph(style="List Bullet")
p.add_run("До проверки  ").bold = True
p.add_run("«Сейчас проверю учебное расписание на завтра после 18:00». ")
p.add_run("Фраза подтверждает действие, но не обещает свободное время.").italic = True

p = doc.add_paragraph(style="List Bullet")
p.add_run("После проверки  ").bold = True
p.add_run("«Проверил: завтра в 18:30 свободно, а в 19:00 занято. Вам подходит 18:30?» ")
p.add_run("Помощник предлагает вариант, но не утверждает, что запись оформлена.").italic = True

doc.add_page_break()

add_heading(doc, "3 Три понятия")
definitions = (
    ("STT", "распознавание речи", "Преобразует голосовой аудиопоток в текст, который может обработать AI агент."),
    ("TTS", "генерация речи", "Преобразует готовый текст ответа в аудио, чтобы пользователь услышал помощника."),
    ("Streaming", "потоковая передача данных", "Передаёт данные небольшими частями по мере готовности, без ожидания всего результата."),
)
for term, label, explanation in definitions:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.add_run(f"{term}  ").bold = True
    p.add_run(f"{label}. ").italic = True
    p.add_run(explanation)

p = doc.add_paragraph()
p.paragraph_format.left_indent = Inches(0.22)
p.paragraph_format.space_before = Pt(1)
p.paragraph_format.space_after = Pt(8)
p.add_run("Пример streaming  ").bold = True
p.add_run(
    "помощник начинает произносить начало ответа, пока следующие фрагменты аудио ещё создаются. "
    "Из-за этого пользователь слышит ответ раньше."
)

add_heading(doc, "4 Изменение просьбы во время ответа")
doc.add_paragraph(
    "Если пользователь перебивает помощника словами «Нет, лучше послезавтра», новая реплика заменяет "
    "предыдущую просьбу о завтрашнем времени."
)

steps = (
    ("Текущий голосовой ответ", "Воспроизведение нужно сразу остановить, чтобы помощник не продолжал говорить о завтрашнем дне."),
    ("Новая просьба", "Помощник должен проверить расписание на послезавтра. Старый запрос больше не определяет ответ."),
    ("Ответ при отсутствии данных", "«На послезавтра в расписании нет данных. Я не могу подтвердить свободное время. Попробовать проверить другой день?»"),
)
table2 = doc.add_table(rows=1, cols=2)
table2.alignment = WD_TABLE_ALIGNMENT.CENTER
table2.autofit = False
widths2 = (Inches(1.85), Inches(5.10))
for i, header in enumerate(("Что меняется", "Поведение помощника")):
    cell = table2.rows[0].cells[i]
    cell.width = widths2[i]
    set_cell_shading(cell, "1F4E79")
    set_cell_margins(cell, top=130, bottom=130)
    set_cell_borders(cell)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(header)
    r.bold = True
    r.font.color.rgb = RGBColor(255, 255, 255)
    r.font.size = Pt(9.5)

for row_idx, values in enumerate(steps, start=1):
    cells = table2.add_row().cells
    for i, value in enumerate(values):
        cells[i].width = widths2[i]
        set_cell_margins(cells[i], top=130, bottom=130)
        set_cell_borders(cells[i])
        cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if row_idx % 2 == 0:
            set_cell_shading(cells[i], "EEF4F8")
        p = cells[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(value)
        r.font.size = Pt(9.5)
        if i == 0:
            r.bold = True

closing = doc.add_paragraph()
closing.paragraph_format.space_before = Pt(8)
closing.add_run("Итог  ").bold = True
closing.add_run(
    "помощник опирается только на результат расписания, корректно меняет запрос после перебивания "
    "и не сообщает о записи, которой не было."
)

footer = section.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
footer_run = footer.add_run("Домашнее задание Lite")
footer_run.font.size = Pt(8.5)
footer_run.font.color.rgb = RGBColor(110, 110, 110)

doc.save(OUTPUT)
print(OUTPUT)
