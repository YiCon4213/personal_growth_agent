"""Learning planning agent with deterministic parsing and structured output."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.agents.state import AgentStatusRecord, GraphState, render_profile_context_note, render_skill_context_note

Pace = Literal["relaxed", "normal", "intensive"]


@dataclass(frozen=True)
class LearningProfile:
    goal: str
    level: str
    total_weeks: int
    weekly_hours: float
    daily_hours: float | None
    study_days_per_week: int
    preferred_style: str
    pace: Pace
    missing_fields: list[str]
    assumptions: list[str]
    is_adjustment: bool


def parse_learning_request(message: str) -> LearningProfile:
    normalized = message.lower()
    missing_fields: list[str] = []
    assumptions: list[str] = []

    goal = _parse_goal(message)
    if goal == "当前学习目标":
        missing_fields.append("学习目标")
        assumptions.append("未说明具体学习目标，先按当前学习目标生成可替换模板。")

    level = _parse_level(message)
    if level == "有少量基础，需要系统化补齐":
        missing_fields.append("当前基础")
        assumptions.append("未说明当前基础，默认有少量基础但知识不够系统。")

    is_adjustment = any(keyword in normalized for keyword in ("太紧", "放慢", "轻松", "宽松"))
    pace = _parse_pace(normalized, is_adjustment)

    daily_hours = _parse_daily_hours(message)
    weekly_hours = _parse_weekly_hours(message)
    if weekly_hours is None and daily_hours is not None:
        study_days_per_week = 6 if daily_hours <= 2 else 5
        weekly_hours = daily_hours * study_days_per_week
    elif weekly_hours is None:
        missing_fields.append("每周可投入时间")
        daily_hours = 1.5
        study_days_per_week = 6
        weekly_hours = daily_hours * study_days_per_week
        assumptions.append("未说明投入时间，默认每周 6 天、每天 1.5 小时。")
    else:
        study_days_per_week = 5 if weekly_hours >= 10 else 4
        daily_hours = round(weekly_hours / study_days_per_week, 1)

    total_weeks = _parse_total_weeks(message)
    if total_weeks is None:
        if is_adjustment:
            total_weeks = 16
            assumptions.append("未说明原计划周期，先按 16 周宽松节奏重排。")
        else:
            total_weeks = 12
            missing_fields.append("截止时间")
            assumptions.append("未说明截止时间，默认按 12 周规划。")

    if is_adjustment:
        total_weeks = max(total_weeks, math.ceil(total_weeks * 1.3))
        weekly_hours = round(max(weekly_hours * 0.8, 4), 1)
        daily_hours = round(weekly_hours / study_days_per_week, 1)
        pace = "relaxed"

    preferred_style = _parse_preferred_style(message)
    if preferred_style == "项目驱动 + 小步复盘":
        missing_fields.append("偏好的学习方式")
        assumptions.append("未说明学习偏好，默认采用项目驱动、小步复盘。")

    return LearningProfile(
        goal=goal,
        level=level,
        total_weeks=total_weeks,
        weekly_hours=round(weekly_hours, 1),
        daily_hours=daily_hours,
        study_days_per_week=study_days_per_week,
        preferred_style=preferred_style,
        pace=pace,
        missing_fields=missing_fields,
        assumptions=assumptions,
        is_adjustment=is_adjustment,
    )


def build_learning_plan(profile: LearningProfile) -> dict[str, Any]:
    phases = _build_phases(profile)
    weekly_plan = _build_weekly_plan(profile, phases)
    daily_tasks = _build_daily_tasks(profile)
    review_questions = [
        "本周最卡住的概念是什么？能否用自己的话讲清楚？",
        "本周是否产出了可运行的小练习或项目提交？",
        "下周应该增加练习、补基础，还是推进新主题？",
    ]
    adjustment_advice = _build_adjustment_advice(profile)

    return {
        "goal": profile.goal,
        "level": profile.level,
        "total_weeks": profile.total_weeks,
        "weekly_hours": profile.weekly_hours,
        "daily_hours": profile.daily_hours,
        "study_days_per_week": profile.study_days_per_week,
        "preferred_style": profile.preferred_style,
        "pace": profile.pace,
        "missing_fields": profile.missing_fields,
        "assumptions": profile.assumptions,
        "phases": phases,
        "weekly_plan": weekly_plan,
        "daily_tasks": daily_tasks,
        "review_questions": review_questions,
        "adjustment_advice": adjustment_advice,
    }


def render_learning_plan(plan: dict[str, Any]) -> str:
    phase_lines = [
        f"- 第 {phase['start_week']}-{phase['end_week']} 周：{phase['title']}。{phase['focus']}"
        for phase in plan["phases"]
    ]
    weekly_lines = [
        f"- 第 {item['week']} 周：{item['theme']}；产出：{item['deliverable']}"
        for item in plan["weekly_plan"][:6]
    ]
    assumption_text = "；".join(plan["assumptions"]) if plan["assumptions"] else "信息充足，暂无额外假设。"
    missing_text = "、".join(plan["missing_fields"]) if plan["missing_fields"] else "暂无"

    return "\n".join(
        [
            f"学习规划 Agent 已生成结构化计划：{plan['goal']}",
            f"基础判断：{plan['level']}。周期：{plan['total_weeks']} 周。投入：每周约 {plan['weekly_hours']} 小时。",
            f"缺失信息：{missing_text}。默认假设：{assumption_text}",
            "阶段路径：",
            *phase_lines,
            "前 6 周周计划：",
            *weekly_lines,
            "每日任务模板：",
            *[f"- {task}" for task in plan["daily_tasks"]],
            "复盘问题：",
            *[f"- {question}" for question in plan["review_questions"]],
            f"调整建议：{plan['adjustment_advice']}",
        ]
    )


def learning_agent_node(state: GraphState) -> GraphState:
    profile = parse_learning_request(state["message"])
    plan = build_learning_plan(profile)
    records: list[AgentStatusRecord] = [
        {
            "agent": "learning",
            "status": "completed",
            "message": "Learning agent parsed the request and produced a structured study plan.",
        }
    ]
    return {
        "response": render_learning_plan(plan) + render_profile_context_note(state) + render_skill_context_note(state),
        "learning_plan": plan,
        "status_records": records,
    }


def _parse_goal(message: str) -> str:
    lower_message = message.lower()
    if "python" in lower_message and "后端" in message:
        return "Python 后端开发"
    if "python" in lower_message:
        return "Python 编程"
    if "后端" in message:
        return "后端开发"
    if "前端" in message or "react" in lower_message or "next.js" in lower_message:
        return "前端开发"
    if "英语" in message:
        return "英语学习"
    if "算法" in message:
        return "算法与数据结构"
    match = re.search(r"(?:学习|学完|掌握|入门|精通)([^，。,.！!？?]+)", message)
    if match:
        candidate = match.group(1).strip()
        generic_targets = {"计划", "路径", "方案", "方法"}
        if candidate and candidate not in generic_targets:
            return candidate[:30]
    return "当前学习目标"


def _parse_level(message: str) -> str:
    if any(keyword in message for keyword in ("零基础", "新手", "没基础", "小白")):
        return "零基础"
    if any(keyword in message for keyword in ("有基础", "学过", "入门过")):
        return "有基础"
    if any(keyword in message for keyword in ("工作经验", "进阶", "提升")):
        return "进阶"
    return "有少量基础，需要系统化补齐"


def _parse_pace(normalized: str, is_adjustment: bool) -> Pace:
    if is_adjustment:
        return "relaxed"
    if any(keyword in normalized for keyword in ("冲刺", "尽快", "高强度", "加速")):
        return "intensive"
    return "normal"


def _parse_daily_hours(message: str) -> float | None:
    match = re.search(r"每天\s*(\d+(?:\.\d+)?)\s*(?:个)?小时", message)
    if not match:
        match = re.search(r"每日\s*(\d+(?:\.\d+)?)\s*(?:个)?小时", message)
    return float(match.group(1)) if match else None


def _parse_weekly_hours(message: str) -> float | None:
    match = re.search(r"每周\s*(\d+(?:\.\d+)?)\s*(?:个)?小时", message)
    return float(match.group(1)) if match else None


def _parse_total_weeks(message: str) -> int | None:
    month_match = re.search(r"(\d+)\s*(?:个)?月", message)
    if month_match:
        return int(month_match.group(1)) * 4
    week_match = re.search(r"(\d+)\s*周", message)
    if week_match:
        return int(week_match.group(1))
    return None


def _parse_preferred_style(message: str) -> str:
    if "项目" in message or "实战" in message:
        return "项目驱动"
    if "视频" in message:
        return "视频课程 + 练习"
    if "书" in message or "文档" in message:
        return "文档阅读 + 代码练习"
    return "项目驱动 + 小步复盘"


def _build_phases(profile: LearningProfile) -> list[dict[str, Any]]:
    phase_count = 4 if profile.total_weeks >= 10 else 3
    base_span = max(1, profile.total_weeks // phase_count)
    phase_titles = _phase_titles_for_goal(profile.goal)
    phases = []
    start_week = 1
    for index in range(phase_count):
        end_week = profile.total_weeks if index == phase_count - 1 else min(
            profile.total_weeks,
            start_week + base_span - 1,
        )
        phases.append(
            {
                "start_week": start_week,
                "end_week": end_week,
                "title": phase_titles[index]["title"],
                "focus": phase_titles[index]["focus"],
            }
        )
        start_week = end_week + 1
    return phases


def _phase_titles_for_goal(goal: str) -> list[dict[str, str]]:
    if "Python" in goal or "后端" in goal:
        return [
            {"title": "语言与工具基础", "focus": "补齐 Python 语法、Git、命令行和调试习惯。"},
            {"title": "Web 后端核心", "focus": "学习 HTTP、FastAPI、接口设计、错误处理和测试。"},
            {"title": "数据与工程化", "focus": "练习数据库、ORM、配置管理、日志和项目结构。"},
            {"title": "综合项目与复盘", "focus": "完成一个可运行后端项目，整理 README 和复盘清单。"},
        ]
    return [
        {"title": "基础概念", "focus": "建立知识地图，补齐核心术语和基础练习。"},
        {"title": "主题突破", "focus": "围绕关键模块做专项练习和输出。"},
        {"title": "综合应用", "focus": "做一个小项目或作品，把知识串起来。"},
        {"title": "复盘巩固", "focus": "查漏补缺，形成长期复习节奏。"},
    ]


def _build_weekly_plan(profile: LearningProfile, phases: list[dict[str, Any]]) -> list[dict[str, str]]:
    weekly_plan = []
    for week in range(1, profile.total_weeks + 1):
        phase = next(item for item in phases if item["start_week"] <= week <= item["end_week"])
        weekly_plan.append(
            {
                "week": str(week),
                "theme": phase["title"],
                "deliverable": _deliverable_for_week(profile.goal, week, profile.total_weeks),
            }
        )
    return weekly_plan


def _deliverable_for_week(goal: str, week: int, total_weeks: int) -> str:
    if "Python" in goal or "后端" in goal:
        if week == 1:
            return "完成 Python 基础练习和 Git 提交"
        if week <= max(2, total_weeks // 3):
            return "完成一个命令行小工具或数据处理练习"
        if week <= max(4, total_weeks * 2 // 3):
            return "完成 2-3 个 FastAPI 接口和接口测试"
        return "完成一个带数据库的后端小项目并写复盘"
    if week == 1:
        return "整理目标地图和基础练习清单"
    if week == total_weeks:
        return "完成最终作品或总结文档"
    return "完成本周主题练习和一页复盘"


def _build_daily_tasks(profile: LearningProfile) -> list[str]:
    focus_minutes = int((profile.daily_hours or 1.5) * 60)
    if focus_minutes < 60:
        return [
            "10 分钟回顾昨天卡点",
            f"{max(focus_minutes - 20, 25)} 分钟学习一个小主题",
            "10 分钟写下当天结论和明天第一步",
        ]
    return [
        "15 分钟复习与整理问题",
        f"{max(focus_minutes - 45, 45)} 分钟学习/编码主任务",
        "20 分钟做练习或补测试",
        "10 分钟记录复盘和下次启动点",
    ]


def _build_adjustment_advice(profile: LearningProfile) -> str:
    if profile.is_adjustment:
        return "已按更宽松节奏重排：延长周期、降低每周负荷，并保留每周缓冲时间。"
    if profile.weekly_hours < 6:
        return "投入时间偏少，建议减少同时学习的主题，每周只追一个核心产出。"
    if profile.pace == "intensive":
        return "当前是冲刺节奏，建议每周至少保留半天复盘和休息，避免只赶进度。"
    return "每周根据复盘结果微调：如果连续两周任务完成率低于 70%，先减少范围而不是增加时长。"
