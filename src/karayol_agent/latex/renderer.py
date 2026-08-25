from __future__ import annotations

import json
import html
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from karayol_agent.schemas import ArtifactResult, DraftPayload


class LatexRenderError(RuntimeError):
    pass


_LATEX_REPLACEMENTS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(value: str | None) -> str:
    if value is None or not value.strip():
        return "[DOLDURULACAK]"
    return "".join(_LATEX_REPLACEMENTS.get(character, character) for character in value)


class LatexRenderer:
    ALLOWED_TEMPLATE_IDS = {
        "ust_yazi_v1",
        "cevap_yazisi_v1",
        "bilgilendirme_yazisi_v1",
        "eksik_bilgi_talebi_v1",
    }

    def __init__(self, templates_dir: Path, output_dir: Path, timeout: int = 30) -> None:
        self.templates_dir = templates_dir
        self.output_dir = output_dir
        self.timeout = timeout
        self.environment = Environment(
            variable_start_string="<<",
            variable_end_string=">>",
            block_start_string="<%",
            block_end_string="%>",
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )

    def render(
        self, document_id: str, draft: DraftPayload, *, compile_pdf: bool = False
    ) -> ArtifactResult:
        if draft.template_id not in self.ALLOWED_TEMPLATE_IDS:
            raise LatexRenderError("Onaylanmamış LaTeX şablonu istendi.")
        template_directory = self.templates_dir / draft.template_id
        template_path = template_directory / "template.tex"
        schema_path = template_directory / "schema.json"
        if not template_path.exists() or not schema_path.exists():
            raise LatexRenderError(f"Şablon dosyaları bulunamadı: {draft.template_id}")

        self._validate_schema(draft, schema_path)
        destination_dir = self.output_dir / document_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        tex_path = destination_dir / "taslak.tex"
        template = self.environment.from_string(template_path.read_text(encoding="utf-8"))
        context = self._context(draft)
        tex_path.write_text(template.render(**context), encoding="utf-8")

        result = ArtifactResult(
            tex_path=str(tex_path.resolve()),
            tex_download_url=f"/api/v1/processes/{document_id}/artifacts/tex",
        )
        if not compile_pdf:
            result.warnings.append("PDF derleme istenmedi; yalnızca LaTeX taslağı üretildi.")
            return result

        compiler = self._find_compiler()
        if compiler is not None:
            compiled_result = self._compile(tex_path, compiler, result)
            if compiled_result.compiled:
                return compiled_result
            compiled_result.warnings.append(
                "LaTeX derlemesi kullanılamadı; taşınabilir PDF üretimine geçildi."
            )
        else:
            result.warnings.append(
                "LaTeX derleyicisi bulunamadı; taşınabilir PDF doğrudan üretildi."
            )
        return self._render_portable_pdf(tex_path, draft, result)

    @staticmethod
    def _validate_schema(draft: DraftPayload, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = draft.model_dump(mode="json")
        missing_keys = [key for key in schema.get("required", []) if key not in payload]
        if missing_keys:
            raise LatexRenderError(
                "Taslak şeması zorunlu alanları karşılamıyor: " + ", ".join(missing_keys)
            )

    @staticmethod
    def _context(draft: DraftPayload) -> dict[str, str]:
        paragraphs = "\n\n".join(
            escape_latex(paragraph) + r"\par" for paragraph in draft.paragraphs
        )
        return {
            "institution_name": escape_latex(draft.institution_name.value),
            "date": escape_latex(draft.date.value),
            "number": escape_latex(draft.number.value),
            "subject": escape_latex(draft.subject.value),
            "recipient": escape_latex(draft.recipient.value),
            "paragraphs": paragraphs,
            "signer": escape_latex(draft.signer.value),
            "signer_title": escape_latex(draft.signer_title.value),
            "interest": LatexRenderer._render_lines(draft.interest),
            "attachments": LatexRenderer._render_items(draft.attachments),
            "distribution": LatexRenderer._render_items(draft.distribution),
            "contact_information": LatexRenderer._render_lines(
                draft.contact_information
            ),
            "initials": LatexRenderer._render_lines(draft.initials),
            "electronic_signature": (
                escape_latex(draft.electronic_signature.value)
                if draft.electronic_signature.value
                else ""
            ),
        }

    @staticmethod
    def _render_items(values: list[str]) -> str:
        return "\n".join(rf"\item {escape_latex(value)}" for value in values)

    @staticmethod
    def _render_lines(values: list[str]) -> str:
        return r" \\ ".join(escape_latex(value) for value in values)

    @staticmethod
    def _render_portable_pdf(
        tex_path: Path,
        draft: DraftPayload,
        result: ArtifactResult,
    ) -> ArtifactResult:
        """Create the user-facing PDF without requiring a TeX installation."""

        try:
            import reportlab
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import (
                ListFlowable,
                ListItem,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:  # pragma: no cover - locked runtime dependency
            raise LatexRenderError(
                "PDF üretimi için ReportLab bağımlılığı bulunamadı."
            ) from exc

        regular_font = "KarayolVera"
        bold_font = "KarayolVeraBold"
        if regular_font not in pdfmetrics.getRegisteredFontNames():
            font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
            pdfmetrics.registerFont(TTFont(regular_font, font_dir / "Vera.ttf"))
            pdfmetrics.registerFont(TTFont(bold_font, font_dir / "VeraBd.ttf"))

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "OfficialTitle",
            parent=styles["Heading1"],
            fontName=bold_font,
            fontSize=13,
            leading=17,
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        )
        body_style = ParagraphStyle(
            "OfficialBody",
            parent=styles["BodyText"],
            fontName=regular_font,
            fontSize=10.5,
            leading=16,
            alignment=TA_JUSTIFY,
            spaceAfter=3 * mm,
        )
        label_style = ParagraphStyle(
            "OfficialLabel",
            parent=body_style,
            fontName=bold_font,
            spaceAfter=1.5 * mm,
        )
        signature_style = ParagraphStyle(
            "OfficialSignature",
            parent=body_style,
            alignment=TA_RIGHT,
        )

        def paragraph(value: str | None, style: ParagraphStyle = body_style) -> Paragraph:
            return Paragraph(html.escape(value or "[DOLDURULACAK]"), style)

        def markup_paragraph(value: str, style: ParagraphStyle) -> Paragraph:
            return Paragraph(value, style)

        template_titles = {
            "ust_yazi_v1": "ÜST YAZI TASLAĞI",
            "cevap_yazisi_v1": "CEVAP YAZISI TASLAĞI",
            "bilgilendirme_yazisi_v1": "BİLGİLENDİRME YAZISI TASLAĞI",
            "eksik_bilgi_talebi_v1": "EKSİK BİLGİ TALEBİ TASLAĞI",
        }
        story: list[object] = [
            paragraph(draft.institution_name.value, title_style),
            paragraph(template_titles[draft.template_id], title_style),
            Table(
                [[
                    paragraph(f"Sayı: {draft.number.value or '[DOLDURULACAK]'}"),
                    paragraph(f"Tarih: {draft.date.value or '[DOLDURULACAK]'}"),
                ]],
                colWidths=[85 * mm, 85 * mm],
                style=TableStyle([
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ]),
            ),
            paragraph(f"Konu: {draft.subject.value or '[DOLDURULACAK]'}"),
        ]
        if draft.interest:
            story.append(paragraph("İlgi: " + "; ".join(draft.interest)))
        story.extend([
            Spacer(1, 5 * mm),
            paragraph(draft.recipient.value, title_style),
            *[paragraph(value) for value in draft.paragraphs],
            Spacer(1, 5 * mm),
            markup_paragraph(
                "<b>" + html.escape(draft.signer.value or "[DOLDURULACAK]") + "</b><br/>"
                + html.escape(draft.signer_title.value or "[DOLDURULACAK]"),
                signature_style,
            ),
        ])

        def add_list(title: str, values: list[str]) -> None:
            if not values:
                return
            story.append(paragraph(title, label_style))
            story.append(
                ListFlowable(
                    [ListItem(paragraph(value), leftIndent=4 * mm) for value in values],
                    bulletType="bullet",
                    leftIndent=7 * mm,
                )
            )

        add_list("Ekler", draft.attachments)
        add_list("Dağıtım", draft.distribution)
        if draft.contact_information:
            story.append(
                paragraph("İletişim: " + " | ".join(draft.contact_information))
            )
        if draft.initials:
            story.append(paragraph("Paraf/Koordinasyon: " + " | ".join(draft.initials)))
        if draft.electronic_signature.value:
            story.append(
                paragraph("Elektronik imza: " + draft.electronic_signature.value)
            )

        pdf_path = tex_path.with_suffix(".pdf")
        document = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title=template_titles[draft.template_id],
            author=draft.institution_name.value or "Karayolu Evrak Ajanı",
        )
        document.build(story)
        result.pdf_path = str(pdf_path.resolve())
        result.pdf_download_url = (
            f"/api/v1/processes/{tex_path.parent.name}/artifacts/pdf"
        )
        result.compiled = True
        result.compiler = "reportlab"
        return result

    @staticmethod
    def _find_compiler() -> str | None:
        for compiler in ("xelatex", "tectonic", "pdflatex"):
            if shutil.which(compiler):
                return compiler
        return None

    def _compile(
        self, tex_path: Path, compiler: str, result: ArtifactResult
    ) -> ArtifactResult:
        if compiler == "tectonic":
            command = [compiler, "--untrusted", "--outdir", str(tex_path.parent), str(tex_path)]
        else:
            command = [
                compiler,
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={tex_path.parent}",
                str(tex_path),
            ]
        completed = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            result.warnings.append(
                "LaTeX derleme başarısız: " + completed.stdout[-800:].replace("\n", " ")
            )
            return result
        pdf_path = tex_path.with_suffix(".pdf")
        if not pdf_path.exists():
            result.warnings.append("Derleyici başarılı döndü fakat PDF dosyası bulunamadı.")
            return result
        result.pdf_path = str(pdf_path.resolve())
        result.pdf_download_url = (
            f"/api/v1/processes/{tex_path.parent.name}/artifacts/pdf"
        )
        result.compiled = True
        result.compiler = compiler
        return result
