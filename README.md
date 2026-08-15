# ITRA Normalizer Demo

A functional vertical slice for normalizing synthetic IT Risk Assessments. The first slice focuses on the AC.2.1/S.7 hero case: two sites report the same raw compliance status, while their detailed evidence describes materially different shared-account practices.

## Current scope

- Loads two validated synthetic site fixtures into SQLite.
- Stores all 32 controls, scoping, technical, security, and risk records.
- Runs three real OpenAI assessments per site for AC.2.1.
- Uses Responses API Structured Outputs with a Pydantic schema.
- Persists normalized values, reconciliation, confidence, model/prompt version, and agreement rate.
- Presents raw evidence and normalized results in Streamlit.
- Protects paid actions with an access code, server-side quotas, result caching, and a kill switch.
- Records API calls and token usage in SQLite for demo-cost visibility.

PDF parsing, all-control normalization, managed file-search RAG, dashboarding, and the combined SQL/RAG chat agent are subsequent slices.

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

Open <http://localhost:8501>, then select **Run AC.2.1 normalization**.

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
ITRA_DB_PATH=/app/data/itra.db
```

Attach a Railway volume at `/app/data` before enabling paid actions. The public app remains readable without the access code; only OpenAI-backed actions require it.

To stop all paid actions without taking the read-only demo offline, set:

```text
OPENAI_CALLS_ENABLED=false
```

The app reserves a complete job's planned calls before starting, permits only one active normalization job, reuses results for identical input/model/prompt versions, and records response usage. These controls complement—but do not replace—an enforced OpenAI project spend limit.

## Data safety

All committed fixtures are synthetic. `.env`, local SQLite databases, and Streamlit secrets are ignored by Git.
