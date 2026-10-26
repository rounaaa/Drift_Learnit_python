from io import BytesIO
from pathlib import Path

from django.utils import timezone


def render_summary_pdf(summary):
    from arabic_reshaper import reshape
    from bidi.algorithm import get_display
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    language = summary.language
    pdf._doc.Catalog.Lang = language
    font_name = "Helvetica"
    if language.startswith("ar"):
        font_path = Path(__file__).resolve().parent / "fonts" / "Amiri-Regular.ttf"
        if not font_path.is_file():
            raise OSError("La police Amiri embarquée est introuvable.")
        font_name = "Amiri"
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    width, height = A4
    margin = 48
    y = height - margin
    labels = {
        "ar": {
            "date": "التاريخ",
            "summary": "الملخص",
            "key_points": "النقاط الرئيسية",
            "chapters": "الفصول",
            "unavailable": "الملخص غير متاح.",
        },
        "en": {
            "date": "Date",
            "summary": "Summary",
            "key_points": "Key points",
            "chapters": "Chapters",
            "unavailable": "Summary unavailable.",
        },
    }.get(
        language.split("-", 1)[0],
        {
            "date": "Date",
            "summary": "Résumé",
            "key_points": "Points clés",
            "chapters": "Chapitres",
            "unavailable": "Résumé indisponible.",
        },
    )

    def draw_block(text, size=11, gap=5, bold=False):
        nonlocal y
        font = "Helvetica-Bold" if bold and font_name == "Helvetica" else font_name
        pdf.setFont(font, size)
        for line in simpleSplit(str(text), font, size, width - 2 * margin):
            if y < margin + size:
                pdf.showPage()
                y = height - margin
                pdf.setFont(font, size)
            if language.startswith("ar"):
                pdf.drawRightString(width - margin, y, get_display(reshape(line)))
            else:
                pdf.drawString(margin, y, line)
            y -= size + gap
        y -= gap

    draw_block(summary.video.title, size=18, gap=9, bold=True)
    draw_block(
        f"{labels['date']} : {timezone.localtime(summary.updated_at).date().isoformat()}"
    )
    draw_block(labels["summary"], size=14, gap=7, bold=True)
    draw_block(summary.summary or labels["unavailable"])
    draw_block(labels["key_points"], size=14, gap=7, bold=True)
    for point in summary.key_points:
        draw_block(f"• {point}")
    draw_block(labels["chapters"], size=14, gap=7, bold=True)
    for chapter in summary.chapters:
        start = float(chapter.get("start", 0))
        minutes, seconds = divmod(int(start), 60)
        draw_block(f"{minutes:02}:{seconds:02} — {chapter.get('title', '')}")
    pdf.save()
    return buffer.getvalue()
