# ITRA Normalizer Demo

A functional vertical slice for normalizing synthetic IT Risk Assessments. Normalization runs in guarded domain batches while retaining AC.2.1/S.7 as the hero case: two sites report the same raw compliance status, while their detailed evidence describes materially different shared-account practices.

## Current scope

- Loads two validated synthetic site fixtures into SQLite.
- Stores all 32 controls, scoping, technical, security, and risk records.
- Runs three real OpenAI assessments per site-control pair in a selected control domain.
- Uses Responses API Structured Outputs with a Pydantic schema.
- Persists normalized values, reconciliation, confidence, model/prompt version, and agreement rate.
- Presents an executive portfolio dashboard, a control explorer, and raw-versus-normalized evidence in Streamlit.
- Protects paid actions with an access code, server-side quotas, result caching, and a kill switch.
- Records API calls and token usage in SQLite for demo-cost visibility.
- Flags low agreement and reconciliation findings explicitly for QA review.
- Includes a managed OpenAI file-search Q&A surface with source-file citations, retrieved evidence snippets, and relevance scores.

PDF parsing and the combined SQL/RAG chat agent are subsequent slices.

## Run locally

Python 3.9 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Export your API key in the shell (do not commit it):

```bash
export OPENAI_API_KEY='your-key'
export DEMO_ACCESS_CODE='choose-a-demo-code'
export OPENAI_CALLS_ENABLED=true
```

Load fixtures and run the tests:

```bash
python scripts/ingest.py
pytest
```

Start the frontend:

```bash
streamlit run app/streamlit_app.py
```

Open <http://localhost:8501>, select a domain, review the planned API calls, then start the guarded normalization batch.

## Docker

```bash
docker build -t itra-normalizer .
docker run --rm -p 8501:8501 \
  -e OPENAI_API_KEY \
  -e DEMO_ACCESS_CODE \
  -e OPENAI_CALLS_ENABLED=true \
  itra-normalizer
```

## Railway deployment

Railway automatically detects the root `Dockerfile`. `railway.toml` configures the Streamlit health endpoint and restart policy. Configure these service variables in Railway:

```text
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-5.6-terra
NORMALIZATION_RUNS=3
DEMO_ACCESS_CODE=<secret>
OPENAI_CALLS_ENABLED=true
MAX_NORMALIZATION_JOBS_PER_DAY=10
MAX_GLOBAL_API_CALLS_PER_DAY=100
MAX_OUTPUT_TOKENS=500
ITRA_DB_PATH=/app/storage/itra.db
OPENAI_VECTOR_STORE_ID=<vector-store-id>
RAG_MAX_RESULTS=5
```

Attach a Railway volume at `/app/storage` before enabling paid actions. The public app remains readable without the access code; only OpenAI-backed actions require it.

## Create the RAG knowledge base

Run the indexing script once from a trusted shell with the project-scoped API key exported:

```bash
python scripts/create_vector_store.py
```

The script creates a new OpenAI vector store, uploads both synthetic PDFs, waits for indexing, and prints an `OPENAI_VECTOR_STORE_ID=...` line. Add that value to Railway. Never pass the API key as a command-line argument or commit it. File-search questions use one API request each and share the same access code, kill switch, daily quotas, spend limit, and usage ledger as normalization.

To stop all paid actions without taking the read-only demo offline, set:

```text
OPENAI_CALLS_ENABLED=false
```

The app reserves a complete job's planned calls before starting, permits only one active normalization job, reuses results for identical input/model/prompt versions, and records response usage. These controls complement—but do not replace—an enforced OpenAI project spend limit.

## Data safety

All committed fixtures are synthetic. `.env`, local SQLite databases, and Streamlit secrets are ignored by Git.
