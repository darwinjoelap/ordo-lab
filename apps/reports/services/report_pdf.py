"""PDF del informe con ReportLab (Fase 11, ADR-027).

Se genera siempre desde el contenido congelado del `Report` (nunca desde la base viva).
Carta, con cabecera en cada página (logo, laboratorio, paciente, orden, versión), exámenes
por sección con **sus observaciones debajo de cada uno**, firmas de quienes validaron y
pie con el texto legal, el QR de verificación, la huella y «Página X de Y».
"""
from __future__ import annotations

import datetime
import io
from xml.sax.saxutils import escape

from django.contrib.staticfiles import finders
from django.core.files.storage import default_storage
from django.utils import timezone
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from apps.tenants.services.platform import report_brand

PAGE_W, PAGE_H = letter
MARGIN = 14 * mm
HEADER_H = 64 * mm   # desde el borde superior hasta el inicio del cuerpo
FOOTER_H = 22 * mm   # pie: enlace de verificación y firma de la plataforma
SIGN_H = 27 * mm     # franja de cada página: QR a la izquierda, firmas a la derecha
QR_SIZE = 23 * mm
BODY_BOTTOM = FOOTER_H + SIGN_H
BODY_W = PAGE_W - 2 * MARGIN
COLS = [BODY_W * 0.38, BODY_W * 0.19, BODY_W * 0.13, BODY_W * 0.30]

INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d1d5db")
SOFT = colors.HexColor("#f3f4f6")
CRITICAL = colors.HexColor("#b00020")
WARN_BG = colors.HexColor("#fff4d6")
WARN_INK = colors.HexColor("#8a5a00")

HIGH, LOW = "▲", "▼"  # ▲ ▼ (se dibujan con ZapfDingbats: 's' y 't')

_base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=10.5,
                       textColor=INK)
ST = {
    "cell": _base,
    "cell_b": ParagraphStyle("cell_b", parent=_base, fontName="Helvetica-Bold"),
    "ref": ParagraphStyle("ref", parent=_base, fontSize=7.8, leading=9.5, textColor=MUTED),
    "group": ParagraphStyle("group", parent=_base, fontName="Helvetica-BoldOblique",
                            fontSize=8, textColor=MUTED),
    "test": ParagraphStyle("test", parent=_base, fontName="Helvetica-Bold", fontSize=9.5,
                           leading=12),
    "obs": ParagraphStyle("obs", parent=_base, fontSize=8, leading=10, leftIndent=6,
                          textColor=INK),
    "interp": ParagraphStyle("interp", parent=_base, fontName="Helvetica-Oblique",
                             fontSize=7.8, leading=9.5, leftIndent=10, textColor=MUTED),
    "small": ParagraphStyle("small", parent=_base, fontSize=7.2, leading=9, textColor=MUTED),
    "sign": ParagraphStyle("sign", parent=_base, fontSize=8, leading=10, alignment=TA_CENTER),
    "sign_b": ParagraphStyle("sign_b", parent=_base, fontName="Helvetica-Bold", fontSize=8.5,
                             leading=10.5, alignment=TA_CENTER),
    "warn": ParagraphStyle("warn", parent=_base, textColor=WARN_INK, fontSize=8.3),
    "footer": ParagraphStyle("footer", parent=_base, fontSize=7, leading=8.6,
                             textColor=MUTED),
}


def fmt_dt(value: str, *, with_time: bool = True) -> str:
    """ISO → 'dd/mm/aaaa hh:mm AM' (hora de 12 h, regla del proyecto)."""
    if not value:
        return ""
    moment = datetime.datetime.fromisoformat(value)
    return moment.strftime("%d/%m/%Y %I:%M %p" if with_time else "%d/%m/%Y")


def _toma(order: dict) -> str:
    """La hora de toma: una sola, o el rango cuando las muestras no se tomaron a la vez.

    `collected_until` sólo viene cuando difiere de la primera. Imprimir sólo la primera
    haría creer que toda la orden se tomó entonces, y con un envase de orina recogido el
    día anterior eso son treinta horas de diferencia sobre una hematología.
    """
    desde = fmt_dt(order.get("collected_at", ""))
    if not desde:
        return "—"
    hasta = fmt_dt(order.get("collected_until", ""))
    return f"{desde} a {hasta}" if hasta else desde


def _p(text: str, style: str = "cell") -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), ST[style])


def _image_bytes(path: str) -> bytes | None:
    """Imagen guardada (logo, firma, sello). Si falta el archivo, se omite sin romper."""
    if not path:
        return None
    try:
        with default_storage.open(path, "rb") as handle:
            data = handle.read()
        ImageReader(io.BytesIO(data)).getSize()  # valida que sea una imagen
        return data
    except (OSError, ValueError):
        return None


def _image(path: str) -> ImageReader | None:
    data = _image_bytes(path)
    return ImageReader(io.BytesIO(data)) if data else None


def _fit(reader: ImageReader, max_w: float, max_h: float) -> tuple[float, float]:
    width, height = reader.getSize()
    scale = min(max_w / width, max_h / height)
    return width * scale, height * scale


def _brand_icon() -> str:
    """Ruta del ícono de Ordo Lab (del tamaño de la letra del pie)."""
    return finders.find("img/brand/ordolab-mark-96.png") or ""


def _hex(value: str, fallback: str = "#1B5FA8") -> colors.Color:
    try:
        return colors.HexColor(value or fallback)
    except ValueError:
        return colors.HexColor(fallback)


# Marcas ---------------------------------------------------------------------------------
def _mark(flag: str) -> str:
    dingbat = '<font name="ZapfDingbats" size="6">{}</font>'
    if flag in ("ALTO", "CRITICO_ALTO"):
        mark = dingbat.format(HIGH)
    elif flag in ("BAJO", "CRITICO_BAJO"):
        mark = dingbat.format(LOW)
    elif flag == "ANORMAL":
        mark = "*"
    else:
        return ""
    if flag.startswith("CRITICO"):
        mark += " C"
    return "&nbsp;" + mark


def _value_cell(row: dict) -> Paragraph:
    text = escape(row["value"]).replace("\n", "<br/>")
    flag = row.get("flag") or ""
    if not flag or flag == "NORMAL":
        return Paragraph(text, ST["cell"])
    color = ' color="#b00020"' if flag.startswith("CRITICO") else ""
    return Paragraph(f"<font{color}><b>{text}</b>{_mark(flag)}</font>", ST["cell"])


# Cuerpo ---------------------------------------------------------------------------------
def _column_header() -> Table:
    labels = ["Parámetro", "Resultado", "Unidad", "Valores de referencia"]
    table = Table([[_p(label, "small") for label in labels]], colWidths=COLS)
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def _section_bar(name: str, color) -> Table:
    bar = Table([[Paragraph(f"<b>{escape(name)}</b>", ParagraphStyle(
        "bar", parent=_base, textColor=colors.white, fontSize=9.5))]], colWidths=[BODY_W])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return bar


def _test_block(test: dict) -> list:
    method = ""
    if test.get("method"):
        method = f'<br/><font size="7" color="#6b7280">Método: {escape(test["method"])}</font>'
    rows = test["rows"]
    # Examen de un solo parámetro (glicemia, HDL, HIV…): una sola línea con el nombre del
    # examen, sin repetirlo como título.
    single = len(rows) == 1 and not rows[0].get("group")
    data, style = [], [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if not single:
        data.append([Paragraph(f"<b>{escape(test['name'])}</b>{method}", ST["test"]),
                     "", "", ""])
        style.append(("SPAN", (0, 0), (-1, 0)))
    group = None
    for row in rows:
        if row.get("group") and row["group"] != group:
            group = row["group"]
            data.append([_p(group, "group"), "", "", ""])
            style.append(("SPAN", (0, len(data) - 1), (-1, len(data) - 1)))
        indent = "&nbsp;&nbsp;&nbsp;" if group else ""
        if single:
            name = Paragraph(f"<b>{escape(test['name'])}</b>{method}", ST["cell"])
        else:
            name = Paragraph(indent + escape(row["name"]), ST["cell"])
        index = len(data)
        if len(row["value"]) > 38 or "\n" in row["value"]:  # narrativo: ocupa el ancho
            data.append([name, _value_cell(row), "", ""])
            style.append(("SPAN", (1, index), (-1, index)))
        else:
            data.append([name, _value_cell(row), _p(row.get("unit", "")),
                         _p(row.get("reference", ""), "ref")])
        if not single and index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), SOFT))
        if row.get("interpretation"):
            data.append([_p(f"Interpretación: {row['interpretation']}", "interp"), "", "", ""])
            style.append(("SPAN", (0, len(data) - 1), (-1, len(data) - 1)))
    table = Table(data, colWidths=COLS, repeatRows=0 if single else 1)
    table.setStyle(TableStyle(style))
    parts: list = [table]
    if test.get("observations"):
        obs = escape(test["observations"]).replace("\n", "<br/>")
        parts.append(Spacer(1, 1.5 * mm))
        parts.append(Paragraph(f"<b>Observaciones:</b> {obs}", ST["obs"]))
    parts.append(Spacer(1, 3 * mm))
    # Un examen corto no se parte entre páginas; uno largo sí (repite su título).
    return [KeepTogether(parts)] if len(data) <= 14 else parts


def _legend(payload: dict) -> Paragraph | None:
    flags = {row.get("flag") for s in payload["sections"] for t in s["tests"]
             for row in t["rows"]}
    parts = []
    if flags & {"ALTO", "BAJO", "CRITICO_ALTO", "CRITICO_BAJO"}:
        parts.append(f'<font name="ZapfDingbats" size="6">{HIGH}</font> sobre / '
                     f'<font name="ZapfDingbats" size="6">{LOW}</font> bajo el valor de '
                     'referencia')
    if flags & {"CRITICO_ALTO", "CRITICO_BAJO"}:
        parts.append("C valor crítico (notificado)")
    if "ANORMAL" in flags:
        parts.append("* resultado anormal")
    return Paragraph(" · ".join(parts), ST["small"]) if parts else None


def _story(payload: dict) -> list:
    color = _hex(payload["lab"].get("color", ""))
    story: list = []
    if payload.get("kind") == "PARCIAL" and payload.get("pending_tests"):
        box = Table([[Paragraph(
            "<b>INFORME PARCIAL.</b> Pendientes por validar: "
            + escape(", ".join(payload["pending_tests"])) + ".", ST["warn"])]],
            colWidths=[BODY_W])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [box, Spacer(1, 3 * mm)]
    if payload.get("amended_tests"):
        # Fase 15: el médico que recibe esta versión debe saber que corrige a la
        # anterior. El motivo de la rectificación es interno y no se imprime.
        box = Table([[Paragraph(
            "<b>INFORME RECTIFICADO.</b> Corrige a la versión anterior en: "
            + escape(", ".join(payload["amended_tests"])) + ".", ST["warn"])]],
            colWidths=[BODY_W])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [box, Spacer(1, 3 * mm)]
    if payload.get("external_samples"):
        # El médico necesita saber que la muestra no se tomó aquí y a qué hora dicen que
        # se tomó: una glicemia de hace cinco horas no se interpreta igual que una recién
        # tomada. Se dice "hora declarada" a propósito — el laboratorio no la presenció.
        lineas = []
        for muestra in payload["external_samples"]:
            detalle = f" ({muestra['detail']})" if muestra.get("detail") else ""
            hora = fmt_dt(muestra.get("collected_at", ""))
            lineas.append(
                f"{escape(muestra['container'])}: {escape(muestra['origin'])}"
                f"{escape(detalle)}"
                + (f", hora declarada {escape(hora)}" if hora else "")
            )
        box = Table([[Paragraph(
            "<b>MUESTRA NO TOMADA EN EL LABORATORIO.</b> " + "; ".join(lineas) + ".",
            ST["warn"])]], colWidths=[BODY_W])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [box, Spacer(1, 3 * mm)]
    for index, section in enumerate(payload["sections"]):
        if index and section.get("page_break"):
            story.append(PageBreak())
        head = [_section_bar(section["name"], color), _column_header(), Spacer(1, 1 * mm)]
        for number, test in enumerate(section["tests"]):
            block = _test_block(test)
            if number == 0:
                # La barra de la sección nunca queda sola al pie de una página.
                if isinstance(block[0], KeepTogether):
                    block = [KeepTogether(head + list(block[0]._content))] + block[1:]
                else:
                    # Examen largo: se parte entre páginas; basta con que la barra tenga
                    # debajo espacio para varias filas.
                    block = [CondPageBreak(45 * mm)] + head + block
            story += block
        story.append(Spacer(1, 2 * mm))
    legend = _legend(payload)
    if legend is not None:
        story.append(legend)
    if payload["lab"].get("disclaimer"):
        story += [Spacer(1, 2 * mm), _p(payload["lab"]["disclaimer"], "small")]
    return story


# Cabecera, pie y numeración ----------------------------------------------------------------
def _fit_font(canvas, text: str, font: str, width: float, size: float = 8.5) -> float:
    """Achica la letra (hasta 6,5 pt) para que un dato largo quepa en su casilla."""
    while size > 6.5 and canvas.stringWidth(text, font, size) > width:
        size -= 0.25
    return size


class _NumberedCanvas(pdf_canvas.Canvas):
    """«Página X de Y»: guarda cada página y numera al final."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages: list[dict] = []

    def showPage(self):  # noqa: N802 (API de ReportLab)
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7)
            self.setFillColor(MUTED)
            self.drawRightString(PAGE_W - MARGIN, 5.8 * mm,
                                 f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


class _Decor:
    def __init__(self, report, verify_url: str, brand: dict):
        self.report = report
        self.brand = brand
        self.payload = report.payload
        self.verify_url = verify_url
        self.logo = _image(self.payload["lab"].get("logo", ""))
        # Firmas y sellos de quienes validaron: se leen una vez y van en cada página.
        self.signers = [
            (signer, _image(signer.get("signature", "")), _image(signer.get("stamp", "")))
            for signer in self.payload.get("signers", [])[:3]
        ]
        self.color = _hex(self.payload["lab"].get("color", ""))

    def __call__(self, canvas, doc):
        canvas.saveState()
        self._watermark(canvas)
        self._header(canvas)
        self._signatures(canvas)
        self._footer(canvas)
        canvas.restoreState()

    def _watermark(self, canvas):
        text = ""
        if not self.report.is_current:
            text = "REEMPLAZADO"
        elif self.payload.get("amended_tests"):
            text = "RECTIFICADO"
        # Un informe parcial **no** lleva marca de agua: es un informe válido de lo que ya
        # se validó, no un documento del que haya que desconfiar. Que es parcial lo dicen
        # la insignia de la cabecera y el recuadro que lista lo pendiente. Reemplazado y
        # rectificado sí la llevan: ahí la advertencia es justamente el punto.
        if not text:
            return
        canvas.saveState()
        canvas.setFillColor(colors.Color(0.55, 0.55, 0.55, alpha=0.12))
        canvas.setFont("Helvetica-Bold", 78)
        canvas.translate(PAGE_W / 2, PAGE_H / 2 - 20 * mm)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, text)
        canvas.restoreState()

    def _header(self, canvas):
        lab, patient, order = self.payload["lab"], self.payload["patient"], self.payload["order"]
        top = PAGE_H - 12 * mm
        x = MARGIN
        if self.logo is not None:
            w, h = _fit(self.logo, 30 * mm, 18 * mm)
            canvas.drawImage(self.logo, MARGIN, top - h, width=w, height=h, mask="auto")
            x = MARGIN + w + 4 * mm
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 12.5)
        canvas.drawString(x, top - 4.5 * mm, lab.get("legal_name") or lab.get("name", ""))
        canvas.setFont("Helvetica", 7.8)
        canvas.setFillColor(MUTED)
        lines = [
            " · ".join(v for v in (lab.get("name") if lab.get("legal_name") else "",
                                   f"RIF {lab['rif']}" if lab.get("rif") else "") if v),
            lab.get("address", ""),
            lab.get("phone", ""),
        ]
        y = top - 9 * mm
        for line in (line for line in lines if line):
            canvas.drawString(x, y, line[:95])
            y -= 3.6 * mm

        right = PAGE_W - MARGIN
        canvas.setFillColor(self.color)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawRightString(right, top - 4.5 * mm, "INFORME DE RESULTADOS")
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(right, top - 9 * mm, f"Orden N° {order['number']}")
        version = (f"Versión {self.report.version} · "
                   f"{'Parcial' if self.report.is_partial else 'Final'}")
        canvas.drawRightString(right, top - 12.6 * mm, version)
        # Contacto del laboratorio bajo el número (Instagram y correo).
        canvas.setFont("Helvetica", 7.8)
        canvas.setFillColor(MUTED)
        y = top - 16.2 * mm
        for line in (f"@{lab['instagram'].lstrip('@')}" if lab.get("instagram") else "",
                     lab.get("email", "")):
            if line:
                canvas.drawRightString(right, y, line)
                y -= 3.4 * mm
        badge = ("RECTIFICADO" if self.payload.get("amended_tests")
                 else "PARCIAL" if self.report.is_partial else "")
        if badge:
            width = 18 * mm if badge == "PARCIAL" else 26 * mm
            badge_x = (right - canvas.stringWidth(version, "Helvetica", 8) - width
                       - 4 * mm)
            canvas.setFillColor(WARN_BG)
            canvas.roundRect(badge_x, top - 13.6 * mm, width, 4.6 * mm, 1.2 * mm,
                             stroke=0, fill=1)
            canvas.setFillColor(WARN_INK)
            canvas.setFont("Helvetica-Bold", 7.8)
            canvas.drawCentredString(badge_x + width / 2, top - 12.3 * mm, badge)

        rule_y = PAGE_H - 34 * mm
        canvas.setStrokeColor(self.color)
        canvas.setLineWidth(1.2)
        canvas.line(MARGIN, rule_y, PAGE_W - MARGIN, rule_y)

        box_top, box_h = rule_y - 2.5 * mm, 22 * mm
        canvas.setFillColor(SOFT)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.roundRect(MARGIN, box_top - box_h, BODY_W, box_h, 1.5 * mm, stroke=1, fill=1)
        emitted = self.report.created_at
        cells = [
            [("Paciente", patient["name"]), ("C.I.", patient.get("document") or "—"),
             ("Historia", patient.get("code", ""))],
            [("Edad", patient.get("age", "")), ("Sexo", patient.get("sex", "")),
             ("Registro", fmt_dt(order.get("ordered_at", "")))],
            [("Médico", order.get("requested_by") or "—"),
             ("Toma", _toma(order)),
             ("Emitido", timezone.localtime(emitted).strftime("%d/%m/%Y %I:%M %p")
              if emitted else "")],
        ]
        col_w = [BODY_W * 0.42, BODY_W * 0.27, BODY_W * 0.31]
        y = box_top - 5.2 * mm
        for row in cells:
            cx = MARGIN + 3 * mm
            for (label, value), width in zip(row, col_w, strict=True):
                canvas.setFont("Helvetica", 7)
                canvas.setFillColor(MUTED)
                canvas.drawString(cx, y, label.upper())
                font = "Helvetica-Bold" if label == "Paciente" else "Helvetica"
                offset = 15 * mm
                size = _fit_font(canvas, str(value), font, width - offset - 2 * mm)
                canvas.setFont(font, size)
                canvas.setFillColor(INK)
                canvas.drawString(cx + offset, y, str(value))
                cx += width
            y -= 6.2 * mm
        if order.get("condition"):
            canvas.setFont("Helvetica-Oblique", 7)
            canvas.setFillColor(MUTED)
            canvas.drawRightString(PAGE_W - MARGIN - 3 * mm, box_top - box_h + 1.6 * mm,
                                   f"Condición: {order['condition']}")

    def _signatures(self, canvas):
        """Franja inferior de **todas** las páginas: QR de verificación a la izquierda y
        firma y sello de cada bioanalista que validó a la derecha (hasta 3)."""
        self._qr(canvas)
        if not self.signers:
            return
        right = PAGE_W - MARGIN
        free = BODY_W - QR_SIZE - 45 * mm  # lo que queda a la derecha del QR y su texto
        cell_w = min(58 * mm, free / len(self.signers))
        line_y = FOOTER_H + 9 * mm   # línea de firma
        for index, (signer, sign, stamp) in enumerate(self.signers):
            x1 = right - (index + 1) * cell_w
            center = x1 + cell_w / 2
            if stamp is not None:  # sello a la derecha, puede montarse sobre la firma
                w, h = _fit(stamp, min(17 * mm, cell_w * 0.32), 17 * mm)
                canvas.drawImage(stamp, x1 + cell_w - w - 1 * mm, line_y - 2 * mm,
                                 width=w, height=h, mask="auto")
            if sign is not None:
                w, h = _fit(sign, cell_w * 0.62, 13 * mm)
                canvas.drawImage(sign, center - w / 2 - cell_w * 0.1, line_y + 0.5 * mm,
                                 width=w, height=h, mask="auto")
            canvas.setStrokeColor(INK)
            canvas.setLineWidth(0.5)
            canvas.line(x1 + 4 * mm, line_y, x1 + cell_w - 4 * mm, line_y)
            canvas.setFillColor(INK)
            canvas.setFont("Helvetica-Bold", 7.5)
            canvas.drawCentredString(center, line_y - 3.2 * mm, signer["name"][:40])
            detail = " · ".join(v for v in (signer.get("title", ""),
                                            signer.get("license", "")) if v)
            if detail:
                canvas.setFont("Helvetica", 6.6)
                canvas.setFillColor(MUTED)
                size = _fit_font(canvas, detail, "Helvetica", cell_w - 4 * mm, 6.6)
                canvas.setFont("Helvetica", size)
                canvas.drawCentredString(center, line_y - 6.2 * mm, detail)

    def _qr(self, canvas):
        widget = QrCodeWidget(self.verify_url, barLevel="M")
        x1, y1, x2, y2 = widget.getBounds()
        drawing = Drawing(QR_SIZE, QR_SIZE, transform=[QR_SIZE / (x2 - x1), 0, 0,
                                                       QR_SIZE / (y2 - y1), 0, 0])
        drawing.add(widget)
        bottom = FOOTER_H + 2 * mm
        renderPDF.draw(drawing, canvas, MARGIN - 1.5 * mm, bottom)
        note = Paragraph(
            "<b>Verifique este informe</b><br/>Escanee el código con la cámara del "
            f"teléfono.<br/>Huella SHA-256:<br/>{self.report.short_hash}…",
            ST["footer"])
        _, height = note.wrap(42 * mm, QR_SIZE)
        note.drawOn(canvas, MARGIN + QR_SIZE + 1 * mm, bottom + (QR_SIZE - height) / 2)

    def _footer(self, canvas):
        lab = self.payload["lab"]
        rule_y = FOOTER_H - 1 * mm
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, rule_y, PAGE_W - MARGIN, rule_y)
        parts = []
        if lab.get("footer"):  # texto propio del laboratorio, si lo configuró
            parts.append(escape(lab["footer"]).replace("\n", "<br/>"))
        parts.append(f"También puede verificarlo en {escape(self.verify_url)}")
        para = Paragraph("<br/>".join(parts), ST["footer"])
        _, height = para.wrap(BODY_W, FOOTER_H)
        para.drawOn(canvas, MARGIN, rule_y - 1.8 * mm - height)
        self._brand(canvas)

    def _brand(self, canvas):
        """Firma de la plataforma: ícono de Ordo Lab y su texto, abajo a la izquierda."""
        if not (self.brand.get("enabled") and self.brand.get("text")):
            return
        text = self.brand["text"]
        if self.brand.get("contact"):
            text += " · " + self.brand["contact"]
        x, y = MARGIN, 5.8 * mm
        icon = _brand_icon()
        if icon:
            size = 5.2 * mm
            canvas.drawImage(ImageReader(icon), x, y - 1.3 * mm, width=size, height=size,
                             mask="auto")
            x += size + 1.6 * mm
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.HexColor("#1B5FA8"))
        head, _, tail = text.partition(" · ")
        canvas.drawString(x, y, head)
        if tail:
            x += canvas.stringWidth(head + " ", "Helvetica-Bold", 8)
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(x, y, "· " + tail)


def render_report_pdf(report, *, verify_url: str) -> bytes:
    buffer = io.BytesIO()
    payload = report.payload
    doc = BaseDocTemplate(
        buffer, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=HEADER_H, bottomMargin=BODY_BOTTOM,
        title=f"Informe {payload['order']['number']} v{report.version}",
        author=payload["lab"].get("legal_name") or payload["lab"].get("name", ""),
        subject="Informe de resultados de laboratorio",
    )
    frame = Frame(MARGIN, BODY_BOTTOM, BODY_W, PAGE_H - HEADER_H - BODY_BOTTOM, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="report", frames=[frame],
                                       onPage=_Decor(report, verify_url,
                                                                    report_brand()))])
    doc.build(_story(payload), canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
