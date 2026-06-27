from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ProfileCandidate as ProfileCandidateModel
from app.db.models import UserProfileItem as UserProfileItemModel
from app.models.schemas import (
    CandidateStatus,
    ErrorCode,
    ProfileCandidate,
    ProfileCategory,
    UserProfileItem,
)
from app.services.data_store import DataStore

SENSITIVE_WORDS = (
    "身份证",
    "银行卡",
    "密码",
    "验证码",
    "住址",
    "家庭住址",
    "手机号",
    "电话",
    "邮箱密码",
)

LEARNING_HINTS = ("学习", "学", "课程", "考试", "复习", "python", "后端", "编程")
FITNESS_HINTS = ("健身", "训练", "锻炼", "减脂", "增肌", "体重", "膝盖", "腰", "疼", "痛")
LIFE_HINTS = ("作息", "起床", "睡", "日程", "提醒", "待办", "晚上", "早上")


class ProfileServiceError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ExtractedProfileCandidate:
    category: ProfileCategory
    content: str
    confidence: float
    source_summary: str
    metadata: dict[str, Any]


def profile_candidate_to_schema(candidate: ProfileCandidateModel) -> ProfileCandidate:
    confidence = None if candidate.confidence is None else max(0, min(candidate.confidence, 100)) / 100
    return ProfileCandidate(
        id=candidate.id,
        user_id=candidate.user_id,
        category=ProfileCategory(candidate.category),
        content=candidate.content,
        confidence=confidence,
        source_summary=candidate.source_summary,
        source_thread_id=candidate.source_thread_id,
        status=CandidateStatus(candidate.status),
        created_at=candidate.created_at,
    )


def profile_item_to_schema(item: UserProfileItemModel) -> UserProfileItem:
    return UserProfileItem(
        id=item.id,
        user_id=item.user_id,
        category=ProfileCategory(item.category),
        content=item.content,
        source_summary=item.source_summary,
        source_thread_id=item.source_thread_id,
        enabled=item.enabled,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class ProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.store = DataStore(session)

    def extract_candidates_from_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        message: str,
    ) -> list[ProfileCandidateModel]:
        extracted = extract_profile_candidates(message, thread_id=thread_id)
        candidates: list[ProfileCandidateModel] = []
        for item in extracted:
            if self.store.find_profile_item_by_content(user_id, item.category, item.content):
                continue
            existing = self.store.find_profile_candidate_by_content(
                user_id,
                item.category,
                item.content,
                statuses=[CandidateStatus.PENDING, CandidateStatus.APPROVED],
            )
            if existing is not None:
                continue
            candidates.append(
                self.store.create_profile_candidate(
                    user_id,
                    item.category,
                    item.content,
                    item.source_summary,
                    confidence=item.confidence,
                    source_thread_id=thread_id,
                    metadata=item.metadata,
                )
            )
        return candidates

    def list_profile_items(self, user_id: str, *, enabled_only: bool = True) -> list[UserProfileItemModel]:
        return list(self.store.list_profile_items(user_id, enabled_only=enabled_only))

    def list_candidates(
        self,
        user_id: str,
        *,
        status: CandidateStatus | str | None = CandidateStatus.PENDING,
    ) -> list[ProfileCandidateModel]:
        return list(self.store.list_profile_candidates(user_id, status=status))

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        user_id: str | None = None,
    ) -> tuple[ProfileCandidateModel, UserProfileItemModel]:
        candidate = self._get_pending_candidate(candidate_id, user_id=user_id)
        existing = self.store.find_profile_item_by_content(candidate.user_id, candidate.category, candidate.content)
        if existing is None:
            existing = self.store.create_profile_item(
                candidate.user_id,
                candidate.category,
                candidate.content,
                candidate.source_summary,
                source_thread_id=candidate.source_thread_id,
                metadata={"source_candidate_id": candidate.id},
            )
        candidate.status = CandidateStatus.APPROVED.value
        self.session.flush()
        return candidate, existing

    def reject_candidate(
        self,
        candidate_id: str,
        *,
        user_id: str | None = None,
    ) -> ProfileCandidateModel:
        candidate = self._get_pending_candidate(candidate_id, user_id=user_id)
        candidate.status = CandidateStatus.REJECTED.value
        self.session.flush()
        return candidate

    def disable_profile_item(self, item_id: str, *, user_id: str) -> UserProfileItemModel:
        item = self.store.disable_profile_item(user_id, item_id)
        if item is None:
            raise ProfileServiceError(ErrorCode.NOT_FOUND, "Profile item was not found.", {"item_id": item_id})
        return item

    def delete_profile_item(self, item_id: str, *, user_id: str) -> None:
        deleted = self.store.delete_profile_item(user_id, item_id)
        if not deleted:
            raise ProfileServiceError(ErrorCode.NOT_FOUND, "Profile item was not found.", {"item_id": item_id})

    def relevant_profile_context(self, user_id: str, message: str, *, limit: int = 5) -> list[dict[str, Any]]:
        categories = relevant_categories_for_message(message)
        items = [
            item
            for item in self.store.list_profile_items(user_id, enabled_only=True)
            if ProfileCategory(item.category) in categories
        ]
        return [profile_item_to_schema(item).model_dump(mode="json") for item in items[:limit]]

    def _get_pending_candidate(self, candidate_id: str, *, user_id: str | None) -> ProfileCandidateModel:
        candidate = self.store.get_profile_candidate(candidate_id)
        if candidate is None:
            raise ProfileServiceError(ErrorCode.NOT_FOUND, "Profile candidate was not found.", {"candidate_id": candidate_id})
        if user_id is not None and candidate.user_id != user_id:
            raise ProfileServiceError(ErrorCode.NOT_FOUND, "Profile candidate was not found.", {"candidate_id": candidate_id})
        if candidate.status != CandidateStatus.PENDING.value:
            raise ProfileServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Profile candidate is no longer pending.",
                {"candidate_id": candidate_id, "status": candidate.status},
            )
        return candidate


def extract_profile_candidates(message: str, *, thread_id: str) -> list[ExtractedProfileCandidate]:
    if is_sensitive_message(message):
        return []
    source_summary = build_source_summary(message, thread_id)
    candidates: list[ExtractedProfileCandidate] = []

    efficiency_match = re.search(r"(晚上\s*\d{1,2}\s*点后).{0,12}(学习效率高|效率高|适合学习)", message)
    if efficiency_match:
        candidates.append(
            ExtractedProfileCandidate(
                category=ProfileCategory.LEARNING,
                content=f"{efficiency_match.group(1).replace(' ', '')}学习效率高",
                confidence=0.9,
                source_summary=source_summary,
                metadata={"rule": "learning_evening_efficiency"},
            )
        )

    if any(keyword in message.lower() for keyword in ("python", "后端", "编程")) and any(
        marker in message for marker in ("想", "目标", "计划", "学完", "学习")
    ):
        goal = "Python 后端开发" if "后端" in message and "python" in message.lower() else "Python 编程"
        candidates.append(
            ExtractedProfileCandidate(
                category=ProfileCategory.LEARNING,
                content=f"学习目标：{goal}",
                confidence=0.75,
                source_summary=source_summary,
                metadata={"rule": "learning_goal"},
            )
        )

    if "减脂" in message or "增肌" in message:
        goal = "减脂" if "减脂" in message else "增肌"
        candidates.append(
            ExtractedProfileCandidate(
                category=ProfileCategory.FITNESS,
                content=f"健身目标：{goal}",
                confidence=0.8,
                source_summary=source_summary,
                metadata={"rule": "fitness_goal"},
            )
        )

    limitation_match = re.search(r"(膝盖|腰|肩|手腕).{0,8}(疼|痛|受伤|不舒服|限制)", message)
    if limitation_match:
        candidates.append(
            ExtractedProfileCandidate(
                category=ProfileCategory.LIMITATION,
                content=f"身体限制：{limitation_match.group(0)}",
                confidence=0.78,
                source_summary=source_summary,
                metadata={"rule": "body_limitation"},
            )
        )

    if any(keyword in message for keyword in ("喜欢详细", "讲详细", "一步步", "慢慢解释")):
        candidates.append(
            ExtractedProfileCandidate(
                category=ProfileCategory.COMMUNICATION,
                content="沟通偏好：喜欢详细、一步步解释",
                confidence=0.82,
                source_summary=source_summary,
                metadata={"rule": "communication_detail"},
            )
        )
    elif any(keyword in message for keyword in ("简单说", "简洁", "少废话")):
        candidates.append(
            ExtractedProfileCandidate(
                category=ProfileCategory.COMMUNICATION,
                content="沟通偏好：喜欢简洁直接的回答",
                confidence=0.82,
                source_summary=source_summary,
                metadata={"rule": "communication_concise"},
            )
        )

    return candidates


def is_sensitive_message(message: str) -> bool:
    return any(word in message for word in SENSITIVE_WORDS)


def build_source_summary(message: str, thread_id: str) -> str:
    normalized = " ".join(message.split())
    if len(normalized) > 80:
        normalized = normalized[:77] + "..."
    return f"用户在会话 {thread_id} 中表示：{normalized}"


def relevant_categories_for_message(message: str) -> set[ProfileCategory]:
    normalized = message.lower()
    if any(keyword in normalized or keyword in message for keyword in LEARNING_HINTS):
        return {ProfileCategory.LEARNING, ProfileCategory.PREFERENCE, ProfileCategory.LIMITATION, ProfileCategory.COMMUNICATION}
    if any(keyword in normalized or keyword in message for keyword in FITNESS_HINTS):
        return {ProfileCategory.FITNESS, ProfileCategory.LIMITATION, ProfileCategory.PREFERENCE, ProfileCategory.COMMUNICATION}
    if any(keyword in normalized or keyword in message for keyword in LIFE_HINTS):
        return {ProfileCategory.LIFE, ProfileCategory.PREFERENCE, ProfileCategory.COMMUNICATION}
    return {ProfileCategory.PREFERENCE, ProfileCategory.COMMUNICATION, ProfileCategory.LIFE}
