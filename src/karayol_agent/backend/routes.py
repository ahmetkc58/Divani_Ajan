from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from karayol_agent import __version__
from karayol_agent.documents import ExtractionError
from karayol_agent.orchestrator import (
    EvrakOrchestrator,
    ProcessNotFoundError,
    ProcessValidationError,
)
from karayol_agent.schemas import (
    ApprovalRequest,
    InformationUpdateRequest,
    ProcessState,
    ResponseStrategyRequest,
    TextProcessRequest,
)

OrchestratorProvider = Callable[[], EvrakOrchestrator]


def build_routers(
    orchestrator_provider: OrchestratorProvider,
) -> tuple[APIRouter, APIRouter]:
    """Build the canonical REST API and its temporary legacy compatibility layer."""

    api = APIRouter(prefix="/api/v1")
    legacy = APIRouter(include_in_schema=False)

    def current_orchestrator() -> EvrakOrchestrator:
        return orchestrator_provider()

    @api.get(
        "/system/health",
        tags=["system"],
        summary="Backend sağlık durumunu getir",
        operation_id="getSystemHealth",
    )
    @legacy.get("/health")
    def health() -> dict[str, object]:
        orchestrator = current_orchestrator()
        return {
            "status": "ok",
            "version": __version__,
            "corpus_size": len(orchestrator.index.documents),
            "latex_compiler": orchestrator.renderer._find_compiler(),
            **orchestrator.corpus_disclosure(),
            **orchestrator.decision_disclosure(),
            "retrieval_mode": orchestrator.settings.retrieval_mode,
            "retrieval_setup_warning": orchestrator.retrieval_setup_warning,
        }

    @api.get(
        "/system/readiness",
        tags=["system"],
        summary="İşleme altyapısının hazır olup olmadığını getir",
        operation_id="getSystemReadiness",
    )
    @legacy.get("/ready")
    async def readiness(response: Response) -> dict[str, object]:
        report = await run_in_threadpool(current_orchestrator().readiness)
        if report["ready"] is not True:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if report["ready"] else "not_ready", **report}

    @api.post(
        "/processes/text",
        response_model=ProcessState,
        tags=["processes"],
        summary="Metin evrakı işle",
        operation_id="processTextDocument",
    )
    @legacy.post("/v1/process/text", response_model=ProcessState)
    def process_text(request: TextProcessRequest) -> ProcessState:
        return current_orchestrator().process_text(
            request.text,
            source_name=request.source_name,
            compile_pdf=request.compile_pdf,
        )

    @api.post(
        "/processes/text/start",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["processes"],
        summary="Metin evrakını canlı izlenebilir biçimde başlat",
        operation_id="startTextDocument",
    )
    def start_text(
        request: TextProcessRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        orchestrator = current_orchestrator()
        state = orchestrator.reserve_text_process(
            request.text,
            source_name=request.source_name,
        )
        background_tasks.add_task(
            orchestrator.process_text,
            request.text,
            source_name=request.source_name,
            compile_pdf=request.compile_pdf,
            document_id=state.document_id,
        )
        return {
            "document_id": state.document_id,
            "status": state.status.value,
            "poll_url": f"/api/v1/processes/{state.document_id}",
        }

    @api.post(
        "/processes/file",
        response_model=ProcessState,
        tags=["processes"],
        summary="Dosya evrakı yükle ve işle",
        operation_id="uploadDocument",
    )
    @legacy.post("/v1/process/file", response_model=ProcessState)
    async def process_file(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI request declaration
        compile_pdf: bool = False,
    ) -> ProcessState:
        orchestrator = current_orchestrator()
        filename = Path(file.filename or "upload.txt").name
        suffix = Path(filename).suffix.lower()
        if suffix not in orchestrator.extractor.SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Yalnızca TXT, MD, PDF, PNG, JPG ve TIFF dosyaları kabul edilir.",
            )
        content = await file.read(orchestrator.settings.max_upload_bytes + 1)
        if len(content) > orchestrator.settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Dosya izin verilen boyut sınırını aşıyor.",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            text, document_layout = await run_in_threadpool(
                orchestrator.extractor.extract_with_layout, temporary_path
            )
            return await run_in_threadpool(
                orchestrator.process_text,
                text,
                source_name=filename,
                compile_pdf=compile_pdf,
                document_layout=document_layout,
            )
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    @api.post(
        "/processes/file/start",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["processes"],
        summary="Dosya evrakını canlı izlenebilir biçimde başlat",
        operation_id="startFileDocument",
    )
    async def start_file(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),  # noqa: B008 - FastAPI request declaration
        compile_pdf: bool = False,
    ) -> dict[str, str]:
        orchestrator = current_orchestrator()
        filename = Path(file.filename or "upload.txt").name
        suffix = Path(filename).suffix.lower()
        if suffix not in orchestrator.extractor.SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Yalnızca TXT, MD, PDF, PNG, JPG ve TIFF dosyaları kabul edilir.",
            )
        content = await file.read(orchestrator.settings.max_upload_bytes + 1)
        if len(content) > orchestrator.settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Dosya izin verilen boyut sınırını aşıyor.",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            text, document_layout = await run_in_threadpool(
                orchestrator.extractor.extract_with_layout, temporary_path
            )
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

        state = orchestrator.reserve_text_process(
            text,
            source_name=filename,
            document_layout=document_layout,
        )
        background_tasks.add_task(
            orchestrator.process_text,
            text,
            source_name=filename,
            compile_pdf=compile_pdf,
            document_layout=document_layout,
            document_id=state.document_id,
        )
        return {
            "document_id": state.document_id,
            "status": state.status.value,
            "poll_url": f"/api/v1/processes/{state.document_id}",
        }

    @api.get(
        "/processes/{document_id}",
        response_model=ProcessState,
        tags=["processes"],
        summary="Evrak sürecini getir",
        operation_id="getProcess",
    )
    @legacy.get("/v1/process/{document_id}", response_model=ProcessState)
    def get_process(document_id: str) -> ProcessState:
        try:
            return current_orchestrator().get(document_id)
        except ProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evrak süreci bulunamadı."
            ) from exc

    @api.post(
        "/processes/{document_id}/information",
        response_model=ProcessState,
        tags=["processes"],
        summary="Eksik evrak bilgilerini tamamla",
        operation_id="updateProcessInformation",
    )
    @legacy.post("/v1/process/{document_id}/information", response_model=ProcessState)
    def provide_information(
        document_id: str, request: InformationUpdateRequest
    ) -> ProcessState:
        try:
            return current_orchestrator().provide_information(
                document_id, request.fields, compile_pdf=request.compile_pdf
            )
        except ProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evrak süreci bulunamadı."
            ) from exc
        except ProcessValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.post(
        "/processes/{document_id}/response-strategy",
        response_model=ProcessState,
        tags=["processes"],
        summary="Katman 3 yanıt stratejisini seç",
        operation_id="chooseResponseStrategy",
    )
    @legacy.post(
        "/v1/process/{document_id}/response-strategy",
        response_model=ProcessState,
    )
    def choose_response_strategy(
        document_id: str, request: ResponseStrategyRequest
    ) -> ProcessState:
        try:
            return current_orchestrator().choose_response_strategy(
                document_id,
                option_id=request.option_id,
                custom_text=request.custom_text,
                delivery_target=request.delivery_target,
                compile_pdf=request.compile_pdf,
            )
        except ProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evrak süreci bulunamadı."
            ) from exc
        except ProcessValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.post(
        "/processes/{document_id}/approval",
        response_model=ProcessState,
        tags=["processes"],
        summary="Evrak taslağını onayla",
        operation_id="approveProcess",
    )
    @legacy.post("/v1/process/{document_id}/approve", response_model=ProcessState)
    def approve(document_id: str, request: ApprovalRequest) -> ProcessState:
        try:
            return current_orchestrator().approve(document_id, request.approved_by)
        except ProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evrak süreci bulunamadı."
            ) from exc
        except ProcessValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def artifact_response(document_id: str, artifact_type: str) -> FileResponse:
        orchestrator = current_orchestrator()
        try:
            state = orchestrator.get(document_id)
        except ProcessNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evrak süreci bulunamadı."
            ) from exc
        if not state.artifact:
            raise HTTPException(
                status_code=404, detail="Evrak çıktısı henüz oluşturulmadı."
            )

        raw_path = (
            state.artifact.tex_path
            if artifact_type == "tex"
            else state.artifact.pdf_path
        )
        if not raw_path:
            raise HTTPException(
                status_code=404, detail=f"{artifact_type.upper()} çıktısı bulunmuyor."
            )
        artifact_path = Path(raw_path).resolve()
        output_root = orchestrator.settings.output_dir.resolve()
        try:
            artifact_path.relative_to(output_root)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Geçersiz çıktı yolu.") from exc
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="Çıktı dosyası bulunamadı.")

        media_type = (
            "application/x-tex" if artifact_type == "tex" else "application/pdf"
        )
        return FileResponse(
            artifact_path,
            media_type=media_type,
            filename=f"{document_id}-taslak.{artifact_type}",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        )

    def layer3_artifact_response(
        document_id: str, target: str, artifact_type: str
    ) -> FileResponse:
        orchestrator = current_orchestrator()
        try:
            state = orchestrator.get(document_id)
        except ProcessNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Evrak süreci bulunamadı.") from exc
        output = next(
            (
                item
                for item in state.layer3_outputs
                if item.target == target
                or (target == "default" and item is state.layer3_outputs[0])
            ),
            None,
        )
        if output is None:
            raise HTTPException(status_code=404, detail="Katman 3 taslağı bulunamadı.")
        raw_path = (
            output.artifact.tex_path
            if artifact_type == "tex"
            else output.artifact.pdf_path
        )
        if not raw_path:
            raise HTTPException(
                status_code=404,
                detail=f"{artifact_type.upper()} çıktısı bulunmuyor.",
            )
        artifact_path = Path(raw_path).resolve()
        try:
            artifact_path.relative_to(orchestrator.settings.output_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Geçersiz çıktı yolu.") from exc
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="Çıktı dosyası bulunamadı.")
        return FileResponse(
            artifact_path,
            media_type=(
                "application/x-tex" if artifact_type == "tex" else "application/pdf"
            ),
            filename=f"{document_id}-{target}-taslak.{artifact_type}",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        )

    @api.get(
        "/processes/{document_id}/artifacts/{target}/tex",
        response_class=FileResponse,
        tags=["artifacts"],
        summary="Katman 3 LaTeX taslağını indir",
        operation_id="downloadLayer3LatexArtifact",
    )
    def download_layer3_tex(document_id: str, target: str) -> FileResponse:
        return layer3_artifact_response(document_id, target, "tex")

    @api.get(
        "/processes/{document_id}/artifacts/{target}/pdf",
        response_class=FileResponse,
        tags=["artifacts"],
        summary="Katman 3 PDF taslağını indir",
        operation_id="downloadLayer3PdfArtifact",
    )
    def download_layer3_pdf(document_id: str, target: str) -> FileResponse:
        return layer3_artifact_response(document_id, target, "pdf")

    @api.get(
        "/processes/{document_id}/artifacts/tex",
        response_class=FileResponse,
        tags=["artifacts"],
        summary="LaTeX artifact'ını indir",
        operation_id="downloadLatexArtifact",
    )
    @legacy.get("/v1/process/{document_id}/artifacts/tex", response_class=FileResponse)
    def download_tex(document_id: str) -> FileResponse:
        return artifact_response(document_id, "tex")

    @api.get(
        "/processes/{document_id}/artifacts/pdf",
        response_class=FileResponse,
        tags=["artifacts"],
        summary="PDF artifact'ını indir",
        operation_id="downloadPdfArtifact",
    )
    @legacy.get("/v1/process/{document_id}/artifacts/pdf", response_class=FileResponse)
    def download_pdf(document_id: str) -> FileResponse:
        return artifact_response(document_id, "pdf")

    return api, legacy
