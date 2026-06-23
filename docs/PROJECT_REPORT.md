# Agro-Mind Agent Project Structure Report

## 1. Purpose

This report explains the structure of the Agro-Mind Agent project: what the
main modules are, what each feature does, how APIs and tools are organized,
how data moves through the system, and how the frontend, backend, agent,
database, retrieval, and safety layers work together.

It is an implementation structure reference for understanding and reviewing the
current project.

## 2. High-Level Architecture

Agro-Mind Agent is structured as a stateful agricultural support application.
It combines a Streamlit frontend, FastAPI backend, LangGraph agent, Qwen model
adapters, catalog retrieval, SQLAlchemy persistence, and safety interception.

```text
Streamlit UI
    |
    | HTTP JSON / NDJSON streaming
    v
FastAPI API
    |
    +-- Auth/session validation
    +-- Chat/catalog/profile/cart/order/treatment routes
    |
    v
LangGraph Agent
    |
    +-- Safety check
    +-- Intent routing
    +-- Diagnosis / product / logistics / general handlers
    +-- Memory update
    |
    +-- Qwen chat / vision models
    +-- Chroma retrieval
    +-- Local XLSX catalog fallback
    |
    v
SQLAlchemy Database
    |
    +-- Customers, sessions, messages, products
    +-- Carts, orders, treatments, escalations
```

The user-facing product is a signed-in agricultural assistant that can diagnose
crop issues, recommend catalog-backed products, answer usage questions, manage
carts and orders, and track treatment tasks.

## 3. Project Directory Structure

| Path | Role |
| --- | --- |
| `main.py` | FastAPI application entry point and API route definitions. |
| `frontend/app.py` | Streamlit UI for login, chat, image upload, profile, cart, checkout, product cards, and treatment tasks. |
| `agent/` | LangGraph orchestration, prompts, LLM factories, tools, and weather context. |
| `db/` | SQLAlchemy engine, ORM models, seed script, and customer-state service functions. |
| `memory/` | DB-backed customer memory wrapper used by the agent. |
| `rag/` | Product catalog loader, Chroma ingestion, crop/advisory source data. |
| `safety/` | Pre-LLM safety interceptor. |
| `tools/` | Additional commerce/agriculture helper utilities. |
| `evaluation/` | Scripted intent, safety, and end-to-end evaluation assets. |
| `tests/` | Pytest regression tests. |
| `tra/` | Translation scripts and translated/source catalog datasets. |
| `docs/` | Product and implementation documentation. |

## 4. Backend Structure

The backend is implemented in `main.py`. It owns the HTTP boundary and converts
frontend requests into agent/database operations.

### FastAPI App Setup

Main backend responsibilities:

- load environment variables
- create the FastAPI app
- enable CORS
- initialize database tables on startup
- seed products on startup
- warm the singleton agent

The singleton agent is created lazily through:

- `get_agent()`

Startup is handled by:

- `lifespan(app)`

### Request And Response Models

Implemented Pydantic models:

| Model | Purpose |
| --- | --- |
| `ChatRequest` | Chat input with `session_id`, message text, optional image, optional order ID. |
| `ChatResponse` | Structured agent output returned to frontend. |
| `LoginRequest` | Username/password login or account creation payload. |
| `LogoutRequest` | Session invalidation payload. |
| `SessionRequest` | Session-scoped actions such as new session, cart clear, checkout. |
| `ProfileUpdateRequest` | Editable customer profile fields. |
| `CartAddRequest` | Product, quantity, and group-buy state for cart additions. |
| `TaskDoneRequest` | Treatment task toggle payload. |

### API Routes

| Method | Route | Structure Role |
| --- | --- | --- |
| `GET` | `/` | API welcome and docs pointer. |
| `GET` | `/health` | Backend/model configuration health summary. |
| `GET` | `/catalog` | Full catalog listing from `rag.catalog_loader`. |
| `GET` | `/catalog/preview` | Small catalog preview for the UI. |
| `POST` | `/login` | Creates or authenticates a password-backed demo customer. |
| `POST` | `/logout` | Ends the active DB session. |
| `POST` | `/session/new` | Creates a new authenticated chat session for the current customer. |
| `POST` | `/chat` | Non-streaming structured agent response. |
| `POST` | `/chat_stream` | Streaming NDJSON agent response. |
| `GET` | `/profile` | Customer profile and pesticide memory. |
| `POST` | `/profile` | Updates profile fields. |
| `GET` | `/history` | Customer chat history across sessions. |
| `GET` | `/cart` | Active customer cart. |
| `POST` | `/cart/add` | Add/increment product in cart. |
| `POST` | `/cart/clear` | Clear active cart and create a fresh one. |
| `POST` | `/checkout` | Convert cart items into demo shipped orders. |
| `GET` | `/orders` | Customer-scoped order list. |
| `GET` | `/order/{order_id}` | Single customer-owned order. |
| `GET` | `/treatments` | Active treatment plans for purchased/shipped products. |
| `GET` | `/tasks/today` | Pending treatment tasks due today. |
| `GET` | `/followups/due` | Due follow-up/task data scoped to the session/customer. |
| `POST` | `/tasks/done` | Toggle a treatment task done/undone. |

Most customer-state routes ultimately validate the session through
`_ensure_customer()` in `db/customer_state.py`. Chat, cart, profile, orders,
and treatments are therefore authenticated customer flows, not anonymous
session-only flows.

## 5. Frontend Structure

The frontend is implemented in `frontend/app.py` using Streamlit.

### Main UI Areas

The UI is organized around:

- top navigation and backend connection state
- sign-in/create-account popover
- logout action
- chat view
- profile view
- product cards
- right-side cart/treatment rail
- footer

### Chat UI

The chat view supports:

- text messages
- image upload and preview
- quick prompt buttons
- streamed assistant output
- intent badges
- safety banners
- product recommendation cards
- product carousel controls when multiple products are returned

Key chat functions:

- `_send_message()`
- `_stream_turn()`
- `_process_turn()`
- `_render_uploaded_image()`
- `_render_composer_upload_preview()`
- `_render_response_loader()`
- `_intent_badge()`

### Product And Cart UI

Product card rendering is separated from generated answer text. The agent
returns `matched_products`, and the frontend renders trusted catalog fields.

Key functions:

- `_render_product_card()`
- `_product_row()`
- `_price_text()`
- `_clean_product_value()`
- `_cart_add()`
- `_get_cart()`
- `_checkout()`

The UI supports both single purchase and group buy. Group buy quantity rules
are enforced by the backend.

### Account And Profile UI

The frontend stores login state in Streamlit session state and synchronizes it
with the backend session ID.

Key functions:

- `_login_customer()`
- `_logout_customer()`
- `_start_new_customer_session()`
- `_apply_logged_in_session()`
- `_apply_logged_out_session()`
- `_is_logged_in()`
- `_reset_local_conversation()`
- `_clear_session_caches()`
- `_render_profile_view()`

The profile view displays signed-in user information, crop, location, editable
profile fields, and recent memory.

### Treatment UI

Treatment plans and daily tasks are shown in the rail.

Key functions:

- `_fetch_treatments()`
- `_get_treatments()`
- `_mark_task_done()`

Task updates call `/tasks/done`, then cached treatment data is cleared.

## 6. Agent Structure

The agent is implemented in `agent/orchestrator.py` with LangGraph.

### Core Types

| Type | Purpose |
| --- | --- |
| `AgentState` | LangGraph state object passed between nodes. |
| `AgentResponse` | Backend-facing response contract. |
| `AgroMindAgent` | Public wrapper used by FastAPI. |
| `_NoopMemory` | Fallback memory adapter if persistence is unavailable. |

### Graph Nodes

| Node | Purpose |
| --- | --- |
| `safety_check_node()` | First node. Blocks unsafe pesticide/self-harm/chemical exposure cases. |
| `intent_node()` | Classifies safe messages into diagnosis, product, logistics, or general. |
| `diagnosis_node()` | Handles text and image crop diagnosis. |
| `product_node()` | Handles recommendations and catalog-grounded usage questions. |
| `logistics_node()` | Answers order/shipping questions using customer-owned order context. |
| `general_node()` | Handles greetings, memory-aware answers, and weather-aware timing questions. |
| `memory_node()` | Updates long-term profile/memory fields after a turn. |

### Routing

Routing helpers:

- `route_after_safety()`
- `route_intent()`

The graph always starts with safety:

```text
safety_check_node
    |
    +-- unsafe -> memory_node -> END
    |
    +-- safe -> intent_node
                 |
                 +-- Diagnosis -> diagnosis_node -> memory_node -> END
                 +-- Product   -> product_node   -> memory_node -> END
                 +-- Logistics -> logistics_node -> memory_node -> END
                 +-- General   -> general_node   -> memory_node -> END
```

### Public Agent Methods

`AgroMindAgent.run()` is the non-streaming path. It:

- persists the user turn
- invokes the LangGraph app
- persists the assistant turn
- extracts `[PRODUCT: ID]` tags
- loads matching catalog product records
- strips hidden product tags from visible text
- returns `AgentResponse`

`AgroMindAgent.stream()` is the streaming path. It:

- streams LLM token chunks when the active node supports async token output
- tracks final LangGraph state snapshots
- persists user/assistant turns in background threads
- applies the same product-tag and product-card post-processing as `run()`
- yields final metadata as an NDJSON event

## 7. Agent Tools Structure

The main LangGraph flow uses `agent/tools.py`.

### Intent And Retrieval Tools

| Function | Purpose |
| --- | --- |
| `classify_intent()` | Deterministic keyword classifier for diagnosis, product, logistics, general. |
| `retrieve_agronomy_knowledge()` | Queries Chroma for product/agronomy context. |
| `recommend_product()` | Selects catalog-backed recommendations and emits hidden product tags. |
| `_local_catalog_recommendation()` | Fallback recommendation path when Chroma is unavailable or empty. |
| `_mentions_catalog_product()` | Detects direct catalog product references in user text. |

### Vision Tool

| Function | Purpose |
| --- | --- |
| `analyze_crop_image()` | Sends a base64 image to the Qwen vision model for crop/pest/disease analysis. |

### Safety Tools

| Function | Purpose |
| --- | --- |
| `_chemical_exposure_risk()` | Checks direct chemical exposure terms. |
| `detect_escalation_risk()` | Combines chemical exposure checks with `SafetyInterceptor`. |
| `create_human_alert()` | Creates an escalation record and returns a safe stop message. |

### Memory/Profile Tools

| Function | Purpose |
| --- | --- |
| `_get_context_string_no_init()` | Reads profile context without creating a session row. |
| `_fetch_profile_bg()` | Background profile-cache population helper. |
| `update_customer_profile()` | Writes profile/memory updates through `CustomerMemory`. |
| `get_customer_profile()` | Reads customer profile with short TTL cache. |
| `invalidate_profile_cache()` | Clears cached profile state. |

### Supporting Utility Module

`tools/agriculture_tools.py` contains extra repository utilities:

- `track_order()`
- `initiate_refund()`
- `request_invoice()`
- `search_products()`
- `get_product()`
- `get_weather_forecast()`
- `analyze_soil()`

These utilities are part of the project, but the current main agent path imports
and uses the tools in `agent/tools.py`.

## 8. Safety Structure

Safety scanning is centered in `safety/interceptor.py`.

Core objects:

- `SafetyResult`
- `SafetyInterceptor`

The safety scanner detects:

- self-harm phrases
- suicide intent
- intentional pesticide or herbicide ingestion
- poisoning another person
- dangerous chemical combinations
- regex variants of unsafe phrasing

The safety flow is structural, not decorative. It is the first agent graph
node, and unsafe messages do not proceed to normal intent routing or product
recommendation.

Escalation persistence is handled by:

- `create_human_alert()` in `agent/tools.py`
- `create_escalation()` in `db/customer_state.py`
- `Escalation` model in `db/models.py`

## 9. Catalog And RAG Structure

Catalog loading is implemented in `rag/catalog_loader.py`.

### Catalog Source

```text
tra/1/1.2/ProductCatalog_Translated_EN.xlsx
```

### Product Record Fields

`ProductRecord` contains:

- `product_id`
- `product_name`
- `english_name`
- `product_type`
- `crops`
- `specification`
- `main_ingredients`
- `how_to_use`
- `water_ratio`
- `group_price`
- `single_price`

### Catalog Functions

| Function | Purpose |
| --- | --- |
| `_load_catalog()` | Parses the XLSX catalog into records. |
| `get_catalog()` | Returns the module-level catalog cache. |
| `search_catalog()` | Keyword search across product fields. |
| `get_product_by_id()` | Case-insensitive product lookup. |
| `all_products_summary()` | Compact text summary of all products. |

### Chroma Ingestion

`rag/ingest.py` builds vector documents from:

- product catalog records
- `rag/Crop_recommendation.csv`
- `rag/farmer_advisory_full.csv`

Runtime retrieval is optional. If the vector store is unavailable, the agent
falls back to local catalog keyword search.

## 10. LLM Provider Structure

Model configuration is isolated in `agent/llm.py`.

Factories:

- `get_chat_llm()`
- `get_vision_llm()`
- `get_embeddings()`

Environment variables:

- `QWEN_API_KEY`
- `DASHSCOPE_API_KEY`
- `QWEN_BASE_URL`
- `QWEN_MODEL`
- `QWEN_VISION_MODEL`
- `QWEN_EMBED_MODEL`

Defaults:

- Qwen-compatible base URL:
  `https://dashscope.aliyuncs.com/compatible-mode/v1`
- text model: `qwen-turbo`
- vision model: `qwen-vl-plus`
- embedding model: `text-embedding-v3`

The rest of the project uses LangChain's OpenAI-compatible classes, while this
module points those classes at DashScope/Qwen.

## 11. External Weather Structure

External web context is limited to weather and spray timing in
`agent/web_context.py`.

Functions:

- `asks_for_web_context()`
- `extract_location_hint()`
- `get_weather_context()`
- `format_web_context_for_prompt()`

The code calls Open-Meteo geocoding and forecast APIs. The returned context is
only used for agronomic timing questions such as weather, rain, wind, humidity,
temperature, season, and spray timing. It is not used for product identity,
dosage, price, or catalog claims.

## 12. Database Structure

SQLAlchemy models live in `db/models.py`. Engine/session setup lives in
`db/engine.py`.

### Engine Layer

`db/engine.py` defines:

- `DATABASE_URL`
- `engine`
- `SessionLocal`
- `Base`
- `get_session()`
- `init_db()`
- `_migrate_existing_schema()`
- `_safe_url()`

It supports SQLite locally and MySQL-style connection settings when the
database URL uses a MySQL dialect.

### ORM Models

| Model | Table | Role |
| --- | --- | --- |
| `Customer` | `customers` | Account, profile, password hash, crop/location, last product. |
| `Session` | `sessions` | Authenticated chat sessions and lifecycle state. |
| `Message` | `messages` | User and assistant turns. |
| `MessageAttachment` | `message_attachments` | Uploaded image data linked to messages. |
| `Product` | `products` | Seeded product catalog. |
| `Diagnosis` | `diagnoses` | Structured crop issue records. |
| `Cart` | `carts` | Active, converted, cleared, or abandoned carts. |
| `CartItem` | `cart_items` | Product quantities, prices, group-buy flags. |
| `Order` | `orders` | Demo orders, shipment status, tracking metadata. |
| `Refund` | `refunds` | Refund state. |
| `Escalation` | `escalations` | Safety escalation tickets. |
| `FollowUp` | `follow_ups` | Proactive follow-up records. |
| `Treatment` | `treatments` | Active treatment plans and daily task JSON. |

## 13. Customer State Service Structure

`db/customer_state.py` is the service layer over the ORM. It contains the core
business operations used by APIs and agent tools.

### Auth And Session Functions

- `_hash_password()`
- `_verify_password()`
- `_new_session_id()`
- `_customer_login_payload()`
- `_ensure_customer()`
- `require_authenticated_session()`
- `login_customer()`
- `logout_customer()`
- `create_customer_session()`

### Cart And Checkout Functions

- `GROUP_BUY_MIN_QUANTITY`
- `_validate_group_buy_quantity()`
- `_active_cart()`
- `_cart_to_dict()`
- `get_cart()`
- `add_cart_item()`
- `clear_cart()`
- `checkout_cart()`

Group buy is enforced at the service layer. The current minimum is 10 units.

### Order Functions

- `_order_to_dict()`
- `list_orders()`
- `get_order()`
- `get_order_context()`

Order access is customer-scoped to prevent one session from reading another
customer's orders.

### Profile And History Functions

- `get_profile()`
- `update_profile()`
- `get_chat_history()`
- `get_all_customer_histories()`
- `list_customers()`
- `create_diagnosis()`

History is retrieved across all sessions for the authenticated customer.

### Pesticide Memory Functions

- `get_pesticide_memory_for_customer()`
- `format_pesticide_memory_lines()`
- `get_pesticide_memory()`

Pesticide memory is derived from active carts and shipped/out-for-delivery/
delivered pesticide orders. This lets the agent answer follow-up usage
questions such as "how do I use it?" based on actual cart/order state.

### Treatment And Task Functions

- `_checkout_treatment_details()`
- `_create_checkout_treatment()`
- `_treatment_to_dict()`
- `_generate_daily_tasks()`
- `add_treatment()`
- `mark_task_done()`
- `get_active_treatments()`
- `get_todays_tasks()`

Checkout can create visible treatment plans. Active treatments are filtered to
products that have been purchased and are in shipped, out-for-delivery, or
delivered order states.

### Escalation Function

- `create_escalation()`

This creates safety tickets in the `escalations` table.

## 14. Memory Structure

`memory/customer_memory.py` provides the agent-facing memory abstraction.

Class:

- `CustomerMemory`

Methods:

- `_ensure_session()`
- `_customer_session_ids()`
- `update()`
- `get_context_string()`
- `chat_history()`
- `append_turn()`
- `load()`

Memory stores and retrieves:

- customer profile fields
- session links
- conversation messages
- uploaded image attachments
- recent diagnosis markers
- last recommended product
- cross-session customer context
- pesticide memory lines derived from commerce state

The agent calls this wrapper instead of writing directly to ORM models.

## 15. Feature Structure Map

| Feature | Frontend | API | Agent/Service | Persistence |
| --- | --- | --- | --- | --- |
| Login/create account | Sign-in popover | `/login` | `login_customer()` | `customers`, `sessions` |
| Logout | Logout button | `/logout` | `logout_customer()` | `sessions` |
| New chat session | Session action | `/session/new` | `create_customer_session()` | `sessions` |
| Chat | Chat composer | `/chat`, `/chat_stream` | `AgroMindAgent` | `messages` |
| Image diagnosis | Image uploader | `/chat`, `/chat_stream` | `diagnosis_node()`, `analyze_crop_image()` | `messages`, `message_attachments` |
| Safety escalation | Safety banner | `/chat`, `/chat_stream` | `safety_check_node()`, `create_human_alert()` | `escalations` |
| Product recommendation | Product cards | chat response metadata | `recommend_product()` | `products` |
| Usage answer | Chat | `/chat`, `/chat_stream` | `product_node()`, `_resolve_usage_product()` | `orders`, `cart_items`, `products` |
| Profile | Profile page | `/profile` | `get_profile()`, `update_profile()` | `customers` |
| History/memory | Profile memory panel | `/history` | `get_chat_history()` | `messages` |
| Cart | Cart rail | `/cart`, `/cart/add`, `/cart/clear` | `get_cart()`, `add_cart_item()`, `clear_cart()` | `carts`, `cart_items` |
| Checkout | Checkout button | `/checkout` | `checkout_cart()` | `orders`, `treatments` |
| Orders | Order context in chat | `/orders`, `/order/{order_id}` | `list_orders()`, `get_order_context()` | `orders` |
| Treatments | Treatment rail | `/treatments` | `get_active_treatments()` | `treatments` |
| Daily tasks | Task checkboxes | `/tasks/today`, `/tasks/done` | `get_todays_tasks()`, `mark_task_done()` | `treatments.daily_tasks` |
| Weather timing | Chat answer | chat routes | `agent/web_context.py`, `general_node()` | none |

## 16. Main Data Flows

### Login Flow

```text
Frontend sign-in form
    -> POST /login
    -> login_customer()
    -> Customer + authenticated Session
    -> frontend stores session_id and active_customer
```

### Chat Flow

```text
Frontend chat message
    -> POST /chat_stream or /chat
    -> require_authenticated_session()
    -> AgroMindAgent
    -> safety_check_node()
    -> intent_node()
    -> selected handler node
    -> memory_node()
    -> product-tag post-processing
    -> ChatResponse / NDJSON metadata
    -> frontend message + optional product cards
```

### Product Recommendation Flow

```text
User crop issue / product request
    -> classify_intent()
    -> diagnosis_node() or product_node()
    -> retrieve_agronomy_knowledge()
    -> recommend_product()
    -> [PRODUCT: ID] hidden tags
    -> get_product_by_id()
    -> matched_products
    -> Streamlit product cards
```

### Cart And Checkout Flow

```text
Product card action
    -> POST /cart/add
    -> add_cart_item()
    -> active Cart + CartItem
    -> POST /checkout
    -> checkout_cart()
    -> Order rows
    -> checkout-created Treatment rows
```

### Treatment Task Flow

```text
Checkout-created treatment
    -> _generate_daily_tasks()
    -> treatment daily_tasks JSON
    -> GET /treatments or /tasks/today
    -> frontend task checkbox
    -> POST /tasks/done
    -> mark_task_done()
```

### Safety Flow

```text
User message
    -> safety_check_node()
    -> detect_escalation_risk()
    -> SafetyInterceptor + chemical exposure terms
    -> create_human_alert()
    -> create_escalation()
    -> safety stop response
```

## 17. Evaluation And Test Structure

Tests live in `tests/`:

- `test_agent.py`
- `test_catalog.py`
- `test_checkout_treatments.py`
- `test_group_buy.py`
- `test_login_session.py`
- `test_pesticide_memory.py`
- `test_product_recommendation.py`
- `test_safety.py`

Evaluation scripts live in `evaluation/`:

- `golden_cases.jsonl`
- `check_intent.py`
- `check_safety.py`
- `run_eval.py`

These files cover the structural behaviors of the project: intent routing,
safety interception, catalog parsing/search, group-buy validation, login and
session isolation, pesticide memory, product recommendation/product cards, and
treatment creation after checkout.

## 18. Runtime Configuration Structure

Important configuration variables:

| Variable | Used By | Purpose |
| --- | --- | --- |
| `QWEN_API_KEY` | `agent/llm.py` | DashScope/Qwen API key. |
| `DASHSCOPE_API_KEY` | `agent/llm.py` | Alternate DashScope API key variable. |
| `QWEN_BASE_URL` | `agent/llm.py` | OpenAI-compatible DashScope base URL override. |
| `QWEN_MODEL` | `agent/llm.py`, `/health` | Text model name. |
| `QWEN_VISION_MODEL` | `agent/llm.py`, `/health` | Vision model name. |
| `QWEN_EMBED_MODEL` | `agent/llm.py` | Embedding model name. |
| `DATABASE_URL` | `db/engine.py` | SQLAlchemy database URL. |
| `LOG_LEVEL` | `main.py` | Backend logging level. |
| `AGRO_MIND_API_URL` | `frontend/app.py` | Backend URL for Streamlit. |

Runtime/generated local assets include:

- `db/agro_mind.db`
- `db/chroma_db/`
- `.streamlit/config.toml`
- `.streamlit/credentials.toml`

## 19. Implementation Boundaries

Implemented:

- authenticated demo users and sessions
- Streamlit chat/profile/cart/treatment UI
- FastAPI APIs for all active app surfaces
- LangGraph safety-first agent flow
- Qwen chat, vision, and embedding adapters
- Chroma retrieval with local catalog fallback
- catalog-backed product cards
- group-buy minimum validation
- demo checkout/orders/tracking numbers
- treatment plans and task toggles
- pesticide memory from cart/order state
- Open-Meteo spray-timing context
- SQLAlchemy persistence
- pytest and scripted evaluation assets

Not implemented as production integrations:

- live Pinduoduo payment/checkout
- live courier tracking
- production auth hardening
- human escalation dashboard
- broad web search
- deployment monitoring

## 20. Summary

The project structure is organized around a clear flow: authenticated Streamlit
user actions call FastAPI routes, routes validate customer sessions and call
the LangGraph agent or customer-state services, the agent performs safety-first
routing and catalog-grounded reasoning, SQLAlchemy stores customer and commerce
state, and the frontend renders structured outputs as chat messages, product
cards, carts, orders, and treatment tasks.

The strongest structural patterns are:

- safety as the first graph node
- product facts rendered from catalog records instead of free-form text
- customer/session scoping at the service layer
- pesticide memory derived from cart/order state
- checkout linked to treatment task creation
- frontend actions mapped cleanly to backend APIs
