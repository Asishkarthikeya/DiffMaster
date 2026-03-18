# 🤖 DiffMaster

**AI-powered code review that runs as a GitHub Action.**

DiffMaster automatically reviews Pull Requests using Google Gemini and Groq, performing AST-level analysis with Tree-Sitter and dependency tracking with NetworkX.

## Features

- 🔒 **Security Auditing** — Detects hardcoded secrets, SQL injection, XSS, and more
- ⚡ **Performance Analysis** — Flags N+1 queries, race conditions, unbounded loops
- 🧠 **AST-Aware** — Uses Tree-Sitter to understand function boundaries and call graphs
- 🕸️ **Blast Radius** — NetworkX dependency graph shows what else is affected by changes
- 🔄 **Gemini → Groq Fallback** — Automatic failover between LLM providers

## Quick Start

### 1. Add the workflow to your repo

Create `.github/workflows/diffmaster.yml`:

```yaml
name: DiffMaster AI Review

on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Run DiffMaster
        uses: Asishkarthikeya/DiffMaster@main
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
          groq_api_key: ${{ secrets.GROQ_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

### 2. Set up GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required | Description |
|--------|----------|-------------|
| `GEMINI_API_KEY` | ✅ | Google AI Studio API key |
| `GROQ_API_KEY` | ❌ | Groq API key (fallback) |
| `GITHUB_TOKEN` | ✅ | GitHub PAT with `pull-requests: write` |

### 3. Open a PR

DiffMaster will automatically post review comments on your PR!

## Architecture

```
PR Opened → GitHub Action → DiffMaster
  ├─ Fetch PR diff via GitHub API
  ├─ Parse hunks with Tree-Sitter AST
  ├─ Build in-memory dependency graph (NetworkX)
  ├─ Analyze with Gemini/Groq (LangChain)
  └─ Post review comments back to PR
```

## Review Severity Levels

| Level | Meaning |
|-------|---------|
| 🔴 `BLOCKER` | Security vulnerability — must fix before merge |
| 🟡 `WARNING` | Reliability/performance risk — should fix |
| 🔵 `INFO` | Maintainability suggestion — nice to fix |

## Local Testing

```bash
export GEMINI_API_KEY="your-key"
export GITHUB_TOKEN="your-token"
export GITHUB_REPOSITORY="owner/repo"
export PR_NUMBER="42"

pip install -r requirements.txt
python main.py
```
