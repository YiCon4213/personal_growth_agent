from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import DatabaseConfigurationError, get_session
from app.db.models import RagDocument
from app.models.schemas import (
    RagDocumentImportRequest,
    RagDocumentResponse,
    RagFileImportRequest,
    RagSearchRequest,
    RagSearchResponse,
)
from app.services.data_store import DataStore
from app.services.rag_service import FitnessRagService, RagDocumentError, RagSearchError

router = APIRouter(prefix="/rag", tags=["rag"])


def to_document_response(document: RagDocument) -> RagDocumentResponse:
    return RagDocumentResponse(
        id=document.id,
        user_id=document.user_id,
        title=document.title,
        source_uri=document.source_uri,
        source_type=document.source_type,
        embedding_model=document.embedding_model,
        embedding_dimension=document.embedding_dimension,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
        metadata=document.metadata_json,
    )


SessionDependency = Annotated[Session, Depends(get_session)]


@router.post("/documents", response_model=RagDocumentResponse)
def import_rag_document(request: RagDocumentImportRequest, session: SessionDependency) -> RagDocumentResponse:
    try:
        service = FitnessRagService(session)
        document = service.import_text_document(
            user_id=request.user_id,
            title=request.title,
            content=request.content,
            source_uri=request.source_uri,
            source_type=request.source_type,
            metadata=request.metadata,
        )
        session.commit()
        return to_document_response(document)
    except RagDocumentError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/documents/import-file", response_model=RagDocumentResponse)
def import_rag_file(request: RagFileImportRequest, session: SessionDependency) -> RagDocumentResponse:
    try:
        service = FitnessRagService(session)
        document = service.import_file_document(
            user_id=request.user_id,
            file_path=request.file_path,
            title=request.title,
            metadata=request.metadata,
        )
        session.commit()
        return to_document_response(document)
    except RagDocumentError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/documents", response_model=list[RagDocumentResponse])
def list_rag_documents(user_id: str, session: SessionDependency) -> list[RagDocumentResponse]:
    try:
        store = DataStore(session)
        return [to_document_response(document) for document in store.list_rag_documents(user_id)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/search", response_model=RagSearchResponse)
def search_rag(request: RagSearchRequest, session: SessionDependency) -> RagSearchResponse:
    try:
        service = FitnessRagService(session)
        result = service.search(
            user_id=request.user_id,
            query=request.query,
            document_ids=request.document_ids or None,
            top_k=request.top_k,
            min_relevance=request.min_relevance,
        )
        return RagSearchResponse(
            sources=result.sources,
            no_match_reason=result.no_match_reason,
        )
    except RagSearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
