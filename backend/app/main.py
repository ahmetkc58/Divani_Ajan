import hashlib
import json
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db import Database, utc_now
from app.schemas import (
    AuditEventResponse,
    CorrectTextRequest,
    DocumentAnalysisV1,
    DocumentResponse,
    DraftCreateRequest,
    DraftUpdateRequest,
    DraftV1,
    HealthResponse,
    JobResponse,
    ModelSelection,
    ModelSettingsResponse,
    UploadResponse,
)
from app.services.analysis import ANALYSIS_PROMPT_VERSION, analyze_document
from app.services.drafting import (
    DRAFT_PROMPT_VERSION,
    create_draft,
    has_blocking_errors,
    validate_draft,
)
from app.services.exports import export_docx, export_pdf
from app.services.ocr import DocumentValidationError, extract_document, validate_upload
from app.services.ollama import OllamaClient, OllamaError
from app.services.rag import RagIndex

settings = get_settings()
database = Database(settings.database_path)
ollama = OllamaClient(settings)
rag = RagIndex(settings, ollama)
logger = logging.getLogger("orneksehir")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    database.initialize()
    yield


app = FastAPI(
    title="Örnekşehir Evrak Karar Destek API",
    version="0.1.0",
    description="Sentetik kamu evrakları için yerel Ollama destekli karar destek sistemi.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    selected = _selected_models()
    ollama_ok = ollama.is_reachable()
    index_ready, index_reason = rag.status(selected.embedding_model if selected else None)
    ready = ollama_ok and selected is not None and index_ready
    return HealthResponse(
        status="ok" if ready else "degraded",
        database=settings.database_path.exists(),
        ollama=ollama_ok,
        models_selected=selected is not None,
        index_ready=index_ready,
        details={
            "ollama_base_url": settings.ollama_base_url,
            "index_reason": index_reason,
            "synthetic_only": True,
        },
    )


@app.get("/api/v1/settings/models", response_model=ModelSettingsResponse)
def get_model_settings() -> ModelSettingsResponse:
    selected = _selected_models()
    try:
        models = ollama.list_models()
        reachable = True
    except OllamaError:
        models = []
        reachable = False
    index_ready, reason = rag.status(selected.embedding_model if selected else None)
    return ModelSettingsResponse(
        ollama_reachable=reachable,
        available_models=models,
        selected=selected,
        index_ready=index_ready,
        index_reason=reason,
    )


@app.put("/api/v1/settings/models", response_model=ModelSettingsResponse)
def update_model_settings(selection: ModelSelection) -> ModelSettingsResponse:
    try:
        dimension = ollama.validate_selection(selection.chat_model, selection.embedding_model)
    except OllamaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    database.set_setting("model_selection", selection.model_dump())
    database.set_setting("embedding_dimension", dimension)
    models = ollama.list_models()
    index_ready, reason = rag.status(selection.embedding_model)
    return ModelSettingsResponse(
        ollama_reachable=True,
        available_models=models,
        selected=selection,
        index_ready=index_ready,
        index_reason=reason,
    )


@app.post("/api/v1/admin/reindex", response_model=JobResponse, status_code=202)
def reindex(background_tasks: BackgroundTasks) -> JobResponse:
    selected = _require_models()
    job = _create_job("reindex", None, "İndeksleme bekliyor")
    background_tasks.add_task(_run_reindex, job["id"], selected.embedding_model)
    return JobResponse.model_validate(job)


@app.post("/api/v1/documents", response_model=UploadResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> UploadResponse:
    filename = Path(file.filename or "belge").name
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        suffix = validate_upload(filename, file.content_type, content, settings)
    except DocumentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    document_id = str(uuid4())
    storage_path = settings.uploads_dir / f"{document_id}{suffix}"
    storage_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    now = utc_now()
    mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    database.execute(
        "INSERT INTO documents(id, filename, mime_type, sha256, storage_path, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'uploaded', ?, ?)",
        (document_id, filename, mime_type, digest, str(storage_path), now, now),
    )
    database.add_audit(
        document_id,
        "document_uploaded",
        {"filename": filename, "mime_type": mime_type, "sha256": digest},
    )
    job = _create_job("ocr", document_id, "Metin çıkarımı bekliyor")
    background_tasks.add_task(_run_ocr, job["id"], document_id, storage_path)
    return UploadResponse(document_id=document_id, job_id=job["id"])


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    return JobResponse.model_validate(_require_row("jobs", job_id))


@app.get("/api/v1/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str) -> DocumentResponse:
    return DocumentResponse.model_validate(_public_document(_require_row("documents", document_id)))


@app.get("/api/v1/documents/{document_id}/file")
def get_document_file(document_id: str) -> FileResponse:
    row = _require_row("documents", document_id)
    path = Path(row["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Belge dosyası bulunamadı.")
    return FileResponse(path, media_type=row["mime_type"], filename=row["filename"])


@app.put("/api/v1/documents/{document_id}/text", response_model=DocumentResponse)
def correct_document_text(document_id: str, request: CorrectTextRequest) -> DocumentResponse:
    _require_row("documents", document_id)
    database.execute(
        "UPDATE documents SET corrected_text = ?, status = 'text_ready', updated_at = ? WHERE id = ?",
        (request.text, utc_now(), document_id),
    )
    database.add_audit(document_id, "ocr_text_corrected", {"character_count": len(request.text)})
    return get_document(document_id)


@app.post("/api/v1/documents/{document_id}/analyze", response_model=JobResponse, status_code=202)
def start_analysis(document_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    document = _require_row("documents", document_id)
    if document["status"] not in {"text_ready", "analyzed", "drafted", "approved"}:
        raise HTTPException(status_code=409, detail="Belge metni henüz incelemeye hazır değil.")
    selected = _require_models()
    index_ready, reason = rag.status(selected.embedding_model)
    if not index_ready:
        raise HTTPException(status_code=409, detail=reason)
    job = _create_job("analysis", document_id, "Analiz bekliyor")
    background_tasks.add_task(_run_analysis, job["id"], document_id, selected)
    return JobResponse.model_validate(job)


@app.get("/api/v1/analyses/{analysis_id}", response_model=DocumentAnalysisV1)
def get_analysis(analysis_id: str) -> DocumentAnalysisV1:
    row = _require_row("analyses", analysis_id)
    return DocumentAnalysisV1.model_validate_json(row["payload_json"])


@app.post("/api/v1/analyses/{analysis_id}/drafts", response_model=JobResponse, status_code=202)
def start_draft(
    analysis_id: str,
    request: DraftCreateRequest,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    analysis = get_analysis(analysis_id)
    selected = _require_models()
    unit_id = request.unit_id or analysis.routing.recommended_unit_id
    job = _create_job("draft", analysis.document_id, "Taslak üretimi bekliyor")
    background_tasks.add_task(_run_draft, job["id"], analysis, unit_id, selected.chat_model)
    return JobResponse.model_validate(job)


@app.get("/api/v1/drafts/{draft_id}", response_model=DraftV1)
def get_draft(draft_id: str) -> DraftV1:
    row = _require_row("drafts", draft_id)
    return DraftV1.model_validate_json(row["payload_json"])


@app.patch("/api/v1/drafts/{draft_id}", response_model=DraftV1)
def update_draft(draft_id: str, request: DraftUpdateRequest) -> DraftV1:
    row = _require_row("drafts", draft_id)
    draft = DraftV1.model_validate_json(row["payload_json"])
    updates = request.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(draft, key, value)
    draft.status = "draft"
    draft.version += 1
    draft.updated_at = utc_now()
    draft.validations = validate_draft(draft)
    _save_draft(draft)
    database.add_audit(
        draft.document_id,
        "draft_updated",
        {"draft_id": draft.id, "version": draft.version, "fields": sorted(updates)},
    )
    return draft


@app.post("/api/v1/drafts/{draft_id}/approve", response_model=DraftV1)
def approve_draft(draft_id: str) -> DraftV1:
    draft = get_draft(draft_id)
    draft.validations = validate_draft(draft)
    if has_blocking_errors(draft):
        raise HTTPException(status_code=409, detail="Taslakta onayı engelleyen doğrulama hataları var.")
    draft.status = "approved"
    draft.version += 1
    draft.updated_at = utc_now()
    _save_draft(draft)
    database.execute(
        "UPDATE documents SET status = 'approved', updated_at = ? WHERE id = ?",
        (utc_now(), draft.document_id),
    )
    database.add_audit(
        draft.document_id,
        "draft_approved",
        {"draft_id": draft.id, "version": draft.version},
    )
    return draft


@app.get("/api/v1/drafts/{draft_id}/export")
def export_draft(draft_id: str, format: str) -> FileResponse:
    draft = get_draft(draft_id)
    if draft.status != "approved":
        raise HTTPException(status_code=409, detail="Yalnızca insan tarafından onaylanmış taslaklar aktarılabilir.")
    normalized_format = format.lower()
    if normalized_format not in {"docx", "pdf"}:
        raise HTTPException(status_code=422, detail="Format docx veya pdf olmalıdır.")
    path = settings.exports_dir / f"{draft.id}-v{draft.version}.{normalized_format}"
    if normalized_format == "docx":
        export_docx(draft, path)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        export_pdf(draft, path)
        media_type = "application/pdf"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    database.add_audit(
        draft.document_id,
        "draft_exported",
        {"draft_id": draft.id, "version": draft.version, "format": normalized_format, "sha256": digest},
    )
    return FileResponse(path, media_type=media_type, filename=f"orneksehir-taslak.{normalized_format}")


@app.get("/api/v1/documents/{document_id}/audit", response_model=list[AuditEventResponse])
def get_audit(document_id: str) -> list[AuditEventResponse]:
    _require_row("documents", document_id)
    rows = database.fetch_all(
        "SELECT * FROM audit_events WHERE document_id = ? ORDER BY id ASC", (document_id,)
    )
    return [
        AuditEventResponse(
            id=row["id"],
            document_id=row["document_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@app.delete("/api/v1/documents/{document_id}", status_code=204)
def delete_document(document_id: str) -> None:
    document = _require_row("documents", document_id)
    draft_rows = database.fetch_all("SELECT id FROM drafts WHERE document_id = ?", (document_id,))
    path = Path(document["storage_path"])
    if path.exists():
        path.unlink()
    for row in draft_rows:
        for export_path in settings.exports_dir.glob(f"{row['id']}-v*.*"):
            export_path.unlink(missing_ok=True)
    database.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def _run_reindex(job_id: str, embedding_model: str) -> None:
    try:
        _update_job(job_id, status="running", progress=1, stage="Kaynaklar hazırlanıyor")
        meta = rag.build(
            embedding_model,
            progress=lambda progress, stage: _update_job(
                job_id, status="running", progress=progress, stage=stage
            ),
        )
        database.set_setting("index_meta", meta)
        _update_job(job_id, status="succeeded", progress=100, stage="İndeks hazır")
    except Exception as exc:
        logger.exception("Reindex failed")
        _update_job(job_id, status="failed", stage="İndeksleme başarısız", error=str(exc))


def _run_ocr(job_id: str, document_id: str, path: Path) -> None:
    try:
        _update_job(job_id, status="running", progress=10, stage="Belge okunuyor")
        result = extract_document(path, settings)
        database.execute(
            "UPDATE documents SET page_count = ?, extraction_method = ?, original_text = ?, "
            "corrected_text = ?, text_quality = ?, status = 'text_ready', updated_at = ? WHERE id = ?",
            (
                result.page_count,
                result.method,
                result.text,
                result.text,
                result.quality,
                utc_now(),
                document_id,
            ),
        )
        database.add_audit(
            document_id,
            "text_extracted",
            {
                "method": result.method,
                "page_count": result.page_count,
                "text_quality": round(result.quality, 4),
                "character_count": len(result.text),
            },
        )
        _update_job(job_id, status="succeeded", progress=100, stage="Metin incelemeye hazır")
    except Exception as exc:
        logger.exception("OCR failed")
        _update_job(job_id, status="failed", stage="Metin çıkarımı başarısız", error=str(exc))


def _run_analysis(job_id: str, document_id: str, selected: ModelSelection) -> None:
    try:
        _update_job(job_id, status="running", progress=10, stage="Evrak analiz ediliyor")
        document = _require_row("documents", document_id)
        text = document["corrected_text"] or document["original_text"]
        if not text:
            raise ValueError("Analiz edilecek belge metni yok.")
        result = analyze_document(
            document_id=document_id,
            text=text,
            text_quality=float(document["text_quality"]),
            chat_model=selected.chat_model,
            embedding_model=selected.embedding_model,
            ollama=ollama,
            rag=rag,
        )
        database.execute(
            "INSERT INTO analyses(id, document_id, payload_json, model_name, prompt_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.id,
                document_id,
                result.model_dump_json(),
                selected.chat_model,
                ANALYSIS_PROMPT_VERSION,
                result.created_at,
            ),
        )
        database.execute(
            "UPDATE documents SET status = 'analyzed', updated_at = ? WHERE id = ?",
            (utc_now(), document_id),
        )
        database.add_audit(
            document_id,
            "document_analyzed",
            {
                "analysis_id": result.id,
                "model": selected.chat_model,
                "prompt_version": ANALYSIS_PROMPT_VERSION,
                "regulation_sources": [item.source_id for item in result.regulations],
            },
        )
        _update_job(
            job_id,
            status="succeeded",
            progress=100,
            stage="Analiz hazır",
            result_id=result.id,
        )
    except Exception as exc:
        logger.exception("Analysis failed")
        _update_job(job_id, status="failed", stage="Analiz başarısız", error=str(exc))


def _run_draft(job_id: str, analysis: DocumentAnalysisV1, unit_id: str, chat_model: str) -> None:
    try:
        _update_job(job_id, status="running", progress=20, stage="Resmî yazı taslağı hazırlanıyor")
        draft = create_draft(
            analysis=analysis,
            selected_unit_id=unit_id,
            chat_model=chat_model,
            ollama=ollama,
        )
        database.execute(
            "INSERT INTO drafts(id, analysis_id, document_id, payload_json, status, version, model_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                draft.id,
                draft.analysis_id,
                draft.document_id,
                draft.model_dump_json(),
                draft.status,
                draft.version,
                draft.model_name,
                draft.created_at,
                draft.updated_at,
            ),
        )
        database.execute(
            "UPDATE documents SET status = 'drafted', updated_at = ? WHERE id = ?",
            (utc_now(), draft.document_id),
        )
        database.add_audit(
            draft.document_id,
            "draft_created",
            {
                "draft_id": draft.id,
                "model": draft.model_name,
                "prompt_version": DRAFT_PROMPT_VERSION,
                "recipient_unit_id": unit_id,
            },
        )
        _update_job(
            job_id,
            status="succeeded",
            progress=100,
            stage="Taslak hazır",
            result_id=draft.id,
        )
    except Exception as exc:
        logger.exception("Draft failed")
        _update_job(job_id, status="failed", stage="Taslak üretimi başarısız", error=str(exc))


def _selected_models() -> ModelSelection | None:
    payload = database.get_setting("model_selection")
    return ModelSelection.model_validate(payload) if payload else None


def _require_models() -> ModelSelection:
    selected = _selected_models()
    if selected is None:
        raise HTTPException(status_code=409, detail="Önce Ollama analiz ve embedding modellerini seçin.")
    if not ollama.is_reachable():
        raise HTTPException(status_code=503, detail="Ollama servisine ulaşılamıyor.")
    return selected


def _create_job(job_type: str, document_id: str | None, stage: str) -> dict:
    job_id = str(uuid4())
    now = utc_now()
    database.execute(
        "INSERT INTO jobs(id, job_type, document_id, status, progress, stage, created_at, updated_at) "
        "VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)",
        (job_id, job_type, document_id, stage, now, now),
    )
    return _require_row("jobs", job_id)


def _update_job(
    job_id: str,
    *,
    status: str,
    stage: str,
    progress: int | None = None,
    error: str | None = None,
    result_id: str | None = None,
) -> None:
    current = _require_row("jobs", job_id)
    database.execute(
        "UPDATE jobs SET status = ?, progress = ?, stage = ?, error = ?, result_id = ?, updated_at = ? WHERE id = ?",
        (
            status,
            current["progress"] if progress is None else max(0, min(progress, 100)),
            stage,
            error,
            result_id,
            utc_now(),
            job_id,
        ),
    )


def _require_row(table: str, record_id: str) -> dict:
    allowed_tables = {"documents", "jobs", "analyses", "drafts"}
    if table not in allowed_tables:
        raise RuntimeError("Geçersiz tablo adı.")
    row = database.fetch_one(f"SELECT * FROM {table} WHERE id = ?", (record_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    return row


def _public_document(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "storage_path"}


def _save_draft(draft: DraftV1) -> None:
    database.execute(
        "UPDATE drafts SET payload_json = ?, status = ?, version = ?, updated_at = ? WHERE id = ?",
        (draft.model_dump_json(), draft.status, draft.version, draft.updated_at, draft.id),
    )
