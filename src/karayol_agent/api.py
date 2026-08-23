from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from karayol_agent import __version__
from karayol_agent.config import settings
from karayol_agent.documents import ExtractionError
from karayol_agent.orchestrator import (
    ProcessNotFoundError,
    ProcessValidationError,
    build_orchestrator,
)
from karayol_agent.schemas import (
    ApprovalRequest,
    InformationUpdateRequest,
    ProcessState,
    TextProcessRequest,
)


app = FastAPI(
    title="Karayolu Evrak Akıllı Ajan API",
    description="Sentetik karayolu evrakları için kaynak doğrulamalı çok ajanlı MVP",
    version=__version__,
)
orchestrator = build_orchestrator()
web_directory = Path(__file__).resolve().parent / "web"
app.mount(
    "/ui-assets",
    StaticFiles(directory=web_directory / "static"),
    name="ui-assets",
)


@app.get("/", response_class=FileResponse, include_in_schema=False)
def manual_test_interface() -> FileResponse:
    return FileResponse(
        web_directory / "index.html",
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                "base-uri 'none'; form-action 'self'"
            ),
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "corpus_size": len(orchestrator.index.documents),
        "latex_compiler": orchestrator.renderer._find_compiler(),
        "data_mode": "sentetik_demo",
    }


@app.post("/v1/process/text", response_model=ProcessState)
def process_text(request: TextProcessRequest) -> ProcessState:
    return orchestrator.process_text(
        request.text,
        source_name=request.source_name,
        compile_pdf=request.compile_pdf,
    )


@app.post("/v1/process/file", response_model=ProcessState)
async def process_file(
    file: UploadFile = File(...), compile_pdf: bool = False
) -> ProcessState:
    filename = Path(file.filename or "upload.txt").name
    suffix = Path(filename).suffix.lower()
    if suffix not in orchestrator.extractor.SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Yalnızca TXT, MD ve PDF dosyaları kabul edilir.",
        )
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Dosya izin verilen boyut sınırını aşıyor.",
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        text = orchestrator.extractor.extract(temporary_path)
        return orchestrator.process_text(
            text, source_name=filename, compile_pdf=compile_pdf
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


@app.get("/v1/process/{document_id}", response_model=ProcessState)
def get_process(document_id: str) -> ProcessState:
    try:
        return orchestrator.get(document_id)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evrak süreci bulunamadı.") from exc


@app.post("/v1/process/{document_id}/information", response_model=ProcessState)
def provide_information(
    document_id: str, request: InformationUpdateRequest
) -> ProcessState:
    try:
        return orchestrator.provide_information(
            document_id, request.fields, compile_pdf=request.compile_pdf
        )
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evrak süreci bulunamadı.") from exc
    except ProcessValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/process/{document_id}/approve", response_model=ProcessState)
def approve(document_id: str, request: ApprovalRequest) -> ProcessState:
    try:
        return orchestrator.approve(document_id, request.approved_by)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evrak süreci bulunamadı.") from exc
    except ProcessValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _artifact_response(document_id: str, artifact_type: str) -> FileResponse:
    try:
        state = orchestrator.get(document_id)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evrak süreci bulunamadı.") from exc
    if not state.artifact:
        raise HTTPException(status_code=404, detail="Evrak çıktısı henüz oluşturulmadı.")

    raw_path = (
        state.artifact.tex_path
        if artifact_type == "tex"
        else state.artifact.pdf_path
    )
    if not raw_path:
        raise HTTPException(
            status_code=404,
            detail=f"{artifact_type.upper()} çıktısı bulunmuyor.",
        )
    artifact_path = Path(raw_path).resolve()
    output_root = orchestrator.settings.output_dir.resolve()
    try:
        artifact_path.relative_to(output_root)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Geçersiz çıktı yolu.") from exc
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Çıktı dosyası bulunamadı.")

    media_type = "application/x-tex" if artifact_type == "tex" else "application/pdf"
    return FileResponse(
        artifact_path,
        media_type=media_type,
        filename=f"{document_id}-taslak.{artifact_type}",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@app.get("/v1/process/{document_id}/artifacts/tex", response_class=FileResponse)
def download_tex(document_id: str) -> FileResponse:
    return _artifact_response(document_id, "tex")


@app.get("/v1/process/{document_id}/artifacts/pdf", response_class=FileResponse)
def download_pdf(document_id: str) -> FileResponse:
    return _artifact_response(document_id, "pdf")
