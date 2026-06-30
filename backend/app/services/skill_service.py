from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Message as MessageModel
from app.db.models import SkillCandidate as SkillCandidateModel
from app.db.models import UserSkill as UserSkillModel
from app.models.schemas import (
    CandidateStatus,
    ErrorCode,
    MessageRole,
    SkillCandidate,
    SkillStatus,
    UserSkill,
)
from app.services.data_store import DataStore

TRIGGER_TURN_INTERVAL = 10

LEARNING_HINTS = ("学习", "python", "后端", "编程", "课程", "复习", "考试")
FITNESS_HINTS = ("健身", "训练", "锻炼", "减脂", "增肌", "体重", "膝盖", "腰")
LIFE_HINTS = ("提醒", "日程", "待办", "作息", "早上", "晚上", "睡")
DETAIL_HINTS = ("喜欢详细", "讲详细", "一步步", "慢慢解释")
CONCISE_HINTS = ("简单说", "简洁", "少废话")


class SkillServiceError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class GeneratedSkillDraft:
    title: str
    content: str
    applicable_scenarios: list[str]
    turn_count: int


def skill_candidate_to_schema(candidate: SkillCandidateModel) -> SkillCandidate:
    return SkillCandidate(
        id=candidate.id,
        user_id=candidate.user_id,
        title=candidate.title,
        content=candidate.content,
        applicable_scenarios=list(candidate.applicable_scenarios or []),
        source_thread_id=candidate.source_thread_id,
        status=CandidateStatus(candidate.status),
        created_at=candidate.created_at,
    )


def skill_to_schema(skill: UserSkillModel) -> UserSkill:
    return UserSkill(
        id=skill.id,
        user_id=skill.user_id,
        title=skill.title,
        content=skill.content,
        applicable_scenarios=list(skill.applicable_scenarios or []),
        status=SkillStatus(skill.status),
        source_thread_id=skill.source_thread_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


class SkillService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.store = DataStore(session)

    def record_user_message(self, *, user_id: str, thread_id: str, message: str) -> MessageModel:
        return self.store.add_message(
            thread_id,
            MessageRole.USER,
            message,
            user_id=user_id,
            metadata={"effective_for_skill": True},
        )

    def record_assistant_message(self, *, user_id: str, thread_id: str, message: str) -> MessageModel:
        return self.store.add_message(
            thread_id,
            MessageRole.ASSISTANT,
            message,
            user_id=user_id,
            metadata={"generated_by": "supervisor_graph"},
        )

    def maybe_generate_candidate(self, *, user_id: str, thread_id: str) -> SkillCandidateModel | None:
        messages = list(self.store.list_messages(thread_id))
        effective_user_messages = [
            message for message in messages if message.role == MessageRole.USER.value and message.content.strip()
        ]
        turn_count = len(effective_user_messages)
        if turn_count == 0 or turn_count % TRIGGER_TURN_INTERVAL != 0:
            return None
        if self.store.find_skill_candidate_for_turn(user_id, thread_id, turn_count) is not None:
            return None
        if self.store.find_skill_for_turn(user_id, thread_id, turn_count) is not None:
            return None

        recent_user_messages = effective_user_messages[-TRIGGER_TURN_INTERVAL:]
        draft = generate_skill_draft(recent_user_messages, turn_count=turn_count)
        return self.store.create_skill_candidate(
            user_id,
            draft.title,
            draft.content,
            applicable_scenarios=draft.applicable_scenarios,
            source_thread_id=thread_id,
            metadata={
                "turn_count": turn_count,
                "source_message_count": len(recent_user_messages),
                "summary_only": True,
            },
        )

    def list_skills(self, user_id: str, *, enabled_only: bool = True) -> list[UserSkillModel]:
        return list(self.store.list_skills(user_id, enabled_only=enabled_only))

    def list_candidates(
        self,
        user_id: str,
        *,
        status: CandidateStatus | str | None = CandidateStatus.PENDING,
    ) -> list[SkillCandidateModel]:
        return list(self.store.list_skill_candidates(user_id, status=status))

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        user_id: str | None = None,
    ) -> tuple[SkillCandidateModel, UserSkillModel]:
        candidate = self._get_pending_candidate(candidate_id, user_id=user_id)
        existing = self.store.find_skill_by_title(candidate.user_id, candidate.title)
        if existing is None:
            existing = self.store.create_skill(
                candidate.user_id,
                candidate.title,
                candidate.content,
                applicable_scenarios=list(candidate.applicable_scenarios or []),
                source_thread_id=candidate.source_thread_id,
                status=SkillStatus.ENABLED,
                metadata={
                    "source_candidate_id": candidate.id,
                    "turn_count": candidate.metadata_json.get("turn_count"),
                },
            )
        candidate.status = CandidateStatus.APPROVED.value
        self.session.flush()
        return candidate, existing

    def reject_candidate(
        self,
        candidate_id: str,
        *,
        user_id: str | None = None,
    ) -> SkillCandidateModel:
        candidate = self._get_pending_candidate(candidate_id, user_id=user_id)
        candidate.status = CandidateStatus.REJECTED.value
        self.session.flush()
        return candidate

    def disable_skill(self, skill_id: str, *, user_id: str) -> UserSkillModel:
        skill = self.store.disable_skill(user_id, skill_id)
        if skill is None:
            raise SkillServiceError(ErrorCode.NOT_FOUND, "Skill was not found.", {"skill_id": skill_id})
        return skill

    def relevant_skill_context(self, user_id: str, message: str, *, limit: int = 3) -> list[dict[str, Any]]:
        scenarios = relevant_scenarios_for_message(message)
        skills = []
        for skill in self.store.list_skills(user_id, enabled_only=True):
            skill_scenarios = set(skill.applicable_scenarios or [])
            if not scenarios or skill_scenarios.intersection(scenarios):
                skills.append(skill)
        return [skill_to_schema(skill).model_dump(mode="json") for skill in skills[:limit]]

    def _get_pending_candidate(self, candidate_id: str, *, user_id: str | None) -> SkillCandidateModel:
        candidate = self.store.get_skill_candidate(candidate_id)
        if candidate is None:
            raise SkillServiceError(ErrorCode.NOT_FOUND, "Skill candidate was not found.", {"candidate_id": candidate_id})
        if user_id is not None and candidate.user_id != user_id:
            raise SkillServiceError(ErrorCode.NOT_FOUND, "Skill candidate was not found.", {"candidate_id": candidate_id})
        if candidate.status != CandidateStatus.PENDING.value:
            raise SkillServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Skill candidate is no longer pending.",
                {"candidate_id": candidate_id, "status": candidate.status},
            )
        return candidate


def generate_skill_draft(messages: list[MessageModel], *, turn_count: int) -> GeneratedSkillDraft:
    texts = [message.content for message in messages]
    combined = "\n".join(texts).lower()
    original_combined = "\n".join(texts)
    scenarios = relevant_scenarios_for_message(original_combined) or ["general planning"]

    preference = infer_preference(original_combined)
    template = infer_plan_template(original_combined, scenarios)
    decision_rule = infer_decision_rule(original_combined, scenarios)
    long_term_goal = infer_long_term_goal(original_combined, scenarios)
    reminder_rule = infer_reminder_rule(original_combined, scenarios)

    title = build_title(scenarios, turn_count)
    content = "\n".join(
        [
            "偏好：" + preference,
            "常用计划模板：" + template,
            "决策规则：" + decision_rule,
            "长期目标：" + long_term_goal,
            "提醒规则：" + reminder_rule,
        ]
    )
    return GeneratedSkillDraft(
        title=title,
        content=content,
        applicable_scenarios=scenarios,
        turn_count=turn_count,
    )


def relevant_scenarios_for_message(message: str) -> list[str]:
    normalized = message.lower()
    scenarios: list[str] = []
    if any(keyword in normalized or keyword in message for keyword in LEARNING_HINTS):
        scenarios.append("learning planning")
    if any(keyword in normalized or keyword in message for keyword in FITNESS_HINTS):
        scenarios.append("fitness guidance")
    if any(keyword in normalized or keyword in message for keyword in LIFE_HINTS):
        scenarios.append("life planning")
    if any(keyword in message for keyword in DETAIL_HINTS + CONCISE_HINTS):
        scenarios.append("communication style")
    return scenarios


def infer_preference(message: str) -> str:
    if any(keyword in message for keyword in DETAIL_HINTS):
        return "回答时优先给出分步骤说明，并补充必要背景。"
    if any(keyword in message for keyword in CONCISE_HINTS):
        return "回答时先给结论，再给少量关键步骤。"
    if "晚上" in message:
        return "计划安排可优先考虑晚间专注时段。"
    if "早上" in message:
        return "计划安排可优先考虑早间启动任务。"
    return "偏好可执行、能复盘的小步计划。"


def infer_plan_template(message: str, scenarios: list[str]) -> str:
    if "learning planning" in scenarios:
        return "目标拆解 -> 周计划 -> 每日最小任务 -> 周复盘问题。"
    if "fitness guidance" in scenarios:
        return "目标确认 -> 周训练安排 -> 动作与强度 -> 恢复和风险提醒。"
    if "life planning" in scenarios:
        return "今日优先级 -> 时间块 -> 工具/提醒动作 -> 晚间复盘。"
    return "先确认目标，再拆成短周期任务，并保留复盘节点。"


def infer_decision_rule(message: str, scenarios: list[str]) -> str:
    if "太紧" in message or "放慢" in message or "轻松" in message:
        return "当计划完成率下降或压力过高时，先减少范围，再延长周期。"
    if "fitness guidance" in scenarios:
        return "训练建议优先保证安全、动作标准和可恢复，再考虑强度提升。"
    if "learning planning" in scenarios:
        return "学习建议优先产出可运行练习或作品，而不是只堆资料。"
    return "多个选择冲突时，优先选择成本低、可验证、能持续的一步。"


def infer_long_term_goal(message: str, scenarios: list[str]) -> str:
    lower = message.lower()
    if "python" in lower and "后端" in message:
        return "持续推进 Python 后端能力建设。"
    if "python" in lower:
        return "持续提升 Python 编程能力。"
    if "减脂" in message:
        return "以可持续方式推进减脂和体能改善。"
    if "增肌" in message:
        return "以渐进训练推进增肌目标。"
    if "learning planning" in scenarios:
        return "保持长期学习节奏，并定期复盘调整。"
    if "fitness guidance" in scenarios:
        return "保持长期训练习惯，并避免伤病风险。"
    return "把长期目标沉淀为稳定、可重复执行的行动系统。"


def infer_reminder_rule(message: str, scenarios: list[str]) -> str:
    if "复盘" in message or "总结" in message:
        return "每个周期结束时提醒复盘完成率、卡点和下个周期第一步。"
    if "fitness guidance" in scenarios:
        return "涉及疼痛、疲劳或伤病时提醒降低强度并寻求专业建议。"
    if "learning planning" in scenarios:
        return "每周提醒检查产出物、薄弱点和下周任务量是否过载。"
    return "当计划超过一周时，提醒设置检查点和调整规则。"


def build_title(scenarios: list[str], turn_count: int) -> str:
    if "learning planning" in scenarios and "fitness guidance" in scenarios:
        prefix = "学习与健身节奏"
    elif "learning planning" in scenarios:
        prefix = "学习规划偏好"
    elif "fitness guidance" in scenarios:
        prefix = "健身指导偏好"
    elif "life planning" in scenarios:
        prefix = "生活计划偏好"
    else:
        prefix = "个人成长偏好"
    return f"{prefix}（第 {turn_count} 轮沉淀）"
