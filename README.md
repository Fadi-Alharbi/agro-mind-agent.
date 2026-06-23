# Agro-Mind Agent

Agro-Mind Agent is a FastAPI, LangGraph, Qwen, and Streamlit support assistant
for an agricultural products store. It helps customers diagnose crop issues,
find catalog-backed product recommendations, manage carts and orders, and route
safety-sensitive messages to a human before an LLM is called.

## Core Capabilities

- Classifies messages into diagnosis, product, logistics, safety, or general QA.
- Uses a pre-LLM safety interceptor for pesticide ingestion, poisoning, and
  self-harm risk.
- Supports text and image-based crop diagnosis through Qwen text and vision
  models.
- Retrieves product context from the translated local catalog and Chroma vector
  store before recommending products.
- Supports lightweight username/password login, logout, session resume, new
  chat sessions, profile updates, and current-session or cross-session history.
- Persists customers, authenticated sessions, chat history, image attachments,
  carts, orders, diagnoses, treatments, treatment tasks, and escalations with
  SQLAlchemy.
- Remembers pesticide context from active carts and shipped orders so usage
  questions like "how do I use it?" can resolve to the relevant product.
- Exposes a Streamlit chat UI with product cards, single/group-buy cart actions,
  checkout, order status, treatment-plan consent, treatment tasks, image upload,
  previous chats, and streaming assistant responses.

## Architecture

```text
Streamlit UI
    |
    | HTTP / NDJSON stream
    v
FastAPI API
    |
    +-- safety/interceptor.py     Pre-LLM safety screen
    +-- agent/orchestrator.py     LangGraph routing and response contract
    +-- agent/tools.py            Intent, retrieval, vision, memory, product tools
    +-- agent/llm.py              Qwen/DashScope-compatible model factories
    +-- rag/catalog_loader.py     XLSX product catalog parser and keyword search
    +-- rag/ingest.py             Chroma ingestion for catalog/advisory knowledge
    +-- db/customer_state.py      Carts, orders, treatments, customer memory
    +-- db/models.py              SQLAlchemy schema
    +-- memory/customer_memory.py Session and cross-session customer context
```

## Product Requirements

For the full product requirements document, see
[docs/PROJECT_PRD.md](docs/PROJECT_PRD.md).

## Project Layout

```text
agent/        LangGraph orchestration, prompts, and LLM/tool adapters
docs/         Product and engineering documentation
db/           SQLAlchemy engine, schema, seed scripts, and generated local data
evaluation/   Scripted safety and intent checks
frontend/     Streamlit application
memory/       Customer/session memory wrapper
rag/          Catalog parser, source CSV/XLSX data, and vector ingestion
safety/       Safety interceptor
tests/        Pytest suite
tools/        Agriculture helper tools
main.py       FastAPI application entry point
```

## Requirements

- Python 3.10 or newer
- A Qwen/DashScope API key for LLM-backed chat, vision, and embeddings
- SQLite for local development, or another SQLAlchemy-supported database
- `requirements.txt` includes the MySQL driver for `mysql+pymysql://...`
  database URLs.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```bash
# Required for model-backed responses
QWEN_API_KEY=your_dashscope_key
# or:
# DASHSCOPE_API_KEY=your_dashscope_key

# Optional model overrides
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-turbo
QWEN_VISION_MODEL=qwen-vl-plus
QWEN_EMBED_MODEL=text-embedding-v3

# Optional. Defaults to sqlite:///db/agro_mind.db
DATABASE_URL=sqlite:///db/agro_mind.db

# Optional logging/UI settings
LOG_LEVEL=INFO
AGRO_MIND_API_URL=http://localhost:8000
```

The app creates database tables and seeds products on API startup. You can also
run the seed step directly:

```bash
python -m db.seed
```

## Knowledge Base Ingestion

The catalog parser reads:

```text
tra/1/1.2/ProductCatalog_Translated_EN.xlsx
```

To build the Chroma vector store used by retrieval tools:

```bash
python -m rag.ingest
```

This writes generated vector data under `db/chroma_db/`, which is intentionally
ignored by git.

## Run Locally

Start the API:

```bash
uvicorn main:app --reload --port 8000
```

Open the API docs:

```text
http://localhost:8000/docs
```

Start the Streamlit UI in another shell:

```bash
streamlit run frontend/app.py
```

Point the UI at a different API host:

```bash
AGRO_MIND_API_URL=http://localhost:8000 streamlit run frontend/app.py
```

Sign in from the Streamlit UI before using chat, cart, orders, treatment plans,
or history. The backend rejects authenticated routes with `401` when the
session is missing, logged out, or unknown.

## API Overview

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | API welcome payload |
| `GET` | `/health` | Liveness, configured model names, and API key status |
| `GET` | `/catalog` | Full catalog listing |
| `GET` | `/catalog/preview` | Small product preview list for the UI |
| `POST` | `/login` | Create or authenticate a customer and return a session |
| `POST` | `/logout` | End the current authenticated session |
| `POST` | `/session/new` | Create a new chat session for the logged-in customer |
| `GET` | `/session` | Resume an active session from a saved session ID |
| `GET` | `/sessions` | List the customer's chat sessions |
| `GET` | `/profile` | Fetch the current customer profile |
| `POST` | `/profile` | Update name, location, or crop type |
| `GET` | `/history` | Fetch current-session or all-session chat history |
| `POST` | `/chat` | Main structured chat endpoint; login required |
| `POST` | `/chat_stream` | NDJSON streaming chat endpoint; login required |
| `GET` | `/cart` | Active session cart |
| `POST` | `/cart/add` | Add or increment a cart item |
| `POST` | `/cart/clear` | Clear the active cart |
| `POST` | `/checkout` | Convert cart items into orders, optionally creating treatment plans |
| `GET` | `/orders` | List session orders |
| `GET` | `/order/{order_id}` | Fetch one order |
| `GET` | `/treatments` | List active treatment plans |
| `GET` | `/tasks/today` | List today's treatment tasks |
| `GET` | `/followups/due` | List due follow-up tasks for the session |
| `POST` | `/tasks/done` | Toggle a treatment task as complete |

Example login request:

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "demo-farmer",
    "password": "demo-password"
  }'
```

Example chat request:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-session",
    "message": "My tomato leaves have brown spots. What should I do?"
  }'
```

For image diagnosis, include `image_base64` with a base64-encoded image.
For order-specific logistics or product-usage questions, include `order_id`.

Checkout accepts `create_treatment_plan: true` when the customer consents to
turn cart items into daily treatment tasks. Group-buy cart items must meet the
configured minimum quantity before checkout succeeds.

## Tests and Checks

Run the automated test suite:

```bash
pytest
```

Run focused evaluation scripts:

```bash
python -m evaluation.check_safety
python -m evaluation.check_intent
```

The tests cover catalog parsing/search, safety interception, intent routing,
agent behavior, login/session isolation, pesticide memory, checkout-created
treatments, group-buy validation, and cart/order behavior.

## Development Notes

- Runtime SQLite databases and Chroma indexes are generated under `db/` and are
  ignored by git.
- The API lazily initializes the agent, but startup also warms the model
  connection after database init/seed.
- Chat, cart, order, profile, history, and treatment endpoints require an
  authenticated DB-backed session.
- `/chat_stream` returns newline-delimited JSON events with `token`,
  `metadata`, or `error` types.
- Product details should come from retrieved catalog context. The agent is
  instructed not to invent product names, prices, dosage, or ingredients.
- Pesticide memory is derived from active cart rows and shipped/out-for-delivery
  orders instead of free-form LLM memory.
- Treatment plans shown in the UI are created only during checkout when
  `create_treatment_plan` is true.
- Safety-sensitive messages short-circuit before normal intent routing and
  return a human escalation response.

## Troubleshooting

**`api_key_configured` is false in `/health`**

Set `QWEN_API_KEY` or `DASHSCOPE_API_KEY` in `.env`, then restart the API.

**Product recommendations say the knowledge base is unavailable**

Run `python -m rag.ingest` and confirm `db/chroma_db/` was created.

**Chat returns `401 Login is required`**

Log in through the UI or call `POST /login`, then pass the returned `session_id`
to chat, cart, order, profile, and treatment endpoints.

**The API starts but no products appear**

Confirm `tra/1/1.2/ProductCatalog_Translated_EN.xlsx` exists, then run
`python -m db.seed`.

**MySQL connection fails**

Check that `DATABASE_URL` uses a valid SQLAlchemy URL and that the matching
database driver is installed in the virtual environment.
