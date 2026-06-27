from __future__ import annotations



from collections.abc import Sequence

from typing import Any



from sqlalchemy import select

from sqlalchemy.orm import Session



from app.core.config import Settings, get_settings

from app.db.models import (

    ApprovalRequest,

    MCPServer,

    MCPTool,

    MCPToolCall,

    Message,

    ProfileCandidate,

    RagDocument,

    SkillCandidate,

    Thread,

    UserProfileItem,

    UserSkill,

)

from app.models.schemas import ApprovalStatus, CandidateStatus, MCPTransport, MessageRole, ProfileCategory, RiskLevel, SkillStatus





class DataStore:

    def __init__(self, session: Session, settings: Settings | None = None) -> None:

        self.session = session

        self.settings = settings or get_settings()



    def upsert_thread(

        self,

        thread_id: str,

        *,

        user_id: str | None = None,

        title: str | None = None,

        metadata: dict[str, Any] | None = None,

    ) -> Thread:

        thread = self.session.get(Thread, thread_id)

        if thread is None:

            thread = Thread(id=thread_id, user_id=user_id, title=title, metadata_json=metadata or {})

            self.session.add(thread)

        else:

            if user_id is not None:

                thread.user_id = user_id

            if title is not None:

                thread.title = title

            if metadata is not None:

                thread.metadata_json = metadata

        self.session.flush()

        return thread



    def get_thread(self, thread_id: str) -> Thread | None:

        return self.session.get(Thread, thread_id)



    def add_message(

        self,

        thread_id: str,

        role: MessageRole | str,

        content: str,

        *,

        user_id: str | None = None,

        metadata: dict[str, Any] | None = None,

    ) -> Message:

        self.upsert_thread(thread_id, user_id=user_id)

        role_value = role.value if isinstance(role, MessageRole) else role

        message = Message(

            thread_id=thread_id,

            role=role_value,

            content=content,

            metadata_json=metadata or {},

        )

        self.session.add(message)

        self.session.flush()

        return message



    def list_messages(self, thread_id: str) -> Sequence[Message]:

        statement = select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at)

        return self.session.scalars(statement).all()



    def create_profile_item(

        self,

        user_id: str,

        category: ProfileCategory | str,

        content: str,

        source_summary: str,

        *,

        source_thread_id: str | None = None,

        enabled: bool = True,

        metadata: dict[str, Any] | None = None,

    ) -> UserProfileItem:

        category_value = category.value if isinstance(category, ProfileCategory) else category

        item = UserProfileItem(

            user_id=user_id,

            category=category_value,

            content=content,

            source_summary=source_summary,

            source_thread_id=source_thread_id,

            enabled=enabled,

            metadata_json=metadata or {},

        )

        self.session.add(item)

        self.session.flush()

        return item



    def list_profile_items(self, user_id: str, *, enabled_only: bool = True) -> Sequence[UserProfileItem]:

        statement = select(UserProfileItem).where(UserProfileItem.user_id == user_id)

        if enabled_only:

            statement = statement.where(UserProfileItem.enabled.is_(True))

        return self.session.scalars(statement.order_by(UserProfileItem.created_at)).all()




    def create_profile_candidate(
        self,
        user_id: str,
        category: ProfileCategory | str,
        content: str,
        source_summary: str,
        *,
        confidence: float | None = None,
        source_thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProfileCandidate:
        category_value = category.value if isinstance(category, ProfileCategory) else category
        confidence_percent = None if confidence is None else int(round(max(0, min(confidence, 1)) * 100))
        candidate = ProfileCandidate(
            user_id=user_id,
            category=category_value,
            content=content,
            confidence=confidence_percent,
            source_summary=source_summary,
            source_thread_id=source_thread_id,
            status=CandidateStatus.PENDING.value,
            metadata_json=metadata or {},
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def get_profile_candidate(self, candidate_id: str) -> ProfileCandidate | None:
        return self.session.get(ProfileCandidate, candidate_id)

    def list_profile_candidates(
        self,
        user_id: str,
        *,
        status: CandidateStatus | str | None = CandidateStatus.PENDING,
    ) -> Sequence[ProfileCandidate]:
        statement = select(ProfileCandidate).where(ProfileCandidate.user_id == user_id)
        if status is not None:
            status_value = status.value if isinstance(status, CandidateStatus) else status
            statement = statement.where(ProfileCandidate.status == status_value)
        return self.session.scalars(statement.order_by(ProfileCandidate.created_at)).all()

    def find_profile_candidate_by_content(
        self,
        user_id: str,
        category: ProfileCategory | str,
        content: str,
        *,
        statuses: list[CandidateStatus | str] | None = None,
    ) -> ProfileCandidate | None:
        category_value = category.value if isinstance(category, ProfileCategory) else category
        status_values = [item.value if isinstance(item, CandidateStatus) else item for item in (statuses or [])]
        statement = select(ProfileCandidate).where(
            ProfileCandidate.user_id == user_id,
            ProfileCandidate.category == category_value,
            ProfileCandidate.content == content,
        )
        if status_values:
            statement = statement.where(ProfileCandidate.status.in_(status_values))
        return self.session.scalars(statement).first()

    def find_profile_item_by_content(
        self,
        user_id: str,
        category: ProfileCategory | str,
        content: str,
    ) -> UserProfileItem | None:
        category_value = category.value if isinstance(category, ProfileCategory) else category
        statement = select(UserProfileItem).where(
            UserProfileItem.user_id == user_id,
            UserProfileItem.category == category_value,
            UserProfileItem.content == content,
        )
        return self.session.scalars(statement).first()

    def disable_profile_item(self, user_id: str, item_id: str) -> UserProfileItem | None:
        item = self.session.get(UserProfileItem, item_id)
        if item is None or item.user_id != user_id:
            return None
        item.enabled = False
        self.session.flush()
        return item

    def delete_profile_item(self, user_id: str, item_id: str) -> bool:
        item = self.session.get(UserProfileItem, item_id)
        if item is None or item.user_id != user_id:
            return False
        self.session.delete(item)
        self.session.flush()
        return True
    def create_skill(

        self,

        user_id: str,

        title: str,

        content: str,

        *,

        applicable_scenarios: list[str] | None = None,

        source_thread_id: str | None = None,

        status: SkillStatus | str = SkillStatus.ENABLED,

        metadata: dict[str, Any] | None = None,

    ) -> UserSkill:

        status_value = status.value if isinstance(status, SkillStatus) else status

        skill = UserSkill(

            user_id=user_id,

            title=title,

            content=content,

            applicable_scenarios=applicable_scenarios or [],

            source_thread_id=source_thread_id,

            status=status_value,

            metadata_json=metadata or {},

        )

        self.session.add(skill)

        self.session.flush()

        return skill



    def list_skills(self, user_id: str, *, enabled_only: bool = True) -> Sequence[UserSkill]:

        statement = select(UserSkill).where(UserSkill.user_id == user_id)

        if enabled_only:

            statement = statement.where(UserSkill.status == SkillStatus.ENABLED.value)

        return self.session.scalars(statement.order_by(UserSkill.created_at)).all()



    def create_skill_candidate(
        self,
        user_id: str,
        title: str,
        content: str,
        *,
        applicable_scenarios: list[str] | None = None,
        source_thread_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SkillCandidate:
        candidate = SkillCandidate(
            user_id=user_id,
            title=title,
            content=content,
            applicable_scenarios=applicable_scenarios or [],
            source_thread_id=source_thread_id,
            status=CandidateStatus.PENDING.value,
            metadata_json=metadata or {},
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def get_skill_candidate(self, candidate_id: str) -> SkillCandidate | None:
        return self.session.get(SkillCandidate, candidate_id)

    def list_skill_candidates(
        self,
        user_id: str,
        *,
        status: CandidateStatus | str | None = CandidateStatus.PENDING,
    ) -> Sequence[SkillCandidate]:
        statement = select(SkillCandidate).where(SkillCandidate.user_id == user_id)
        if status is not None:
            status_value = status.value if isinstance(status, CandidateStatus) else status
            statement = statement.where(SkillCandidate.status == status_value)
        return self.session.scalars(statement.order_by(SkillCandidate.created_at)).all()

    def find_skill_candidate_for_turn(
        self,
        user_id: str,
        thread_id: str,
        turn_count: int,
    ) -> SkillCandidate | None:
        statement = select(SkillCandidate).where(
            SkillCandidate.user_id == user_id,
            SkillCandidate.source_thread_id == thread_id,
        )
        for candidate in self.session.scalars(statement).all():
            if (candidate.metadata_json or {}).get("turn_count") == turn_count:
                return candidate
        return None

    def find_skill_for_turn(
        self,
        user_id: str,
        thread_id: str,
        turn_count: int,
    ) -> UserSkill | None:
        statement = select(UserSkill).where(
            UserSkill.user_id == user_id,
            UserSkill.source_thread_id == thread_id,
        )
        for skill in self.session.scalars(statement).all():
            if (skill.metadata_json or {}).get("turn_count") == turn_count:
                return skill
        return None

    def find_skill_by_title(self, user_id: str, title: str) -> UserSkill | None:
        statement = select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.title == title)
        return self.session.scalars(statement).first()

    def disable_skill(self, user_id: str, skill_id: str) -> UserSkill | None:
        skill = self.session.get(UserSkill, skill_id)
        if skill is None or skill.user_id != user_id:
            return None
        skill.status = SkillStatus.DISABLED.value
        self.session.flush()
        return skill
    def create_mcp_server(

        self,

        user_id: str,

        name: str,

        endpoint_url: str,

        *,

        transport: MCPTransport | str = MCPTransport.HTTP,

        enabled: bool = True,

        metadata: dict[str, Any] | None = None,

    ) -> MCPServer:

        transport_value = transport.value if isinstance(transport, MCPTransport) else transport

        server = MCPServer(

            user_id=user_id,

            name=name,

            endpoint_url=endpoint_url,

            transport=transport_value,

            enabled=enabled,

            metadata_json=metadata or {},

        )

        self.session.add(server)

        self.session.flush()

        return server



    def list_mcp_servers(self, user_id: str, *, enabled_only: bool = False) -> Sequence[MCPServer]:

        statement = select(MCPServer).where(MCPServer.user_id == user_id)

        if enabled_only:

            statement = statement.where(MCPServer.enabled.is_(True))

        return self.session.scalars(statement.order_by(MCPServer.created_at)).all()



    def get_mcp_server(self, server_id: str) -> MCPServer | None:

        return self.session.get(MCPServer, server_id)



    def upsert_mcp_tool(

        self,

        server_id: str,

        name: str,

        *,

        description: str | None = None,

        input_schema: dict[str, Any] | None = None,

        risk_level: RiskLevel | str = RiskLevel.LOW,

        enabled: bool = True,

        metadata: dict[str, Any] | None = None,

    ) -> MCPTool:

        risk_value = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level

        statement = select(MCPTool).where(MCPTool.server_id == server_id, MCPTool.name == name)

        tool = self.session.scalars(statement).first()

        if tool is None:

            tool = MCPTool(server_id=server_id, name=name)

            self.session.add(tool)

        tool.description = description

        tool.input_schema = input_schema or {}

        tool.risk_level = risk_value

        tool.enabled = enabled

        tool.metadata_json = metadata or {}

        self.session.flush()

        return tool



    def list_mcp_tools(

        self,

        user_id: str,

        *,

        server_ids: list[str] | None = None,

        enabled_only: bool = True,

    ) -> Sequence[MCPTool]:

        statement = select(MCPTool).join(MCPServer, MCPTool.server_id == MCPServer.id).where(

            MCPServer.user_id == user_id

        )

        if server_ids:

            statement = statement.where(MCPTool.server_id.in_(server_ids))

        if enabled_only:

            statement = statement.where(MCPTool.enabled.is_(True), MCPServer.enabled.is_(True))

        return self.session.scalars(statement.order_by(MCPTool.created_at)).all()



    def get_mcp_tool_for_user(self, user_id: str, tool_id: str) -> MCPTool | None:

        statement = select(MCPTool).join(MCPServer, MCPTool.server_id == MCPServer.id).where(

            MCPServer.user_id == user_id, MCPTool.id == tool_id

        )

        return self.session.scalars(statement).first()



    def create_mcp_tool_call(

        self,

        user_id: str,

        server_id: str,

        tool_name: str,

        *,

        thread_id: str | None = None,

        tool_id: str | None = None,

        arguments: dict[str, Any] | None = None,

        output: dict[str, Any] | None = None,

        risk_level: RiskLevel | str = RiskLevel.LOW,

        status: str = "succeeded",

        error_message: str | None = None,

    ) -> MCPToolCall:

        risk_value = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level

        call = MCPToolCall(

            user_id=user_id,

            thread_id=thread_id,

            server_id=server_id,

            tool_id=tool_id,

            tool_name=tool_name,

            arguments=arguments or {},

            output=output or {},

            risk_level=risk_value,

            status=status,

            error_message=error_message,

        )

        self.session.add(call)

        self.session.flush()

        return call





    def create_approval_request(

        self,

        user_id: str,

        thread_id: str,

        server_id: str,

        tool_id: str,

        tool_name: str,

        arguments: dict[str, Any],

        *,

        risk_level: RiskLevel | str,

        expected_impact: str,

    ) -> ApprovalRequest:

        risk_value = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level

        approval = ApprovalRequest(

            user_id=user_id,

            thread_id=thread_id,

            server_id=server_id,

            tool_id=tool_id,

            tool_name=tool_name,

            arguments=arguments,

            risk_level=risk_value,

            expected_impact=expected_impact,

            status=ApprovalStatus.PENDING.value,

        )

        self.session.add(approval)

        self.session.flush()

        return approval



    def get_approval_request(self, approval_id: str) -> ApprovalRequest | None:

        return self.session.get(ApprovalRequest, approval_id)



    def list_approval_requests(

        self,

        user_id: str,

        *,

        status: ApprovalStatus | str | None = None,

    ) -> Sequence[ApprovalRequest]:

        statement = select(ApprovalRequest).where(ApprovalRequest.user_id == user_id)

        if status is not None:

            status_value = status.value if isinstance(status, ApprovalStatus) else status

            statement = statement.where(ApprovalRequest.status == status_value)

        return self.session.scalars(statement.order_by(ApprovalRequest.created_at)).all()

    def create_rag_document(

        self,

        user_id: str,

        title: str,

        *,

        source_uri: str | None = None,

        source_type: str | None = None,

        embedding_model: str | None = None,

        embedding_dimension: int | None = None,

        chunk_count: int = 0,

        metadata: dict[str, Any] | None = None,

    ) -> RagDocument:

        document = RagDocument(

            user_id=user_id,

            title=title,

            source_uri=source_uri,

            source_type=source_type,

            embedding_model=embedding_model or self.settings.embedding_model,

            embedding_dimension=embedding_dimension or self.settings.embedding_dimension,

            chunk_count=chunk_count,

            metadata_json=metadata or {},

        )

        self.session.add(document)

        self.session.flush()

        return document



    def list_rag_documents(self, user_id: str) -> Sequence[RagDocument]:

        statement = select(RagDocument).where(RagDocument.user_id == user_id).order_by(

            RagDocument.created_at

        )

        return self.session.scalars(statement).all()
