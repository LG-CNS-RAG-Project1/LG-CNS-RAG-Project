"""기존 보고서 Markdown을 한글 글꼴이 포함된 A4 PDF로 내보낸다."""

from io import BytesIO
from pathlib import Path
import re
import gzip
from xml.sax.saxutils import escape


def make_pdf(title: str, markdown: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    name = "IdeaLensKorean"
    if name not in pdfmetrics.getRegisteredFontNames():
        font_path = (
            Path(__file__).with_name("assets") / "fonts" / "NanumGothic-Regular.ttf.gz"
        )
        pdfmetrics.registerFont(
            TTFont(name, BytesIO(gzip.decompress(font_path.read_bytes())))
        )
    normal = ParagraphStyle(
        "body",
        fontName=name,
        fontSize=9,
        leading=15,
        wordWrap="CJK",
        alignment=TA_LEFT,
        spaceAfter=6,
    )
    heading = ParagraphStyle(
        "heading",
        parent=normal,
        fontSize=13,
        leading=20,
        spaceBefore=12,
        spaceAfter=9,
        textColor=colors.HexColor("#17594e"),
        keepWithNext=True,
    )
    title_style = ParagraphStyle(
        "title", parent=heading, fontSize=20, leading=28, spaceAfter=18
    )
    small = ParagraphStyle("cell", parent=normal, fontSize=8, leading=12, spaceAfter=0)

    def text(line):
        # Keep readable titles and URLs without executing or fetching report content.
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        return escape(line.replace("**", "").replace("`", ""))

    elements = [
        Paragraph("IDEALENS / RESEARCH REPORT", small),
        Spacer(1, 10),
        Paragraph(text(title), title_style),
    ]
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[:\- ]+", x or "-") for x in cells):
                    rows.append(cells)
                i += 1
            if rows:
                count = max(len(r) for r in rows)
                # Wide source tables are rendered as numbered records so cells stay legible.
                if count > 4:
                    for row in rows[1:]:
                        for key, value in zip(rows[0], row):
                            elements.append(Paragraph(text(f"{key}: {value}"), normal))
                        elements.append(Spacer(1, 8))
                else:
                    body = [
                        [Paragraph(text(c), small) for c in r + [""] * (count - len(r))]
                        for r in rows
                    ]
                    table = Table(
                        body,
                        colWidths=[487 / count] * count,
                        repeatRows=1,
                        splitInRow=1,
                        hAlign="LEFT",
                    )
                    table.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    colors.HexColor("#e9f0e9"),
                                ),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                (
                                    "GRID",
                                    (0, 0),
                                    (-1, -1),
                                    0.4,
                                    colors.HexColor("#cbd9d0"),
                                ),
                                ("TOPPADDING", (0, 0), (-1, -1), 7),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                            ]
                        )
                    )
                    elements.extend([table, Spacer(1, 10)])
            continue
        if line:
            if line.startswith("#"):
                elements.append(Paragraph(text(line.lstrip("#").strip()), heading))
            elif not line.startswith("```") and not re.fullmatch(r"[-*_]{3,}", line):
                elements.append(Paragraph(text(line), normal))
        i += 1

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(name, 8)
        canvas.setFillColor(colors.HexColor("#6b817b"))
        canvas.drawString(54, 28, "IdeaLens · 출처와 적용 조건을 확인해 주세요.")
        canvas.drawRightString(A4[0] - 54, 28, str(doc.page))
        canvas.restoreState()

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=44,
        bottomMargin=50,
        title=title,
        author="IdeaLens",
    )
    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
