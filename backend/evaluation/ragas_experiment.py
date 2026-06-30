"""绕过业务聊天流程，直接评估项目真实 RAG 检索与回答质量。"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select

from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, create_session_factory
from app.db.models import RagChunk, RagDocument
from app.services.llm_service import DeepSeekLLMService
from app.services.rag_service import (
    DEFAULT_USER_ID,
    FitnessRagService,
    grounded_fitness_prompt,
)

EVALUATION_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVALUATION_DIR / "corpus"
CASES_PATH = EVALUATION_DIR / "rag_eval_cases.json"
ARTIFACT_ROOT = EVALUATION_DIR / "artifacts"
DATASET_NAME = "fitness_rag_eval"


class EvaluationCase(BaseModel):
    id: str
    category: str
    difficulty: str
    question: str
    reference: str
    expected_sources: list[str] = Field(default_factory=list)


class CollectedRow(BaseModel):
    case_id: str
    category: str
    difficulty: str
    user_input: str
    response: str
    retrieved_contexts: list[str]
    retrieved_titles: list[str]
    @field_validator(
        "retrieved_contexts",
        "retrieved_titles",
        "expected_sources",
        "rag_trace",
        mode="before",
    )
    @classmethod
    def parse_csv_structures(cls, value: Any) -> Any:
        return ast.literal_eval(value) if isinstance(value, str) else value

    reference: str
    expected_sources: list[str]
    rag_trace: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    case_id: str
    category: str
    difficulty: str
    user_input: str
    response: str
    retrieved_contexts: list[str]
    retrieved_titles: list[str]
    reference: str
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    noise_sensitivity: float
    context_recall: float
    context_entity_recall: float
    metric_errors: dict[str, str] = Field(default_factory=dict)


def load_cases(limit: int | None = None) -> list[EvaluationCase]:
    raw_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in raw_cases]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Evaluation case ids must be unique.")
    return cases[:limit] if limit is not None else cases


def corpus_documents() -> list[tuple[Path, str, str]]:
    documents: list[tuple[Path, str, str]] = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        first_line = content.splitlines()[0].strip()
        if not first_line.startswith("# "):
            raise ValueError(f"Corpus file must begin with an H1 title: {path.name}")
        documents.append((path, first_line[2:].strip(), content))
    if not documents:
        raise ValueError(f"No Markdown corpus files found in {CORPUS_DIR}")
    return documents


def validate_real_settings(settings: Settings) -> None:
    missing = []
    if not settings.database_url:
        missing.append("DATABASE_URL")
    if not settings.deepseek_api_key:
        missing.append("DEEPSEEK_API_KEY")
    if not settings.dashscope_api_key:
        missing.append("DASHSCOPE_API_KEY")
    if missing:
        raise RuntimeError(f"Missing real-provider configuration: {', '.join(missing)}")


async def replace_vector_corpus(settings: Settings, *, confirmed: bool) -> dict[str, int]:
    """在同一事务中删除 default_user 旧文档并导入本评估语料。"""
    if not confirmed:
        raise RuntimeError("Corpus replacement is destructive; pass --replace to confirm.")
    engine = create_database_engine(settings)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Real corpus replacement requires PostgreSQL/pgvector.")

    session_factory = create_session_factory(engine)
    llm = DeepSeekLLMService(settings)
    with session_factory() as session:
        old_documents = session.scalar(
            select(func.count()).select_from(RagDocument).where(
                RagDocument.user_id == DEFAULT_USER_ID
            )
        ) or 0
        try:
            session.execute(delete(RagDocument).where(RagDocument.user_id == DEFAULT_USER_ID))
            service = FitnessRagService(session, settings=settings, llm_service=llm)
            imported = 0
            for path, title, content in corpus_documents():
                await service.import_text_document_async(
                    user_id=DEFAULT_USER_ID,
                    title=title,
                    content=content,
                    source_uri=f"evaluation/corpus/{path.name}",
                    source_type="markdown",
                    metadata={"evaluation_corpus": True, "corpus_version": "2026-06-29"},
                )
                imported += 1
            chunk_count = session.scalar(
                select(func.count())
                .select_from(RagChunk)
                .join(RagDocument, RagDocument.id == RagChunk.document_id)
                .where(RagDocument.user_id == DEFAULT_USER_ID)
            ) or 0
            session.commit()
        except Exception:
            session.rollback()
            raise
    return {
        "deleted_documents": int(old_documents),
        "imported_documents": imported,
        "imported_chunks": int(chunk_count),
    }


async def generate_grounded_answer(
    llm: DeepSeekLLMService,
    *,
    question: str,
    sources: list[Any],
    no_match_reason: str | None,
) -> str:
    chunks = []
    async for token in llm.stream_text(
        [{"role": "user", "content": question}],
        system_prompt=grounded_fitness_prompt(sources, no_match_reason),
    ):
        chunks.append(token)
    answer = "".join(chunks).strip()
    if not answer:
        raise RuntimeError("DeepSeek returned an empty grounded answer.")
    return answer


def reset_dataset_file() -> None:
    dataset_path = ARTIFACT_ROOT / "datasets" / f"{DATASET_NAME}.csv"
    if dataset_path.exists():
        dataset_path.unlink()


async def collect_dataset(
    settings: Settings,
    *,
    limit: int | None,
    request_delay: float,
):
    from ragas import Dataset

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    reset_dataset_file()
    dataset = Dataset(
        name=DATASET_NAME,
        backend="local/csv",
        root_dir=str(ARTIFACT_ROOT),
        data_model=CollectedRow,
    )
    cases = load_cases(limit)
    session_factory = create_session_factory(create_database_engine(settings))
    llm = DeepSeekLLMService(settings)

    with session_factory() as session:
        service = FitnessRagService(session, settings=settings, llm_service=llm)
        for index, case in enumerate(cases, start=1):
            result = await service.search_async(
                user_id=DEFAULT_USER_ID,
                query=case.question,
                top_k=settings.rag_final_limit,
            )
            answer = await generate_grounded_answer(
                llm,
                question=case.question,
                sources=result.sources,
                no_match_reason=result.no_match_reason,
            )
            row = CollectedRow(
                case_id=case.id,
                category=case.category,
                difficulty=case.difficulty,
                user_input=case.question,
                response=answer,
                retrieved_contexts=[source.excerpt for source in result.sources],
                retrieved_titles=[source.title for source in result.sources],
                reference=case.reference,
                expected_sources=case.expected_sources,
                rag_trace=result.trace or {},
            )
            dataset.append(row)
            print(
                f"[{index}/{len(cases)}] collected {case.id}: "
                f"contexts={len(row.retrieved_contexts)}"
            )
            if request_delay and index < len(cases):
                await asyncio.sleep(request_delay)
    dataset.save()
    return dataset


def dashscope_compatible_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    if normalized.endswith("/compatible-mode/v1"):
        return normalized
    if normalized.endswith("/api/v1"):
        return normalized[: -len("/api/v1")] + "/compatible-mode/v1"
    return normalized + "/compatible-mode/v1"


def build_evaluators(settings: Settings) -> dict[str, Any]:
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextEntityRecall,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
        NoiseSensitivity,
    )

    llm_client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
    )
    embedding_client = AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=dashscope_compatible_base_url(settings.dashscope_base_url),
        timeout=settings.embedding_timeout_seconds,
    )
    evaluator_llm = llm_factory(
        model=settings.llm_model,
        client=llm_client,
        max_tokens=4096,
    )
    evaluator_embeddings = embedding_factory(
        "openai",
        model=settings.embedding_model,
        client=embedding_client,
    )
    return {
        "faithfulness": Faithfulness(llm=evaluator_llm),
        "answer_relevancy": AnswerRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings),

        "context_precision": ContextPrecision(llm=evaluator_llm),
        "context_entity_recall": ContextEntityRecall(llm=evaluator_llm),
        "noise_sensitivity": NoiseSensitivity(llm=evaluator_llm, mode="irrelevant"),
        "context_recall": ContextRecall(llm=evaluator_llm),
    }


async def metric_value(
    name: str,
    call: Callable[[], Awaitable[Any]],
    errors: dict[str, str],
) -> float:
    try:
        result = await call()
        return float(result.value)
    except Exception as exc:
        errors[name] = f"{exc.__class__.__name__}: {exc}"
        return math.nan


async def evaluate_dataset(settings: Settings, *, concurrency: int):
    from ragas import Dataset, experiment

    if concurrency < 1:
        raise ValueError("Evaluation concurrency must be at least 1.")
    dataset = Dataset.load(
        name=DATASET_NAME,
        backend="local/csv",
        root_dir=str(ARTIFACT_ROOT),
        data_model=CollectedRow,
    )
    if len(dataset) == 0:
        raise RuntimeError("Collected dataset is empty. Run collect first.")
    evaluators = build_evaluators(settings)
    semaphore = asyncio.Semaphore(concurrency)

    @experiment(experiment_model=EvaluationResult, name_prefix="fitness-rag-six-metrics")
    async def score_row(row: CollectedRow) -> EvaluationResult:
        async with semaphore:
            errors: dict[str, str] = {}
            common = {
                "user_input": row.user_input,
                "response": row.response,
                "retrieved_contexts": row.retrieved_contexts,
            }
            faithfulness = await metric_value(
                "faithfulness", lambda: evaluators["faithfulness"].ascore(**common), errors
            )
            answer_relevancy = await metric_value(
                "answer_relevancy",
                lambda: evaluators["answer_relevancy"].ascore(
                    user_input=row.user_input, response=row.response
                ),
                errors,
            )
            context_precision = await metric_value(
                "context_precision",
                lambda: evaluators["context_precision"].ascore(
                    user_input=row.user_input,
                    reference=row.reference,
                    retrieved_contexts=row.retrieved_contexts,
                ),
                errors,
            )
            context_entity_recall = await metric_value(
                "context_entity_recall",
                lambda: evaluators["context_entity_recall"].ascore(
                    reference=row.reference, retrieved_contexts=row.retrieved_contexts
                ),
                errors,
            )
            noise_sensitivity = await metric_value(
                "noise_sensitivity",
                lambda: evaluators["noise_sensitivity"].ascore(
                    user_input=row.user_input,
                    response=row.response,
                    reference=row.reference,
                    retrieved_contexts=row.retrieved_contexts,
                ),
                errors,
            )
            context_recall = await metric_value(
                "context_recall",
                lambda: evaluators["context_recall"].ascore(
                    user_input=row.user_input,
                    reference=row.reference,
                    retrieved_contexts=row.retrieved_contexts,
                ),
                errors,
            )

            print(f"evaluated {row.case_id}: errors={len(errors)}")
            return EvaluationResult(
                **row.model_dump(exclude={"expected_sources", "rag_trace"}),
                faithfulness=faithfulness,
                answer_relevancy=answer_relevancy,
                context_precision=context_precision,
                context_entity_recall=context_entity_recall,
                noise_sensitivity=noise_sensitivity,
                context_recall=context_recall,
                metric_errors=errors,
            )

    run_name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = await score_row.arun(dataset, name=run_name)
    summary = summarize_results(list(results))
    summary_path = ARTIFACT_ROOT / "experiments" / f"summary_{run_name}.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary: {summary_path}")
    return results


def summarize_results(rows: list[EvaluationResult]) -> dict[str, Any]:
    metric_names = (
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_entity_recall",
        "noise_sensitivity",
        "context_recall",
    )
    means: dict[str, float | None] = {}
    for name in metric_names:
        values = [float(getattr(row, name)) for row in rows]
        finite_values = [value for value in values if math.isfinite(value)]
        means[name] = round(sum(finite_values) / len(finite_values), 6) if finite_values else None
    return {
        "sample_count": len(rows),
        "metric_means": means,
        "metric_direction": {
            **{name: "higher_is_better" for name in metric_names if name != "noise_sensitivity"},
            "noise_sensitivity": "lower_is_better",
        },
        "failed_metric_calls": sum(len(row.metric_errors) for row in rows),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="真实健身 RAG 语料替换与 RAGAS 六指标评估。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="删除旧文档并导入评估语料。")
    prepare.add_argument("--replace", action="store_true")
    collect = subparsers.add_parser("collect", help="收集真实检索上下文和回答。")
    collect.add_argument("--limit", type=int)
    collect.add_argument("--request-delay", type=float, default=1.0)
    evaluate = subparsers.add_parser("evaluate", help="运行六个 RAGAS 指标。")
    evaluate.add_argument("--concurrency", type=int, default=1)
    run = subparsers.add_parser("run", help="依次 prepare、collect、evaluate。")
    run.add_argument("--replace", action="store_true")
    run.add_argument("--limit", type=int)
    run.add_argument("--request-delay", type=float, default=1.0)
    run.add_argument("--concurrency", type=int, default=1)
    return parser


async def async_main(args: argparse.Namespace) -> None:
    settings = get_settings()
    validate_real_settings(settings)
    started = time.perf_counter()
    if args.command == "prepare":
        print(await replace_vector_corpus(settings, confirmed=args.replace))
    elif args.command == "collect":
        dataset = await collect_dataset(
            settings, limit=args.limit, request_delay=args.request_delay
        )
        print(f"saved {len(dataset)} rows under {ARTIFACT_ROOT}")
    elif args.command == "evaluate":
        await evaluate_dataset(settings, concurrency=args.concurrency)
    else:
        print(await replace_vector_corpus(settings, confirmed=args.replace))
        dataset = await collect_dataset(
            settings, limit=args.limit, request_delay=args.request_delay
        )
        print(f"saved {len(dataset)} rows under {ARTIFACT_ROOT}")
        await evaluate_dataset(settings, concurrency=args.concurrency)
    print(f"elapsed_seconds={time.perf_counter() - started:.2f}")


def main() -> None:
    asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
