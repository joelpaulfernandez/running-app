"""
LangGraph coaching-explanation agent.
Trigger: ACWR cap (proactive) | missed-session reschedule | VDOT recalc (on-demand).
Context window: trigger event + last 4 weeks of session data.
Output: 2-4 sentence inline text card.
"""
from typing import Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import os
import json


SYSTEM_PROMPT = """You are a concise running coach assistant.
Explain training plan changes in 2-4 sentences. Be direct and data-driven.
Reference the specific numbers (ACWR, VDOT, distances).
No cheerleading. No filler. Just the why and what to expect."""


def build_coach_graph():
    llm = ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        max_tokens=300,
    )

    def explain_node(state: dict) -> dict:
        trigger = state["trigger"]
        context = state["context"]
        explanation = state.get("system_explanation", "")

        context_str = json.dumps(context, indent=2, default=str)
        prompt = f"""Trigger: {trigger}
System explanation: {explanation}

Last 4 weeks of training data:
{context_str}

Explain this change to the athlete in 2-4 sentences."""

        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        return {**state, "coach_note": response.content}

    graph = StateGraph(dict)
    graph.add_node("explain", explain_node)
    graph.set_entry_point("explain")
    graph.add_edge("explain", END)
    return graph.compile()


_coach_graph = None


def get_coach_note(
    trigger: str,
    system_explanation: str,
    recent_sessions: list[dict],
) -> str:
    """
    trigger: "acwr_cap" | "missed_session" | "vdot_recalc"
    system_explanation: the rule-based reason string
    recent_sessions: last 4 weeks of planned+actual session data
    """
    global _coach_graph
    if _coach_graph is None:
        _coach_graph = build_coach_graph()

    state = {
        "trigger": trigger,
        "system_explanation": system_explanation,
        "context": recent_sessions,
    }
    result = _coach_graph.invoke(state)
    return result.get("coach_note", system_explanation)
