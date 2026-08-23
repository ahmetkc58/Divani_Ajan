from __future__ import annotations

import json
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
            tex_download_url=f"/v1/process/{document_id}/artifacts/tex",
        )
        if not compile_pdf:
            result.warnings.append("PDF derleme istenmedi; yalnızca LaTeX taslağı üretildi.")
            return result

        compiler = self._find_compiler()
        if compiler is None:
            result.warnings.append(
                "LaTeX derleyicisi bulunamadı; .tex üretildi ancak PDF derlenemedi."
            )
            return result
        return self._compile(tex_path, compiler, result)

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
        references = "\n".join(
            rf"\item {escape_latex(reference.title)}"
            + (rf" - {escape_latex(reference.article)}" if reference.article else "")
            + rf" ({escape_latex(reference.source)})"
            for reference in draft.references
        )
        if not references:
            references = r"\item [DOĞRULANMIŞ KAYNAK BULUNAMADI]"
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
            "references": references,
        }

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
            f"/v1/process/{tex_path.parent.name}/artifacts/pdf"
        )
        result.compiled = True
        result.compiler = compiler
        return result
