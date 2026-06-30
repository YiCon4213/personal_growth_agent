from io import BytesIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.database import DatabaseConfigurationError, get_session
from app.db.models import RagDocument
from app.models.schemas import RagDocumentImportRequest, RagDocumentResponse, RagSearchRequest, RagSearchResponse
from app.services.data_store import DataStore
from app.services.embedding_service import EmbeddingServiceError
from app.services.rag_service import DEFAULT_USER_ID, FitnessRagService, RagDocumentError, RagSearchError

router = APIRouter(prefix="/rag", tags=["rag"])
SessionDependency = Annotated[Session, Depends(get_session)]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def to_document_response(document: RagDocument) -> RagDocumentResponse:
    return RagDocumentResponse(
        id=document.id, user_id=document.user_id, title=document.title,
        source_uri=document.source_uri, source_type=document.source_type,
        embedding_provider=document.embedding_provider, embedding_model=document.embedding_model,
        embedding_version=document.embedding_version, embedding_dimension=document.embedding_dimension,
        content_hash=document.content_hash, index_status=document.index_status,
        chunk_count=document.chunk_count, created_at=document.created_at, updated_at=document.updated_at,
        metadata=document.metadata_json,
    )


def service_for(request: Request, session: Session) -> FitnessRagService:
    return FitnessRagService(
        session,
        embedding_provider=getattr(request.app.state, "embedding_provider", None),
        llm_service=getattr(request.app.state, "llm_service", None),
    )


@router.post("/documents", response_model=RagDocumentResponse)
async def import_rag_document(payload: RagDocumentImportRequest, request: Request, session: SessionDependency) -> RagDocumentResponse:
    try:
        document = await service_for(request, session).import_text_document_async(
            user_id=DEFAULT_USER_ID, title=payload.title, content=payload.content,
            source_uri=payload.source_uri, source_type=payload.source_type, metadata=payload.metadata,
        )
        session.commit()
        return to_document_response(document)
    except (RagDocumentError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingServiceError as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/documents/upload", response_model=RagDocumentResponse)
async def upload_rag_document(request: Request, session: SessionDependency, file: UploadFile = File(...), title: str | None = Form(default=None)) -> RagDocumentResponse:
    filename = file.filename or "upload.txt"
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in {"md", "markdown", "txt", "pdf"}:
        raise HTTPException(status_code=400, detail="Only Markdown, TXT, and text-based PDF uploads are supported.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 10 MiB limit.")
    try:
        if suffix == "pdf":
            content = "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(BytesIO(raw)).pages).strip()
        else:
            content = raw.decode("utf-8")
        document = await service_for(request, session).import_text_document_async(
            user_id=DEFAULT_USER_ID, title=title or filename.rsplit(".", 1)[0], content=content,
            source_uri=filename, source_type="markdown" if suffix in {"md", "markdown"} else suffix,
            metadata={"upload": True, "content_type": file.content_type},
        )
        session.commit()
        return to_document_response(document)
    except (UnicodeDecodeError, RagDocumentError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingServiceError as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/documents", response_model=list[RagDocumentResponse])
def list_rag_documents(session: SessionDependency) -> list[RagDocumentResponse]:
    return [to_document_response(document) for document in DataStore(session).list_rag_documents(DEFAULT_USER_ID)]


@router.post("/documents/rebuild-index")
async def rebuild_rag_index(request: Request, session: SessionDependency) -> dict[str, Any]:
    try:
        count = await service_for(request, session).rebuild_index(user_id=DEFAULT_USER_ID)
        session.commit()
        return {"rebuilt_documents": count}
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail=f"Index rebuild failed: {exc}") from exc


@router.post("/search", response_model=RagSearchResponse)
async def search_rag(payload: RagSearchRequest, request: Request, session: SessionDependency) -> RagSearchResponse:
    try:
        result = await service_for(request, session).search_async(
            user_id=DEFAULT_USER_ID, query=payload.query, document_ids=payload.document_ids or None,
            top_k=min(payload.top_k, 3), min_relevance=payload.min_relevance,
        )
        return RagSearchResponse(sources=result.sources, no_match_reason=result.no_match_reason, trace=result.trace or {})
    except RagSearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
