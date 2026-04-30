from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_invoice_number(payment):
    reference_date = payment.paid_at or payment.created_at or timezone.now()
    return f"FAC-{reference_date:%Y%m%d}-{payment.pk:05d}"


def build_invoice_filename(payment):
    return f"facture-{build_invoice_number(payment).lower()}.pdf"


def generate_invoice_pdf(payment):
    reservation = payment.reservation
    resource = reservation.resource
    billed_amount = Decimal(payment.amount)
    collected_amount = _decimal_from_value(
        payment.metadata.get('fedapay_collected_amount'),
        default=billed_amount,
    )
    invoice_number = build_invoice_number(payment)
    issue_date = timezone.localtime(payment.paid_at or payment.created_at or timezone.now())

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = _build_styles()
    story = []

    story.append(
        Table(
            [
                [
                    Paragraph(f"<b>{settings.INVOICE_COMPANY_NAME}</b>", styles["brand"]),
                    Paragraph("<b>FACTURE DE RESERVATION</b>", styles["invoice_title"]),
                ],
                [
                    Paragraph(
                        f"{settings.INVOICE_COMPANY_ADDRESS}<br/>{settings.INVOICE_COMPANY_PHONE}<br/>"
                        f"{settings.INVOICE_COMPANY_EMAIL}",
                        styles["company_info"],
                    ),
                    Paragraph(
                        f"No facture : <b>{invoice_number}</b><br/>"
                        f"Date d'emission : <b>{issue_date:%d/%m/%Y %H:%M}</b><br/>"
                        f"Statut : <b>Payee</b>",
                        styles["meta"],
                    ),
                ],
            ],
            colWidths=[95 * mm, 75 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )
    )
    story.append(Spacer(1, 10))

    story.append(
        Table(
            [
                [
                    Paragraph("<b>Client</b>", styles["section_title"]),
                    Paragraph("<b>Reservation</b>", styles["section_title"]),
                ],
                [
                    Paragraph(
                        f"{reservation.customer_name}<br/>{reservation.customer_email}<br/>"
                        f"{reservation.customer_phone or 'Telephone non renseigne'}",
                        styles["box_text"],
                    ),
                    Paragraph(
                        f"Ressource : <b>{resource.name}</b><br/>"
                        f"Debut : {timezone.localtime(reservation.start_datetime):%d/%m/%Y %H:%M}<br/>"
                        f"Fin : {timezone.localtime(reservation.end_datetime):%d/%m/%Y %H:%M}<br/>"
                        f"Participants : {reservation.attendees_count}",
                        styles["box_text"],
                    ),
                ],
            ],
            colWidths=[85 * mm, 85 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F6FA")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D7DFEA")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7DFEA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        )
    )
    story.append(Spacer(1, 14))

    story.append(
        Table(
            [
                [
                    Paragraph("<b>Description</b>", styles["table_head"]),
                    Paragraph("<b>Jours</b>", styles["table_head"]),
                    Paragraph("<b>Prix unitaire</b>", styles["table_head_right"]),
                    Paragraph("<b>Total</b>", styles["table_head_right"]),
                ],
                [
                    Paragraph(f"Reservation de {resource.name}", styles["table_cell"]),
                    Paragraph(str(reservation.billable_days), styles["table_cell"]),
                    Paragraph(_format_currency(resource.price), styles["table_cell_right"]),
                    Paragraph(_format_currency(billed_amount), styles["table_cell_right"]),
                ],
            ],
            colWidths=[82 * mm, 20 * mm, 34 * mm, 34 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123C73")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C8D2DE")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E0E6ED")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        )
    )
    story.append(Spacer(1, 14))

    summary_rows = [
        [Paragraph("Montant de la reservation", styles["summary_label"]), Paragraph(_format_currency(billed_amount), styles["summary_value"])],
        [Paragraph("Montant collecte via FedaPay", styles["summary_label"]), Paragraph(_format_currency(collected_amount), styles["summary_value"])],
        [Paragraph("Reference FedaPay", styles["summary_label"]), Paragraph(payment.metadata.get("fedapay_reference") or payment.provider_reference or "-", styles["summary_value"])],
    ]

    story.append(
        Table(
            summary_rows,
            colWidths=[95 * mm, 45 * mm],
            hAlign="RIGHT",
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D7DFEA")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E6ECF2")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F7F9FC")),
                    ("PADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        )
    )
    story.append(Spacer(1, 14))

    note = (
        "Merci pour votre confiance. Cette facture confirme l'enregistrement de votre reservation."
    )
    if collected_amount != billed_amount:
        note = (
            "Cette reservation a ete confirmee en mode test : FedaPay a encaisse un montant technique reduit, "
            "tandis que le montant contractuel de la reservation reste celui indique sur la facture."
        )
    story.append(Paragraph(note, styles["note"]))

    document.build(story)
    return buffer.getvalue()


def _build_styles():
    styles = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "brand",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#123C73"),
            alignment=TA_LEFT,
        ),
        "invoice_title": ParagraphStyle(
            "invoice_title",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#16243A"),
            alignment=TA_RIGHT,
        ),
        "company_info": ParagraphStyle(
            "company_info",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#4A5568"),
        ),
        "meta": ParagraphStyle(
            "meta",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#243B53"),
            alignment=TA_RIGHT,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.HexColor("#1F2937"),
        ),
        "box_text": ParagraphStyle(
            "box_text",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#344054"),
        ),
        "table_head": ParagraphStyle(
            "table_head",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            textColor=colors.white,
        ),
        "table_head_right": ParagraphStyle(
            "table_head_right",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            textColor=colors.white,
            alignment=TA_RIGHT,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#243B53"),
        ),
        "table_cell_right": ParagraphStyle(
            "table_cell_right",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=13,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#243B53"),
        ),
        "summary_label": ParagraphStyle(
            "summary_label",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#475467"),
        ),
        "summary_value": ParagraphStyle(
            "summary_value",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#111827"),
        ),
        "note": ParagraphStyle(
            "note",
            parent=styles["BodyText"],
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#475467"),
        ),
    }


def _format_currency(amount):
    amount = _decimal_from_value(amount, default=Decimal("0"))
    if amount == amount.to_integral_value():
        formatted = f"{int(amount):,}".replace(",", " ")
    else:
        formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} XOF"


def _decimal_from_value(value, default):
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
