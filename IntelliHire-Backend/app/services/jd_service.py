from io import BytesIO

from app.models.job_description import JobDescription

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    ListFlowable,
    ListItem,
)


def build_jd_pdf(jd: JobDescription) -> BytesIO:
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        name="TitleStyle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        spaceAfter=18,
        textColor=colors.HexColor("#111827"),
    )

    heading_style = ParagraphStyle(
        name="HeadingStyle",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=14,
        spaceAfter=8,
        textColor=colors.HexColor("#1F2937"),
    )

    normal_style = ParagraphStyle(
        name="NormalStyle",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#374151"),
    )

    table_label_style = ParagraphStyle(
        name="TableLabelStyle",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )

    table_value_style = ParagraphStyle(
        name="TableValueStyle",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#374151"),
    )

    story = []

    # Main title
    story.append(Paragraph("Job Description", title_style))

    # Basic Details
    basic_details = [
        ["Job Title", jd.title or "-"],
        # ["Req ID", jd.req_id or "-"],
        ["Grade / Level", jd.grade or "-"],
        ["Location", jd.location or "-"],
        ["Experience", jd.experience or "-"],
        # ["Line of Business", jd.lob or "-"],
        # ["Vertical", jd.vertical or "-"],
    ]

    table_data = []

    for label, value in basic_details:
        table_data.append(
            [
                Paragraph(f"<b>{label}</b>", table_label_style),
                Paragraph(str(value), table_value_style),
            ]
        )

    details_table = Table(
        table_data,
        colWidths=[2.0 * inch, 4.4 * inch],
    )

    details_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story.append(details_table)
    story.append(Spacer(1, 14))

    def add_paragraph_section(section_title: str, value: str | None):
        if not value:
            return

        story.append(Paragraph(section_title, heading_style))
        story.append(Paragraph(value, normal_style))
        story.append(Spacer(1, 6))

    def add_list_section(section_title: str, items):
        if not items:
            return

        story.append(Paragraph(section_title, heading_style))

        list_items = []

        for item in items:
            if isinstance(item, dict):
                text = "<br/>".join(
                    f"<b>{key}:</b> {value}"
                    for key, value in item.items()
                )
            else:
                text = str(item)

            list_items.append(
                ListItem(
                    Paragraph(text, normal_style),
                    bulletColor=colors.HexColor("#2563EB"),
                )
            )

        story.append(
            ListFlowable(
                list_items,
                bulletType="bullet",
                leftIndent=18,
            )
        )

        story.append(Spacer(1, 6))

    # Required sections only

    add_paragraph_section("Role Summary", jd.role_summary)

    add_list_section("Key Responsibilities", jd.responsibilities)

    add_list_section("Mandatory Skills", jd.mandatory_skills)

    add_list_section("Good-to-have Skills", jd.good_to_have_skills)

    add_list_section("Qualifications", jd.qualifications)

    doc.build(story)

    buffer.seek(0)
    return buffer