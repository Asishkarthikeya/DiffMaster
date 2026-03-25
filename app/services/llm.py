"""
DiffMaster LLM Module — Waterfall Fallback System

Cascade order (optimized for free-tier reliability):
  1. Groq models (fast, reliable, free tier generous)
  2. Gemini models (free tier quota is tight)

On rate-limit / 404 / any error → immediately tries the next model.
No internal SDK retries — fail fast, move on.
"""

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
import json
import time
import logging

logger = logging.getLogger(__name__)

# --- Waterfall Model Chain ---
# Groq FIRST (fast, reliable, generous free tier)
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

# Gemini as FALLBACK (free tier exhausts quickly)
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
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
- ACTION: A concrete, code-based suggestion to fix the issue. **MUST use GitHub's standard ` ```suggestion ` syntax block so the developer can click to commit the fix directly!**

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
    """Build the ordered waterfall chain of (name, llm) tuples.
    Order: Groq first (reliable), then Gemini (quota-limited)."""
    chain = []

    # --- Groq FIRST (generous free tier, fast) ---
    if settings.GROQ_API_KEY:
        for model in GROQ_MODELS:
            chain.append((
                f"groq/{model}",
                ChatGroq(
                    model=model,
                    temperature=temperature,
                    api_key=settings.GROQ_API_KEY,
                    max_retries=1,  # Fail fast
                )
            ))

    # --- Gemini SECOND (as fallback) ---
    if settings.GEMINI_API_KEY:
        for model in GEMINI_MODELS:
            chain.append((
                f"gemini/{model}",
                ChatGoogleGenerativeAI(
                    model=model,
                    temperature=temperature,
                    google_api_key=settings.GEMINI_API_KEY,
                    max_output_tokens=4096,
                    max_retries=0,    # NO internal retries — fail immediately
                    timeout=15,       # 15s hard timeout
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
    Tries each model in order; on any error, moves to next IMMEDIATELY.
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
            if "429" in error_msg or "rate" in error_msg.lower() or "quota" in error_msg.lower():
                logger.warning(f"  ⚠️ Rate limited on {name}, trying next...")
            elif "404" in error_msg or "not found" in error_msg.lower():
                logger.warning(f"  ⚠️ Model {name} not found, trying next...")
            else:
                logger.warning(f"  ⚠️ Error on {name}: {error_msg[:150]}, trying next...")

            if i < len(chain) - 1:
                time.sleep(0.3)  # Brief pause before retry
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

def generate_full_review(file_patches: dict[str, str]) -> str:
    """Generate a comprehensive, sectioned code review for ALL files in the PR.
    
    Produces a single rich Markdown comment with:
    - Code Review of [filename]
    - Bugs
    - Performance Problems
    - Security Issues
    - Code Quality Improvements (with inline code blocks)
    - Suggested Revised Code
    """
    if not file_patches:
        return "✅ **DiffMaster Review Complete:** No issues found. This PR looks clean!"

    # Build the diff context string
    patches_str = ""
    for filename, patch in file_patches.items():
        patches_str += f"\n### File: `{filename}`\n```\n{patch}\n```\n"

    prompt = f"""You are DiffMaster, a Senior AI Code Reviewer performing a comprehensive code review.

Below are the code changes (diffs) from a Pull Request. For EACH file, produce a thorough review.

YOUR OUTPUT MUST follow this EXACT markdown structure. Include ALL applicable sections. If a section has no issues, OMIT it entirely. Do NOT use placeholder text.

---

# Code Review of [filename]

## Bugs
1. **[Bug Title]:** [Detailed explanation of the bug, WHY the current code is wrong, and what will happen if not fixed. Reference the exact method/line. Show the correct usage with inline code like `db.users.find_one({{"_id": id}})` instead of `db.users.find(id)`.]

## Performance Problems
1. **[Problem Title]:** [Explain the performance implication. For example, if a variable is not indexed, querying with `find` may lead to performance issues on large datasets. Recommend indexing or projecting necessary fields.]
2. **[Problem Title]:** [Additional performance concern if applicable.]

## Security Issues
1. **[Issue Title]:** [Explain the security risk. For example, no input validation on `id` opens the door to NoSQL injection. Recommend type checking and sanitization.]

## Code Quality Improvements
1. **[Improvement Title]:** [Explain the improvement. Include inline code blocks showing the improvement, like adding a docstring:]
```python
def get_user(id):
    \"\"\"Retrieve a user from the database by their unique identifier.

    Args:
        id (str): The unique identifier of the user.

    Returns:
        dict: The user document from the database or None if not found.
    \"\"\"
```
2. **[Improvement Title]:** [Additional quality suggestion, e.g., renaming parameters for clarity.]
3. **[Improvement Title]:** [e.g., Return type consistency - handle None case.]

## Suggested Revised Code
```python
# Show the COMPLETE corrected version of the function/code
```

---

IMPORTANT RULES:
- Be extremely thorough and detailed. Cover ALL issues you can find.
- Use GitHub-flavored Markdown with proper code blocks.
- Include inline code references using backticks for function names, variables, and methods.
- The "Suggested Revised Code" MUST be a complete, working, corrected version of the code.
- If reviewing multiple files, create a separate "# Code Review of [filename]" section for each.
- Do NOT use JSON format. Output ONLY rich Markdown.

Here are the code changes to review:
{patches_str[:12000]}

Generate the comprehensive code review now:"""

    messages = [HumanMessage(content=prompt)]
    content = invoke_with_waterfall(messages, temperature=0.3)
    if not content:
        return "⚠️ DiffMaster ran into an error generating the review."
    return content

def generate_pr_description(diff_patches: str) -> str:
    """Generate a high-level summary of the entire Pull Request."""
    prompt = f"""You are DiffMaster, an AI Code Reviewer. 
Your task is to summarize the changes in this Pull Request for human reviewers.

Output a beautifully formatted Markdown summary with the following structure:
### 🤖 DiffMaster PR Summary
**Purpose:** [One sentence describing the overall goal of the PR]

**Key Changes:**
- [Bullet points of major files changed and what was done]

Raw Diff:
{diff_patches[:8000]}

Return ONLY the markdown summary."""

    messages = [HumanMessage(content=prompt)]
    content = invoke_with_waterfall(messages, temperature=0.2)
    return content or "⚠️ Could not generate PR description."
