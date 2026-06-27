from app.agents.graph import run_supervisor_graph
from app.models.schemas import RagSource
from app.services.rag_service import RagSearchResult


class FakeRagService:
    def search(self, **kwargs):
        return RagSearchResult(
            sources=[
                RagSource(
                    document_id="doc_1",
                    chunk_id="chunk_1",
                    title="减脂训练指南",
                    source_uri="fitness.md",
                    relevance_score=0.88,
                    excerpt="减脂训练建议结合力量训练和有氧训练。",
                )
            ]
        )


def test_fitness_agent_uses_rag_sources_when_available() -> None:
    result = run_supervisor_graph(
        message="我想做减脂训练",
        thread_id="thread_fitness_rag",
        run_id="run_test",
        user_id="user_1",
        rag_service=FakeRagService(),
    )

    assert result["route"] == "fitness"
    assert result["rag_sources"][0].document_id == "doc_1"
    assert "知识库依据" in result["response"]
    assert "减脂训练指南" in result["response"]
