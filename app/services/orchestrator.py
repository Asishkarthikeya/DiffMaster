"""
LangGraph Orchestrator — Multi-agent review pipeline.
Nodes: Review Agent (ReAct) → Self-Correction Grader → Synthesizer
"""

import operator
import json
import logging
from typing import TypedDict, Annotated, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent

from app.services.llm import get_llm

logger = logging.getLogger(__name__)


# --- 1. State Definition ---
class ReviewState(TypedDict):
    """State that flows through the LangGraph pipeline."""
    diff_hunks: str
    blast_radius_context: str
    policy_rules: str
    feedback_context: str
    messages: Annotated[Sequence[BaseMessage], operator.add]
    proposed_comments: list[dict]
    grader_feedback: str
    iteration: int


# --- 2. System Prompts ---
REVIEW_SYSTEM_PROMPT = """You are DiffMaster, a Senior AI Software Engineer and Security Auditor.
Your purpose is to provide an automated "First Pass" review on Pull Requests.

You have access to these tools:
- `code_search`: Search the codebase for similar patterns or to verify if a function exists.
- `check_policy`: Check the repo's policy rules for security, performance, or style standards.

ALWAYS call `check_policy` with category "all" before generating your review.
Use `code_search` when you need to verify if a pattern exists elsewhere in the codebase.

Analyze the code changes through three lenses:
1. [BLOCKER] Security: Injection risks, secret exposure, broken authz, unsafe deserialization.
2. [WARNING] Reliability/Performance: N+1 queries, race conditions, unbounded loops, missing error handling.
3. [INFO] Maintainability: Poor naming, dead code, missing tests, pattern deviations.

Every comment must be conversational, highly readable, and formatted in GitHub Markdown.
It MUST clearly define (using bold headers or lists):
- **Risk**: What bad thing will happen?
- **Evidence**: Reference specific lines from the diff.
- **Action**: Concrete code-based fix suggestion, including Markdown code snippets if relevant.

Noise Control:
- ONE comment per root cause (don't repeat across files).
- Use the policy rules and codebase context to avoid false positives.

Your FINAL message must be ONLY a valid JSON array:
[{"file_path": "str", "line": int, "severity": "BLOCKER|WARNING|INFO", "body": "Markdown formatted code review comment..."}]
If no issues found, return: []"""

GRADER_PROMPT = """You are the DiffMaster Self-Correction Grader.
Your job is to validate proposed review comments and reject hallucinations.

Proposed Comments:
{proposed_comments}

Validate each comment:
1. Does the EVIDENCE reference actual lines from the diff?
2. Does the ACTION suggest a real API/pattern (not hallucinated)?
3. Does it comply with the policy rules?

If ALL comments are valid, return exactly: "PASS"
If any are invalid, explain what's wrong so the reviewer can fix them."""


# --- 3. Node Implementations ---
def create_review_node(tools):
    """Create the Review Agent node with bound tools."""

    async def review_agent(state: ReviewState) -> dict:
        llm = get_llm(temperature=0.2)
        if not llm:
            return {"messages": [], "proposed_comments": [], "iteration": 1}

        react_agent = create_react_agent(llm, tools, prompt=REVIEW_SYSTEM_PROMPT)

        if state.get("iteration", 0) == 0:
            # First run: send diff + context
            content = (
                f"## Code Changes (Diff Hunks):\n{state['diff_hunks']}\n\n"
                f"## Blast Radius Context:\n{state.get('blast_radius_context', 'None')}\n\n"
                f"## Policy Rules:\n{state.get('policy_rules', 'Default')}\n\n"
                f"## {state.get('feedback_context', '')}"
            )
            inputs = {"messages": [HumanMessage(content=content)]}
        else:
            # Retry: append grader feedback
            retry_msg = (
                f"The Self-Correction Grader rejected your output. Fix these issues:\n"
                f"{state['grader_feedback']}\n\nReturn the corrected JSON array."
            )
            inputs = {"messages": state["messages"] + [HumanMessage(content=retry_msg)]}

        result = await react_agent.ainvoke(inputs)
        final_message = result["messages"][-1]

        # Parse JSON from response
        proposed = []
        content = final_message.content
        try:
            if "```json" in content:
                content = content.split("```json")[-1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            parsed = json.loads(content)
            if isinstance(parsed, list):
                proposed = parsed
            elif isinstance(parsed, dict) and "comments" in parsed:
                proposed = parsed["comments"]
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Could not parse agent output as JSON")

        return {
            "messages": result["messages"],
            "proposed_comments": proposed,
            "iteration": state.get("iteration", 0) + 1,
        }

    return review_agent


async def grader_node(state: ReviewState) -> dict:
    """Self-Correction Grader: validates proposed comments."""
    if not state.get("proposed_comments"):
        return {"grader_feedback": "PASS"}

    llm = get_llm(temperature=0.0)
    if not llm:
        return {"grader_feedback": "PASS"}

    proposed_json = json.dumps(state["proposed_comments"], indent=2)
    prompt = GRADER_PROMPT.format(proposed_comments=proposed_json)

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    feedback = response.content.strip()

    return {"grader_feedback": feedback}


def grade_router(state: ReviewState) -> str:
    """Route based on grader output."""
    feedback = state.get("grader_feedback", "")
    iteration = state.get("iteration", 0)

    if "PASS" in feedback.upper() or iteration >= 3:
        return "synthesize"
    return "review_agent"


def synthesize_node(state: ReviewState) -> dict:
    """Final node: output validated comments."""
    return {"proposed_comments": state.get("proposed_comments", [])}


def build_review_graph(tools):
    """Build and compile the LangGraph review pipeline."""
    workflow = StateGraph(ReviewState)

    workflow.add_node("review_agent", create_review_node(tools))
    workflow.add_node("grader", grader_node)
    workflow.add_node("synthesize", synthesize_node)

    workflow.set_entry_point("review_agent")
    workflow.add_edge("review_agent", "grader")
    workflow.add_conditional_edges("grader", grade_router, {
        "review_agent": "review_agent",
        "synthesize": "synthesize",
    })
    workflow.add_edge("synthesize", END)

    return workflow.compile()
