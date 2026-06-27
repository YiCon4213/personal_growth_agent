"""LangGraph supervisor skeleton for the personal growth assistant."""



from typing import Any



from langgraph.graph import END, START, StateGraph



from app.agents.fitness import fitness_agent_node

from app.agents.general import general_agent_node

from app.agents.learning import learning_agent_node

from app.agents.life import life_agent_node

from app.agents.state import GraphState

from app.agents.supervisor import select_next_agent, supervisor_node





def build_graph():

    graph_builder = StateGraph(GraphState)

    graph_builder.add_node("supervisor", supervisor_node)

    graph_builder.add_node("learning", learning_agent_node)

    graph_builder.add_node("fitness", fitness_agent_node)

    graph_builder.add_node("life", life_agent_node)

    graph_builder.add_node("general", general_agent_node)



    graph_builder.add_edge(START, "supervisor")

    graph_builder.add_conditional_edges(

        "supervisor",

        select_next_agent,

        {

            "learning": "learning",

            "fitness": "fitness",

            "life": "life",

            "general": "general",

        },

    )

    graph_builder.add_edge("learning", END)

    graph_builder.add_edge("fitness", END)

    graph_builder.add_edge("life", END)

    graph_builder.add_edge("general", END)

    return graph_builder.compile()





compiled_graph = build_graph()

graph = compiled_graph





def run_supervisor_graph(

    *,

    message: str,

    thread_id: str,

    run_id: str,

    user_id: str | None = None,

    rag_collection_ids: list[str] | None = None,

    rag_service: Any | None = None,

    enabled_mcp_server_ids: list[str] | None = None,

    mcp_service: Any | None = None,
    profile_context: list[dict[str, Any]] | None = None,
    skill_context: list[dict[str, Any]] | None = None,
) -> GraphState:

    initial_state: GraphState = {

        "message": message,

        "thread_id": thread_id,

        "user_id": user_id,

        "run_id": run_id,

        "rag_collection_ids": rag_collection_ids or [],

        "enabled_mcp_server_ids": enabled_mcp_server_ids or [],
        "profile_context": profile_context or [],
        "skill_context": skill_context or [],
        "status_records": [],

    }

    if rag_service is not None:

        initial_state["rag_service"] = rag_service

    if mcp_service is not None:

        initial_state["mcp_service"] = mcp_service

    return compiled_graph.invoke(initial_state)
