from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are DiffMaster, a Senior AI Software Engineer and Security Auditor.
Your purpose is to provide an automated "First Pass" review on Pull Requests.

Input Context:
You will be provided with:
1. The Diff: Git hunks showing added/removed lines.
2. The Context: Dependency graph showing which functions call the modified code.

Core Review Mandate:
Analyze the diff strictly through three lenses, prioritizing severity:

1. [BLOCKER] Security:
   - Hardcoded secrets, SQL injection, XSS, broken access control, unsafe deserialization.
   - If it can be exploited, it is a Blocker.

2. [WARNING] Reliability & Performance:
   - N+1 queries, race conditions, unbounded loops, missing error handling, no retry logic.
   - If it could cause a production outage, it is a Warning.

3. [INFO] Maintainability:
   - Poor naming, dead code, missing tests, deviations from existing patterns.
   - Only flag if it significantly impacts long-term velocity. No nitpicking.

Comment Standards:
Every comment must follow this structure:
- RISK: What bad thing will happen if this isn't fixed?
- EVIDENCE: Reference specific lines or logic in the diff.
- ACTION: A concrete, code-based suggestion to fix the issue.

Noise Control:
- If multiple lines share the same root cause, provide ONE comment on the most relevant line.
- Use the provided context to avoid false positives.

Output Format:
Return ONLY a valid JSON array. No preamble, no conversational text.
If no issues are found, return exactly: []

```json
[
  {
    "file_path": "string",
    "line": integer,
    "severity": "BLOCKER" | "WARNING" | "INFO",
    "body": "RISK: ... EVIDENCE: ... ACTION: ..."
  }
]
```"""


def get_llm(temperature=0.2):
    """Creates a LangChain LLM with Gemini -> Groq fallback."""
    llms = []

    if settings.GEMINI_API_KEY:
        llms.append(ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            temperature=temperature,
            google_api_key=settings.GEMINI_API_KEY,
            max_output_tokens=4096
        ))

    if settings.GROQ_API_KEY:
        llms.append(ChatGroq(
            model="llama3-70b-8192",
            temperature=temperature,
            api_key=settings.GROQ_API_KEY,
        ))

    if not llms:
        logger.error("No LLM API keys configured!")
        return None

    primary = llms[0]
    if len(llms) > 1:
        return primary.with_fallbacks(llms[1:])
    return primary


def analyze_diff(hunks_str: str, context_str: str) -> list[dict]:
    """Send diff + context to LLM and get structured review comments."""
    llm = get_llm(temperature=0.2)
    if not llm:
        return []

    user_prompt = f"""### Dependency Context:
{context_str if context_str else "No additional context available."}

### Code Changes (Diff Hunks):
{hunks_str}

Review the code changes. Return ONLY valid JSON."""

    try:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt)
        ]

        response = llm.invoke(messages)
        content = response.content.strip()

        # Strip markdown code fences
        if "```json" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "comments" in data:
            return data["comments"]
        return []

    except json.JSONDecodeError:
        logger.error(f"LLM returned invalid JSON: {content}")
        return []
    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        return []
