from app.agents.graph import run_supervisor_graph
from app.agents.supervisor import classify_route


def test_supervisor_classifies_learning_requests() -> None:
    assert classify_route("我想三个月学完 Python 后端") == "learning"


def test_supervisor_classifies_learning_adjustment_requests() -> None:
    assert classify_route("计划太紧，帮我放慢") == "learning"


def test_supervisor_classifies_fitness_requests() -> None:
    assert classify_route("我现在 75kg，想减脂并安排训练") == "fitness"


def test_supervisor_classifies_general_exercise_benefit_as_fitness() -> None:
    assert classify_route("运动有什么好处") == "fitness"


def test_supervisor_classifies_shoulder_pain_as_fitness() -> None:
    assert classify_route("我的肩膀也有点痛") == "fitness"


def test_supervisor_classifies_life_tool_requests() -> None:
    assert classify_route("帮我查天气，并安排今天的学习和运动") == "life"


def test_supervisor_classifies_general_requests() -> None:
    assert classify_route("你好，今天聊点轻松的") == "general"


def test_graph_routes_to_learning_agent() -> None:
    result = run_supervisor_graph(
        message="我想学习 Python 后端",
        thread_id="thread_learning",
        run_id="run_test",
    )

    assert result["route"] == "learning"
    assert "学习规划 Agent 已生成结构化计划" in result["response"]
    assert result["learning_plan"]["goal"] == "Python 后端开发"
    assert [record["agent"] for record in result["status_records"]] == [
        "supervisor",
        "learning",
    ]


def test_graph_routes_to_fitness_agent() -> None:
    result = run_supervisor_graph(
        message="帮我做一个减脂训练计划",
        thread_id="thread_fitness",
        run_id="run_test",
    )

    assert result["route"] == "fitness"
    assert "健身指导 Agent 已接手" in result["response"]


def test_graph_routes_to_life_agent() -> None:
    result = run_supervisor_graph(
        message="帮我查天气并安排今天",
        thread_id="thread_life",
        run_id="run_test",
    )

    assert result["route"] == "life"
    assert "生活助手 Agent 已接手" in result["response"]


def test_graph_routes_general_conversation() -> None:
    result = run_supervisor_graph(
        message="你好",
        thread_id="thread_general",
        run_id="run_test",
    )

    assert result["route"] == "general"
    assert "普通对话" in result["response"]
