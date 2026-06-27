from app.agents.learning import build_learning_plan, parse_learning_request, render_learning_plan


def test_parse_learning_request_extracts_python_backend_plan() -> None:
    profile = parse_learning_request("我想 3 个月学完 Python 后端，每天 2 小时")

    assert profile.goal == "Python 后端开发"
    assert profile.total_weeks == 12
    assert profile.daily_hours == 2
    assert profile.study_days_per_week == 6
    assert profile.weekly_hours == 12
    assert profile.pace == "normal"


def test_build_learning_plan_is_structured_for_frontend() -> None:
    profile = parse_learning_request("我想 3 个月学完 Python 后端，每天 2 小时，零基础，偏项目实战")
    plan = build_learning_plan(profile)

    assert plan["goal"] == "Python 后端开发"
    assert plan["level"] == "零基础"
    assert plan["total_weeks"] == 12
    assert plan["weekly_hours"] == 12
    assert len(plan["phases"]) == 4
    assert len(plan["weekly_plan"]) == 12
    assert plan["weekly_plan"][0]["deliverable"] == "完成 Python 基础练习和 Git 提交"
    assert plan["daily_tasks"]
    assert plan["review_questions"]
    assert "每周" in plan["adjustment_advice"]


def test_render_learning_plan_contains_required_sections() -> None:
    profile = parse_learning_request("我想 3 个月学完 Python 后端，每天 2 小时")
    plan = build_learning_plan(profile)
    rendered = render_learning_plan(plan)

    assert "阶段路径" in rendered
    assert "前 6 周周计划" in rendered
    assert "每日任务模板" in rendered
    assert "复盘问题" in rendered
    assert "调整建议" in rendered


def test_learning_plan_adjusts_when_user_says_plan_is_too_tight() -> None:
    profile = parse_learning_request("计划太紧，帮我放慢")
    plan = build_learning_plan(profile)

    assert profile.is_adjustment is True
    assert plan["pace"] == "relaxed"
    assert plan["total_weeks"] >= 16
    assert plan["weekly_hours"] <= 9
    assert "宽松节奏" in plan["adjustment_advice"]


def test_learning_plan_uses_defaults_and_reports_missing_information() -> None:
    profile = parse_learning_request("帮我制定学习计划")
    plan = build_learning_plan(profile)

    assert plan["goal"] == "当前学习目标"
    assert "学习目标" in plan["missing_fields"]
    assert "截止时间" in plan["missing_fields"]
    assert "每周可投入时间" in plan["missing_fields"]
    assert plan["assumptions"]
