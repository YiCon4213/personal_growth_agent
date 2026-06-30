import asyncio
import math

import pytest

from app.services.rag_service import split_text_into_chunks
from evaluation.ragas_experiment import (
    EvaluationResult,
    CollectedRow,
    corpus_documents,
    dashscope_compatible_base_url,
    load_cases,
    replace_vector_corpus,
    summarize_results,
)


def test_evaluation_assets_have_broad_maintained_coverage() -> None:
    documents = corpus_documents()
    cases = load_cases()

    assert len(documents) == 12
    assert len(cases) == 30
    assert sum(len(split_text_into_chunks(content)) for _, _, content in documents) >= 12
    assert {case.category for case in cases} >= {
        "activity_guideline",
        "strength",
        "beginner_plan",
        "squat",
        "running",
        "recovery",
        "nutrition",
        "safety",
        "older_adult",
        "warmup_mobility",
    }
    titles = {title for _, title, _ in documents}
    assert all(set(case.expected_sources).issubset(titles) for case in cases)
def test_collected_row_restores_structures_from_ragas_csv() -> None:
    row = CollectedRow.model_validate(
        {
            "case_id": "case",
            "category": "test",
            "difficulty": "fact",
            "user_input": "question",
            "response": "answer",
            "retrieved_contexts": "['context']",
            "retrieved_titles": "['title']",
            "reference": "reference",
            "expected_sources": "['title']",
            "rag_trace": "{'pipeline': 'advanced_rag_v1'}",
        }
    )

    assert row.retrieved_contexts == ["context"]
    assert row.rag_trace == {"pipeline": "advanced_rag_v1"}




def test_dashscope_native_url_is_converted_for_openai_compatible_evaluation() -> None:
    assert dashscope_compatible_base_url(
        "https://dashscope.aliyuncs.com/api/v1"
    ) == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert dashscope_compatible_base_url(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/"
    ) == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_corpus_replacement_requires_explicit_confirmation() -> None:
    with pytest.raises(RuntimeError, match="--replace"):
        asyncio.run(replace_vector_corpus(object(), confirmed=False))  # type: ignore[arg-type]


def test_summary_marks_noise_as_lower_is_better_and_ignores_failed_values() -> None:
    row = EvaluationResult(
        case_id="case",
        category="test",
        difficulty="fact",
        user_input="question",
        response="answer",
        retrieved_contexts=["context"],
        retrieved_titles=["title"],
        reference="reference",
        faithfulness=1.0,
        answer_relevancy=0.8,
        context_precision=0.9,
        context_entity_recall=math.nan,
        noise_sensitivity=0.1,
        context_recall=0.7,
        metric_errors={"context_entity_recall": "provider failure"},
    )

    summary = summarize_results([row])

    assert summary["metric_means"]["faithfulness"] == 1.0
    assert summary["metric_means"]["context_entity_recall"] is None
    assert summary["metric_direction"]["noise_sensitivity"] == "lower_is_better"
    assert summary["failed_metric_calls"] == 1
