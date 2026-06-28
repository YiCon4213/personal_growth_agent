from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.db.models import Thread
from app.models.schemas import (
    ChatMessage,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationRenameRequest,
    ConversationSummary,
    MessageRole,
)
from app.services.data_store import DataStore

router = APIRouter(prefix="/conversations", tags=["conversations"])
DEFAULT_USER_ID = "default_user"


def _summary(thread: Thread, message_count: int = 0) -> ConversationSummary:
    return ConversationSummary(
        id=thread.id,
        title=thread.title or "新会话",
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        message_count=message_count,
    )


def _owned_thread(store: DataStore, thread_id: str) -> Thread:
    thread = store.get_thread(thread_id)
    if thread is None or thread.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return thread


@router.post("", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreateRequest,
    session: Session = Depends(get_session),
) -> ConversationDetail:
    store = DataStore(session)
    thread = store.upsert_thread(
        f"thread_{uuid4().hex}",
        user_id=DEFAULT_USER_ID,
        title=(request.title or "新会话").strip() or "新会话",
    )
    session.commit()
    return ConversationDetail(**_summary(thread).model_dump(), messages=[])


@router.get("", response_model=list[ConversationSummary])
def list_conversations(session: Session = Depends(get_session)) -> list[ConversationSummary]:
    return [_summary(thread, count) for thread, count in DataStore(session).list_threads(DEFAULT_USER_ID)]


@router.get("/{thread_id}", response_model=ConversationDetail)
def get_conversation(
    thread_id: str,
    session: Session = Depends(get_session),
) -> ConversationDetail:
    store = DataStore(session)
    thread = _owned_thread(store, thread_id)
    messages = store.list_messages(thread_id)
    return ConversationDetail(
        **_summary(thread, len(messages)).model_dump(),
        messages=[
            ChatMessage(
                id=item.id,
                role=MessageRole(item.role),
                content=item.content,
                created_at=item.created_at,
                metadata=item.metadata_json,
            )
            for item in messages
        ],
    )


@router.patch("/{thread_id}", response_model=ConversationSummary)
def rename_conversation(
    thread_id: str,
    request: ConversationRenameRequest,
    session: Session = Depends(get_session),
) -> ConversationSummary:
    store = DataStore(session)
    thread = _owned_thread(store, thread_id)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be blank.")
    thread.title = title
    session.commit()
    return _summary(thread, len(store.list_messages(thread_id)))


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    thread_id: str,
    session: Session = Depends(get_session),
) -> Response:
    store = DataStore(session)
    _owned_thread(store, thread_id)
    store.delete_thread(thread_id, user_id=DEFAULT_USER_ID)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)