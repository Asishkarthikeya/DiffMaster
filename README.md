# DiffMaster

**Intelligent Automated Code Review API**

DiffMaster is a headless, API-first AI code reviewer that integrates directly with your Version Control System. It acts as a "First Pass" reviewer — when a Pull Request is opened, DiffMaster analyzes the code changes, cross-references them with project patterns, and posts line-specific comments covering security, performance, and maintainability.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     VCS Platforms                            │
│              GitHub  ·  GitLab  ·  Bitbucket                │
└──────────┬───────────────────────────────────┬──────────────┘
           │  Webhooks (PR opened/sync)         │  Post Comments
           ▼                                    ▲
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI (API Gateway)                     │
│  /api/v1/webhooks  ·  /api/v1/reviews  ·  /api/v1/policies │
└──────────┬───────────────────────────────────┬──────────────┘
           │  Enqueue Task                      │  Return Results
           ▼                                    ▲
┌──────────────────────────────────────────────────────────────┐
│               Celery Workers (Redis Broker)                  │
│                                                              │
│  ┌─────────┐  ┌───────────┐  ┌────────────┐  ┌──────────┐ │
│  │  Diff   │→ │  Blast    │→ │  Policy    │→ │   AI     │ │
│  │ Parser  │  │  Radius   │  │  Engine    │  │  Review  │ │
│  └─────────┘  └───────────┘  └────────────┘  └──────────┘ │
│       │              │              │              │         │
│       ▼              ▼              ▼              ▼         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           Comment Generator & Deduplication           │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
           │                                    ▲
           ▼                                    │
┌──────────────────────────────────────────────────────────────┐
│  PostgreSQL (pgvector)  ·  Embeddings  ·  RAG Context       │
└──────────────────────────────────────────────────────────────┘
```

## Core Workflow

1. **Webhook Intake** — Receives `pull_request.opened`/`synchronize` events; validates signatures and rate-limits.
2. **Diff & Context Fetch** — Retrieves diff hunks, file contents, and repository metadata.
3. **Blast Radius Analysis** — Identifies impacted call sites, dependencies, and security boundaries; prioritizes risky hunks.
4. **Policy-Aware Review** — Applies org rules (forbidden APIs, secrets detection, logging standards, performance constraints).
5. **AI Review** — Sends chunked diffs with context to LLM for intelligent code review.
6. **Comment Generation** — Posts concise, line-anchored comments with severity, reasoning, and suggested fixes.
7. **Feedback Loop** — Tracks which comments are accepted/rejected; learns per-repo conventions to reduce noise.

## Review Categories

| Severity | Category | Examples |
|----------|----------|----------|
| **BLOCKER** | Security | Injection risks, authz checks, secret exposure, unsafe deserialization |
| **WARNING** | Reliability/Performance | Concurrency hazards, unbounded retries, N+1 patterns |
| **INFO** | Maintainability | Naming, dead code, missing tests, documentation gaps |

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Framework | Python FastAPI (async) |
| Task Queue | Celery + Redis |
| Database | PostgreSQL + pgvector |
| VCS Integration | GitHub API, GitLab API |
| Code Parsing | Tree-Sitter, Python AST |
| AI/LLM | OpenAI GPT-4o |
| Embeddings | OpenAI text-embedding-3-small |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- OpenAI API key

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/diffmaster.git
cd diffmaster
cp .env.example .env
# Edit .env with your configuration
```

### 2. Start with Docker Compose

```bash
docker compose up -d
```

This starts:
- **API server** on `http://localhost:8000`
- **Celery worker** for async review processing
- **Celery beat** for scheduled tasks
- **PostgreSQL** with pgvector extension
- **Redis** as message broker

### 3. Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn app.main:app --reload --port 8000

# Start celery worker (separate terminal)
celery -A app.workers.celery_app worker --loglevel=info
```

### 4. Run Tests

```bash
pytest tests/ -v
```

## API Endpoints

### Webhooks
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/webhooks/github` | GitHub webhook receiver |
| `POST` | `/api/v1/webhooks/gitlab` | GitLab webhook receiver |

### Reviews
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/reviews` | List reviews (filterable) |
| `GET` | `/api/v1/reviews/{id}` | Get review details |
| `GET` | `/api/v1/reviews/{id}/comments` | Get review comments |
| `PATCH` | `/api/v1/reviews/{id}/comments/{cid}/feedback` | Submit feedback |
| `GET` | `/api/v1/reviews/{id}/stats` | Get feedback statistics |

### Repositories
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/repositories` | List repositories |
| `POST` | `/api/v1/repositories` | Register a repository |
| `GET` | `/api/v1/repositories/{id}` | Get repository details |
| `PATCH` | `/api/v1/repositories/{id}` | Update repository settings |
| `DELETE` | `/api/v1/repositories/{id}` | Remove a repository |

### Policies
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/policies` | List policy packs |
| `POST` | `/api/v1/policies` | Create a policy pack |
| `GET` | `/api/v1/policies/{id}` | Get policy details |
| `PATCH` | `/api/v1/policies/{id}` | Update a policy |
| `DELETE` | `/api/v1/policies/{id}` | Delete a policy |
| `POST` | `/api/v1/policies/{id}/rules` | Add a rule to policy |
| `DELETE` | `/api/v1/policies/{id}/rules/{rid}` | Delete a rule |

### Health
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check with DB status |
| `GET` | `/api/v1/ready` | Readiness probe |

## Project Structure

```
diffmaster/
├── app/
│   ├── api/                    # FastAPI route handlers
│   │   ├── health.py           # Health checks
│   │   ├── webhooks.py         # VCS webhook intake
│   │   ├── reviews.py          # Review management
│   │   ├── repositories.py     # Repository management
│   │   ├── policies.py         # Policy management
│   │   └── router.py           # Central router
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── repository.py       # Repository model
│   │   ├── review.py           # Review model
│   │   ├── comment.py          # ReviewComment model (pgvector)
│   │   └── policy.py           # Policy & PolicyRule models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── services/               # Business logic
│   │   ├── diff_parser.py      # Diff parsing & smart chunking
│   │   ├── blast_radius.py     # Impact analysis
│   │   ├── policy_engine.py    # Policy evaluation
│   │   ├── review_engine.py    # AI-powered review
│   │   ├── comment_generator.py# Comment formatting & dedup
│   │   ├── feedback_tracker.py # Feedback loop
│   │   └── rag/                # RAG pipeline
│   │       ├── embeddings.py   # Embedding generation
│   │       └── retriever.py    # Vector similarity search
│   ├── integrations/           # VCS platform integrations
│   │   ├── base.py             # Abstract interface
│   │   ├── github_integration.py
│   │   ├── gitlab_integration.py
│   │   └── webhook_validator.py
│   ├── workers/                # Celery async workers
│   │   ├── celery_app.py       # Celery configuration
│   │   └── tasks.py            # Task definitions
│   ├── parsing/                # Code parsing
│   │   └── tree_sitter_parser.py
│   ├── db/                     # Database utilities
│   ├── config.py               # Application settings
│   └── main.py                 # FastAPI entry point
├── tests/                      # Test suite (92 tests)
├── alembic/                    # Database migrations
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── requirements.txt
```

## Configuration

All configuration is managed via environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | OpenAI API key | (required) |
| `OPENAI_MODEL` | LLM model for reviews | `gpt-4o` |
| `GITHUB_WEBHOOK_SECRET` | GitHub webhook secret | (optional) |
| `MAX_COMMENTS_PER_PR` | Cap on comments per PR | `25` |
| `COMMENT_DEDUP_ENABLED` | Deduplicate across commits | `true` |
| `MIN_SEVERITY` | Minimum severity to post | `INFO` |

## Built-in Security Rules

DiffMaster includes built-in detection for:

- **Secrets**: API keys, passwords, private keys, AWS credentials, GitHub tokens
- **Dangerous APIs**: `eval()`, `exec()`, `os.system()`, `shell=True`, `pickle.load()`, `innerHTML`
- **Unsafe patterns**: YAML without SafeLoader, SQL injection indicators

## License

Proprietary — Enterprise AI Engineering Suite
