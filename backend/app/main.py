from fastapi import FastAPI, Request

from fastapi.encoders import jsonable_encoder

from fastapi.exceptions import RequestValidationError

from fastapi.responses import JSONResponse, StreamingResponse



from app.api.v1.approvals import router as approvals_router

from app.api.v1.chat import build_stream_event, format_sse, router as chat_router

from app.api.v1.contracts import router as contracts_router
from app.api.v1.conversations import router as conversations_router

from app.api.v1.health import router as health_router

from app.api.v1.mcp import router as mcp_router

from app.api.v1.profile import router as profile_router

from app.api.v1.rag import router as rag_router
from app.api.v1.skills import router as skills_router

from app.core.config import get_settings

from app.models.schemas import ErrorCode, ErrorResponse, StreamEventType
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingProvider





def create_app(*, llm_service: LLMService | None = None, embedding_provider: EmbeddingProvider | None = None) -> FastAPI:

    settings = get_settings()

    app = FastAPI(

        title="Personal Growth Agent API",

        version="0.1.0",

        description="New backend boundary for the personal growth multi-agent platform.",

    )



    app.state.llm_service = llm_service
    app.state.embedding_provider = embedding_provider

    @app.exception_handler(RequestValidationError)

    async def validation_exception_handler(

        request: Request,

        exc: RequestValidationError,

    ) -> JSONResponse | StreamingResponse:

        if request.url.path == f"{settings.api_v1_prefix}/chat/stream":

            body = exc.body if isinstance(exc.body, dict) else {}

            body_thread_id = body.get("thread_id")

            thread_id = body_thread_id if isinstance(body_thread_id, str) else "unknown"

            event = build_stream_event(

                event_type=StreamEventType.ERROR,

                thread_id=thread_id,

                run_id="run_validation_error",

                payload=ErrorResponse(

                    code=ErrorCode.VALIDATION_ERROR,

                    message="Chat stream request validation failed.",

                    details={"errors": jsonable_encoder(exc.errors())},

                ).model_dump(mode="json"),

            )

            return StreamingResponse(

                iter([format_sse(event)]),

                media_type="text/event-stream",

                status_code=200,

                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},

            )

        return JSONResponse(

            status_code=422,

            content={"detail": jsonable_encoder(exc.errors())},

        )



    app.include_router(approvals_router, prefix=settings.api_v1_prefix)

    app.include_router(chat_router, prefix=settings.api_v1_prefix)

    app.include_router(contracts_router, prefix=settings.api_v1_prefix)
    app.include_router(conversations_router, prefix=settings.api_v1_prefix)

    app.include_router(health_router, prefix=settings.api_v1_prefix)

    app.include_router(mcp_router, prefix=settings.api_v1_prefix)

    app.include_router(profile_router, prefix=settings.api_v1_prefix)

    app.include_router(rag_router, prefix=settings.api_v1_prefix)
    app.include_router(skills_router, prefix=settings.api_v1_prefix)

    return app





app = create_app()
