"""
DiffMaster LLM Module — Waterfall Fallback System

Cascade order:
  1. Gemini (primary model from config)
  2. Gemini fallback variants (2.0-flash, 2.0-flash-lite, 1.5-flash)
  3. Groq models (llama-3.3-70b, llama-3.1-8b, gemma2-9b)

On rate-limit / 404 / any error → automatically tries the next model.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
import json
import time
import logging

logger = logging.getLogger(__name__)

# --- Waterfall Model Chain ---
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

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


def _build_model_chain(temperature: float = 0.2) -> list[tuple[str, object]]:
    """Build the ordered waterfall chain of (name, llm) tuples."""
    chain = []

    if settings.GEMINI_API_KEY:
        # Primary model from config
        primary = settings.GEMINI_MODEL
        seen = set()

        # Add primary first
        models_to_try = [primary] + [m for m in GEMINI_MODELS if m != primary]

        for model in models_to_try:
            if model in seen:
                continue
            seen.add(model)
            chain.append((
                f"gemini/{model}",
                ChatGoogleGenerativeAI(
                    model=model,
                    temperature=temperature,
                    google_api_key=settings.GEMINI_API_KEY,
                    max_output_tokens=4096,
                )
            ))

    if settings.GROQ_API_KEY:
        for model in GROQ_MODELS:
            chain.append((
                f"groq/{model}",
                ChatGroq(
                    model=model,
                    temperature=temperature,
                    api_key=settings.GROQ_API_KEY,
                )
            ))

    return chain


def get_llm(temperature=0.2):
    """
    Returns the primary LLM with automatic fallbacks.
    Uses LangChain's .with_fallbacks() for seamless cascading.
    """
    chain = _build_model_chain(temperature)

    if not chain:
        logger.error("No LLM API keys configured!")
        return None

    logger.info(f"🔗 LLM waterfall chain: {' → '.join(name for name, _ in chain)}")

    primary_name, primary_llm = chain[0]
    if len(chain) > 1:
        fallback_llms = [llm for _, llm in chain[1:]]
        return primary_llm.with_fallbacks(fallback_llms)

    return primary_llm


def invoke_with_waterfall(messages: list, temperature: float = 0.2) -> str | None:
    """
    Manually invoke the waterfall chain with detailed logging.
    Tries each model in order; on any error, moves to next.
    Returns the response content string, or None if all models fail.
    """
    chain = _build_model_chain(temperature)

    if not chain:
        logger.error("No LLM API keys configured!")
        return None

    for i, (name, llm) in enumerate(chain):
        try:
            logger.info(f"  🔄 Trying model {i+1}/{len(chain)}: {name}")
            response = llm.invoke(messages)
            logger.info(f"  ✅ Success with {name}")
            return response.content.strip()
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate" in error_msg.lower():
                logger.warning(f"  ⚠️ Rate limited on {name}, trying next...")
            elif "404" in error_msg or "not found" in error_msg.lower():
                logger.warning(f"  ⚠️ Model {name} not found, trying next...")
            else:
                logger.warning(f"  ⚠️ Error on {name}: {error_msg[:100]}, trying next...")

            if i < len(chain) - 1:
                time.sleep(0.5)  # Brief pause before retry
                continue

    logger.error("❌ All models in the waterfall chain failed!")
    return None


def analyze_diff(hunks_str: str, context_str: str) -> list[dict]:
    """Send diff + context to LLM and get structured review comments.
    Uses the waterfall chain for maximum reliability."""

    user_prompt = f"""### Dependency Context:
{context_str if context_str else "No additional context available."}

### Code Changes (Diff Hunks):
{hunks_str}

Review the code changes. Return ONLY valid JSON."""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt)
    ]

    content = invoke_with_waterfall(messages, temperature=0.2)
    if not content:
        return []

    try:
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
        logger.error(f"LLM returned invalid JSON: {content[:200]}")
        return []
