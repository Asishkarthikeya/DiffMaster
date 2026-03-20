<p align="center">
  <h1 align="center">🤖 DiffMaster</h1>
  <p align="center"><strong>AI-powered code review that catches security bugs, performance issues, and code smells — automatically on every Pull Request.</strong></p>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-features">Features</a> •
  <a href="#%EF%B8%8F-configuration">Configuration</a> •
  <a href="#-how-it-works">How It Works</a> •
  <a href="#-example-review">Example</a>
</p>

---

## ⚡ Quick Start

Add DiffMaster to any repository in **2 minutes**:

### 1. Add API Keys as Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret | Required | Description |
|--------|----------|-------------|
| `GEMINI_API_KEY` | Optional | [Google AI Studio](https://aistudio.google.com/apikey) — free tier available |
| `GROQ_API_KEY` | Optional | [Groq Console](https://console.groq.com/keys) — free tier available |

> **Note:** At least one API key is required. We recommend setting both for maximum reliability.

### 2. Create the Workflow File

Create `.github/workflows/diffmaster.yml` in your repository:

```yaml
name: DiffMaster AI Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: Asishkarthikeya/DiffMaster@main
        with:
          github_token: ${{ github.token }}
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
          groq_api_key: ${{ secrets.GROQ_API_KEY }}
```

### 3. Open a PR

That's it! DiffMaster will automatically review every new or updated Pull Request and post inline comments.

---

## 🎯 Features

### 🔴 Security Auditing (BLOCKER)
- Hardcoded secrets, API keys, passwords
- SQL injection, command injection, code injection (`eval()`)
- XSS, broken access control, unsafe deserialization

### 🟡 Reliability & Performance (WARNING)
- N+1 query patterns
- Race conditions, unbounded loops
- Missing error handling, no retry logic

### 🔵 Maintainability (INFO)
- Poor naming, dead code
- Missing tests, missing docstrings
- Deviations from existing code patterns

### 🧠 Smart Analysis
- **AST Parsing** — Tree-Sitter parses your code into an Abstract Syntax Tree for precise analysis
- **Dependency Graphing** — NetworkX maps function call relationships to understand impact
- **RAG Context** — FAISS vector search finds relevant code for better context
- **Waterfall LLM Fallback** — Automatically cascades through multiple models if one is rate-limited

### 🔇 Noise Control
- Deduplicates similar comments
- Caps max comments per review (default: 15)
- Severity filtering — only show what matters
- Groups comments by root cause

---

## ⚙️ Configuration

### Workflow Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `github_token` | *required* | GitHub token for posting comments (`${{ github.token }}`) |
| `gemini_api_key` | `""` | Google Gemini API key |
| `groq_api_key` | `""` | Groq API key (fallback) |
| `model` | `gemini-2.5-flash-preview-05-20` | Primary LLM model |
| `severity_filter` | `INFO` | Minimum severity: `BLOCKER`, `WARNING`, or `INFO` |

### Repo-Level Config (Optional)

Create a `.diffmaster.yml` in your repo root to customize behavior:

```yaml
# .diffmaster.yml
severity_filter: WARNING        # Only post WARNING and BLOCKER
max_comments: 10                # Cap at 10 comments per review
ignore_paths:                   # Skip these paths
  - "docs/**"
  - "*.md"
  - "tests/fixtures/**"
custom_rules:                   # Add project-specific rules
  - "All API endpoints must have rate limiting"
  - "Database queries must use parameterized statements"
```

---

## 🔗 How It Works

```
PR Opened / Updated
        │
        ▼
┌─────────────────┐
│  Fetch PR Diff   │  ← GitHub API
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Parse with AST  │  ← Tree-Sitter (Python, JS, TS)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Build Dep Graph  │  ← NetworkX (function call mapping)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  RAG Context     │  ← FAISS + sentence-transformers
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  LLM Review      │  ← Groq → Gemini (waterfall fallback)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Post Comments    │  ← GitHub PR Review API
└─────────────────┘
```

### LLM Waterfall Chain

DiffMaster automatically cascades through models for maximum reliability:

```
groq/llama-3.3-70b → groq/llama-3.1-8b → groq/gemma2-9b
        ↓ (if all Groq models fail)
gemini/2.0-flash → gemini/2.0-flash-lite → gemini/1.5-flash
```

If one model is rate-limited or unavailable, it **instantly** tries the next — no waiting.

---

## 💬 Example Review

When DiffMaster reviews your PR, it posts inline comments like this:

> **\[BLOCKER\] DiffMaster Review**
>
> RISK: Hardcoded API key exposure. The secret `sk-12345-super-secret-key` is committed to source control.
> EVIDENCE: `API_KEY = "sk-12345-super-secret-key"` on line 4.
> ACTION: Store API keys securely using environment variables: `API_KEY = os.getenv("API_KEY")`

> **\[WARNING\] DiffMaster Review**
>
> RISK: N+1 query pattern will cause performance degradation at scale.
> EVIDENCE: Line 15 queries orders inside a loop over users.
> ACTION: Use a single JOIN query: `SELECT * FROM users JOIN orders ON users.id = orders.user_id`

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM Providers | Groq (Llama 3.3, Gemma2), Google Gemini |
| Code Parsing | Tree-Sitter (Python, JavaScript, TypeScript) |
| Dependency Graph | NetworkX |
| Vector Search | FAISS + sentence-transformers |
| Orchestration | LangGraph (multi-agent pipeline) |
| GitHub Integration | PyGithub |

---

## 🔒 Security & Privacy

- **No code storage** — DiffMaster is stateless; it processes each PR independently and stores nothing
- **API keys as secrets** — credentials are managed through GitHub Secrets, never exposed in logs
- **Minimal permissions** — only requires `contents: read` and `pull-requests: write`
- **Runs in your GitHub Actions** — your code never leaves GitHub's infrastructure

---

## 📝 License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Built with ❤️ by <a href="https://github.com/Asishkarthikeya">Asish Karthikeya</a></strong>
</p>
