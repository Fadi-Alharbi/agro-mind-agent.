# Agro-Mind Agent Product Requirements Document

## 1. Product Summary

Agro-Mind Agent is a multimodal AI customer-support assistant for an
agricultural products store serving farmers and buyers, especially mobile users
asking from field conditions. The product combines crop diagnosis, safe product
guidance, catalog-backed recommendations, group-buy cart flows, order tracking,
customer memory, and treatment follow-up tasks in one chat-first experience.

The current implementation is a local/prototype system with these major parts:

- FastAPI backend in `main.py`
- Streamlit frontend in `frontend/app.py`
- LangGraph agent in `agent/orchestrator.py`
- Qwen/DashScope text, vision, and embedding adapters in `agent/llm.py`
- Safety interceptor in `safety/interceptor.py`
- Catalog parsing and search in `rag/catalog_loader.py`
- Chroma ingestion in `rag/ingest.py`
- SQLAlchemy persistence in `db/models.py`, `db/engine.py`, and
  `db/customer_state.py`
- Customer/session memory wrapper in `memory/customer_memory.py`
- Regression tests under `tests/`

## 2. Problem Statement

Agricultural buyers ask support questions that often combine crop symptoms,
pesticide use, dosage, shipping, invoices, refunds, and safety concerns. A
generic chatbot can hallucinate product details, miss poisoning/self-harm
language, fail to preserve order context, or recommend products that are not in
the store catalog.

Agro-Mind must answer quickly while keeping high-risk safety handling ahead of
commerce, grounding product claims in the catalog, and preserving structured
state for follow-up support.

## 3. Target Users

### Farmers and Buyers

- Often use a phone with one hand in bright outdoor conditions.
- Need short, readable, actionable answers.
- Need crop diagnosis, product selection, dosage/usage guidance, delivery
  status, invoice/refund help, and treatment reminders.
- Are not expected to understand backend concepts, product IDs, or model limits.

### Store Support Team

- Needs safety escalations before automated product guidance continues.
- Needs concise summaries for risky pesticide exposure or self-harm messages.
- Needs order, customer, and conversation context to reduce repeated questions.

### Developers and Operators

- Need a runnable local prototype using SQLite by default.
- Need optional support for SQLAlchemy-compatible remote databases such as MySQL.
- Need documented API contracts, database tables, environment variables, and
  test coverage.

## 4. Product Goals

- Provide concise crop diagnosis and next steps from text or optional image
  input.
- Recommend only products that can be traced to the local catalog or retrieved
  knowledge base.
- Separate assistant prose from structured product cards so prices, dosage,
  ingredients, and product names render from trusted catalog records.
- Run safety checks before normal routing and before any product recommendation.
- Stream LLM-backed responses so the user sees text quickly.
- Persist customer sessions, messages, uploaded-image attachments, profile
  fields, cart state, orders, treatments, tasks, and escalations.
- Support cart add, cart clear, checkout, order list, order lookup, and
  treatment task toggling through backend APIs.
- Keep the UI quiet, legible, mobile-friendly, and focused on conversation.

## 5. Non-Goals

- Replace agronomists, emergency services, poison control, licensed medical
  professionals, or human support.
- Certify pesticide legality, label compliance, or regional registration status.
- Process real payments.
- Integrate with live Pinduoduo APIs in the current prototype.
- Provide a production staff inbox or full admin dashboard.
- Provide robust authentication or role-based access control in the current
  backend API.
- Guarantee model output correctness without catalog/database verification.

## 6. User Stories

- As a farmer, I can describe crop symptoms and receive a likely diagnosis,
  practical steps, and at most one important follow-up question.
- As a farmer, I can upload a crop image and receive image-assisted diagnosis.
- As a buyer, I can ask which product to use and receive product cards based on
  actual catalog data.
- As a buyer, I can ask how to use a named product or an ordered product and get
  catalog-grounded usage guidance.
- As a buyer, I can add a product to my cart as a single purchase or group buy.
- As a buyer, I cannot checkout a group-buy item below the minimum group-buy
  quantity.
- As a buyer, I can checkout and receive order IDs, tracking numbers, courier,
  shipped-from location, and estimated delivery.
- As a buyer, I can ask about recent orders or a specific order ID.
- As a returning customer, I can receive context-aware follow-up from previous
  crop issues, profile fields, and active treatments.
- As a support operator, I can rely on poisoning, pesticide exposure, or
  self-harm messages being escalated before automated product guidance.

## 7. System Architecture

```text
Streamlit UI
  |
  | HTTP JSON + NDJSON streaming
  v
FastAPI API
  |
  +-- safety/interceptor.py      pre-LLM self-harm / pesticide risk screen
  +-- agent/orchestrator.py      LangGraph flow and response contract
  +-- agent/tools.py             intent, retrieval, vision, product, profile tools
  +-- agent/web_context.py       optional weather/local context for timing questions
  +-- rag/catalog_loader.py      XLSX catalog parser and keyword search
  +-- rag/ingest.py              Chroma vector-store ingestion
  +-- db/customer_state.py       transactional cart/order/profile/treatment helpers
  +-- db/models.py               SQLAlchemy ORM schema
  +-- memory/customer_memory.py  session and cross-session memory
```

The backend starts by calling `init_db()` and `seed_products()` during FastAPI
lifespan startup. These operations must be idempotent and must not block service
startup permanently; startup logs a warning if they fail.

## 8. Functional Requirements

### 8.1 Chat Request Handling

- The backend must accept chat requests through `POST /chat`.
- The backend must accept streaming chat requests through `POST /chat_stream`.
- `ChatRequest` must include:
  - `session_id`: string, defaults to a generated UUID if omitted.
  - `message`: required string, length 1 to 4000.
  - `image_base64`: optional base64-encoded image.
  - `order_id`: optional order identifier for logistics or usage context.
- Invalid base64 image input must return HTTP `400` with
  `Invalid base64 image data.`
- Backend failures during non-streaming chat must return HTTP `500`.
- Streaming failures must emit an NDJSON error event instead of breaking the
  client contract.

### 8.2 Chat Response Contract

Every final chat response must expose:

- `intent`: lower-case intent string, typically `diagnosis`, `product`,
  `logistics`, `general`, `general_qa`, `safety`, `safety_escalation`, or
  `greeting`.
- `safety_risk_detected`: boolean.
- `escalate_human`: boolean.
- `response_text`: customer-facing assistant text.
- `recommended_product_id`: first matched product ID or `null`.
- `group_purchase_triggered`: boolean indicating that product purchase UI should
  be shown for a recommendation.
- `human_summary_brief`: concise support summary or `null`.
- `matched_products`: list of catalog product dictionaries.
- `session_id`: echoed session ID.

The agent may use hidden product tags internally, such as `[PRODUCT: AF0035]`,
but these tags must not appear in the UI. They must be stripped before final
display and converted into `matched_products` records.

### 8.3 Streaming Requirements

- `POST /chat_stream` must return `application/x-ndjson`.
- Each streamed line must be valid JSON.
- Supported stream event shapes:
  - `{"type": "token", "content": "<text chunk>"}`
  - `{"type": "metadata", "data": {<ChatResponse>}}`
  - `{"type": "error", "content": "<message>"}`
- The frontend must render token events immediately in the active assistant
  bubble.
- Final product cards, badges, safety banners, and metadata-dependent UI must
  render only after the `metadata` event.
- Non-streaming `/chat` remains the fallback for compatibility.

### 8.4 Intent Routing

The agent must classify messages before selecting a work path:

- `Diagnosis`: crop disease, pest, symptom, plant-health, or image messages.
- `Product`: product recommendation, dosage, dilution, usage, purchase, price,
  product name, product ID, or order-specific usage questions.
- `Logistics`: order, shipping, delivery, tracking, courier, invoice, return,
  refund, damaged parcel, receipt, or ETA messages.
- `General`: ordinary agricultural QA or greeting messages.
- `Safety`: pesticide exposure, poisoning, breathing difficulty, self-harm, or
  suicide language.

Keyword routing should be preferred where deterministic checks are sufficient.
The router must recognize order IDs matching `PDD\d{14}-\d+-\d+`.

### 8.5 Safety and Human Escalation

- Safety checks must run before normal intent routing.
- The system must detect:
  - pesticide/herbicide ingestion
  - chemical exposure to eyes or skin
  - poisoning language
  - difficulty breathing after chemical exposure
  - direct or indirect self-harm language
  - suicide language
- Safety-triggered messages must:
  - skip product recommendation
  - set `safety_risk_detected=true`
  - set `escalate_human=true`
  - create an `escalations` database row when possible
  - return a customer-facing safety stop message
  - include support-summary metadata when available
- Safe dosage, harvest interval, shipping, product authenticity, angry customer,
  and livestock questions must not be falsely escalated unless they include
  actual poisoning/exposure/self-harm intent.

### 8.6 Crop Diagnosis

- Text diagnosis must retrieve catalog/agronomy context before asking the LLM
  for a concise answer.
- Image diagnosis must send the image to the configured vision model, then run
  product recommendation against the analysis.
- Diagnosis output must stay under approximately 150 words unless the user asks
  for detail.
- If confidence is low or information is missing, the assistant must state the
  limitation and ask at most one high-value follow-up question.
- Diagnosis text must not invent product names, product IDs, dosage, prices, or
  ingredients.

### 8.7 Product Recommendation

- Product details must originate from `rag/catalog_loader.py`, Chroma retrieval,
  or the seeded `products` table.
- The assistant must not invent:
  - product names
  - product IDs
  - ingredients
  - dosage or dilution
  - group/single prices
  - supported crops
  - shipping details
- Recommendations should end with hidden product tags for real matches:
  `[PRODUCT: AFXXXX]`.
- Legacy text marker `Product ID: AFXXXX` must still be accepted for backward
  compatibility.
- If no catalog match is suitable, the assistant must state that no suitable
  product was found and return general advice without any product card.
- Product usage questions for exact product IDs or names must resolve directly
  from the catalog.
- Product usage questions for an order must resolve the order first, then use
  the order's attached product ID.

### 8.8 Cart and Group Buy

- The system must maintain one active cart per customer.
- `GET /cart` must create and return an active cart if none exists.
- `POST /cart/add` must add or increment a cart item.
- Cart item fields must include product, quantity, unit price, line total,
  group-buy flag, source, and optional diagnosis link.
- Single purchase may use quantity 1 to 100.
- Group buy requires at least `10` units.
- Group-buy requests below 10 units must return a clear error.
- `POST /cart/clear` must mark the current active cart as `cleared` and return a
  fresh empty active cart.

### 8.9 Checkout and Orders

- `POST /checkout` must convert active cart items into one or more orders.
- Empty checkout must return HTTP `400` with `Cart is empty.`
- Checkout must reject group-buy items below 10 units.
- Each order created by checkout must include:
  - generated ID in the format `PDD<YYYYMMDDHHMMSS>-<customer_id>-<index>`
  - product ID
  - cart ID
  - optional diagnosis ID
  - quantity
  - total amount
  - group-buy flag
  - status
  - tracking number
  - courier
  - shipped-from location
  - estimated delivery
- Current prototype checkout marks orders as `shipped`, with courier
  `Postal Courier`, shipped from `Zhejiang Province`, and ETA
  `3-5 business days`.
- `GET /orders` must list only orders owned by the current session/customer.
- `GET /order/{order_id}` must return HTTP `404` if the order is not found for
  the current customer.

### 8.10 Customer Profile and History

- The backend must expose profile read/update endpoints.
- Editable profile fields:
  - `name`
  - `location`
  - `crop_type`
- Profile responses must also include:
  - `id`
  - `external_id`
  - `last_recommended_product`
  - `created_at`
- The backend must expose recent chat history through `/history`.
- Chat history must include role, content, intent, image presence, optional
  attachments, and timestamps.
- Cross-session memory should be customer-scoped when a customer identity is
  available.
- Profile lookup may be cached for performance but the database remains the
  source of truth.

### 8.11 Treatments and Daily Tasks

- The system must create treatment records when the agent extracts a product
  treatment from a diagnosis/product recommendation response.
- Treatment extraction may run in a background thread so the user response is
  not delayed.
- Treatment fields must include crop, disease, product ID, duration,
  instructions, quantity per dose, generated daily task list, status, start
  date, and creation date.
- Daily tasks must be generated from duration text when possible.
- Duration parsing should default to 5 days when duration is missing or has no
  number.
- Durations longer than 90 days should not generate tasks.
- `GET /treatments` must return active treatments for the current customer.
- `GET /tasks/today` must return incomplete tasks whose date is today.
- `POST /tasks/done` must toggle a task done/undone by `treatment_id` and day.
- A treatment should become `completed` when all generated tasks are done.
- `GET /followups/due` currently mirrors today's treatment tasks and must remain
  scoped to the caller's session/customer to avoid data leakage.

### 8.12 Frontend Experience

- The frontend must be implemented in Streamlit.
- The first screen must be the usable chat/product-support experience, not a
  marketing landing page.
- The UI must read the backend URL from `AGRO_MIND_API_URL`, defaulting to
  `http://localhost:8000`.
- The UI must show:
  - Agro-Mind top bar
  - backend connection status
  - sign-in/session switch popover
  - about popover with shipping/courier/session details
  - profile-loaded caption
  - chat history bubbles
  - starter prompts when empty
  - follow-up prompt chips during a conversation
  - inline image upload
  - uploaded image preview
  - streamed assistant response
  - intent badges
  - safety escalation banner
  - catalog product card carousel
  - quantity selector
  - single-purchase add button
  - group-buy add button disabled below 10 units
  - cart rail when cart has items
  - checkout and clear cart controls
  - treatment plan rail
  - daily treatment task checkboxes
  - profile editor/history sections in the rail
- The UI must hide internal product tags from visible assistant text.
- The UI must degrade clearly when the API is unavailable.
- The UI should use large touch targets, high contrast, restrained motion, and
  concise text suitable for phone use outdoors.

### 8.13 External Web and Weather Context

The current product does not implement broad, open-ended web search. It
implements controlled external web context for weather and agronomic timing
through `agent/web_context.py`.

- External web context may be used only for:
  - weather
  - climate
  - season
  - humidity
  - rain
  - temperature
  - wind
  - whether spraying today is appropriate
  - best time to spray
- The system must detect weather-context requests with `asks_for_web_context()`.
- The system must extract a supported location with `extract_location_hint()`.
- Supported location hints currently include:
  - Riyadh
  - Jeddah
  - Dammam
  - Dubai
  - Cairo
- If the user asks for weather-aware advice without a location, the assistant
  must ask for the city before using external context.
- `get_weather_context()` must call Open-Meteo geocoding and forecast APIs with
  short timeouts.
- `format_web_context_for_prompt()` must format temperature, humidity, rain,
  wind speed, location, and source for the LLM.
- External weather context must be labeled as external context in the prompt.
- External web/weather data must not be used to invent or verify:
  - product names
  - product IDs
  - ingredients
  - dosage or dilution
  - product prices
  - supported crops
  - order status
  - regulatory claims
- If Open-Meteo fails or returns no data, the system should continue without
  external context or ask for a clearer location.
- Future broad web search, if added, must be treated as a separate feature with
  explicit source allowlists, citations, freshness rules, and safety constraints.

## 9. API Requirements

| Method | Path | Request | Response / Behavior |
| --- | --- | --- | --- |
| `GET` | `/` | none | welcome payload with message, version, docs path |
| `GET` | `/health` | none | status, API key configured flag, model names, backend |
| `GET` | `/catalog` | none | `{count, products}` full catalog |
| `GET` | `/catalog/preview` | `limit` query, clamped 1-50 | bounded product preview |
| `POST` | `/chat` | `ChatRequest` | `ChatResponse` |
| `POST` | `/chat_stream` | `ChatRequest` | NDJSON token/metadata/error stream |
| `GET` | `/profile` | `session_id` query | customer profile |
| `POST` | `/profile` | `ProfileUpdateRequest` | updated profile |
| `GET` | `/history` | `session_id`, optional `limit` | recent customer messages |
| `GET` | `/cart` | `session_id` query | active cart |
| `POST` | `/cart/add` | `CartAddRequest` | updated active cart or HTTP `400` |
| `POST` | `/cart/clear` | `{session_id}` | fresh empty cart |
| `POST` | `/checkout` | `{session_id}` | created orders or HTTP `400` |
| `GET` | `/orders` | `session_id` query | customer orders |
| `GET` | `/order/{order_id}` | `session_id` query | one customer order or HTTP `404` |
| `GET` | `/treatments` | `session_id` query | active treatments |
| `GET` | `/tasks/today` | `session_id` query | today's pending treatment tasks |
| `GET` | `/followups/due` | `session_id` query | due follow-up/task list scoped to user |
| `POST` | `/tasks/done` | `TaskDoneRequest` | updated treatment |

### Request Models

```json
{
  "ChatRequest": {
    "session_id": "string",
    "message": "string, 1-4000 chars",
    "image_base64": "optional string",
    "order_id": "optional string"
  },
  "CartAddRequest": {
    "session_id": "string",
    "product_id": "string",
    "quantity": "integer, 1-100",
    "is_group_buy": "boolean, default true"
  },
  "SessionRequest": {
    "session_id": "string"
  },
  "ProfileUpdateRequest": {
    "session_id": "string",
    "name": "optional string",
    "location": "optional string",
    "crop_type": "optional string"
  },
  "TaskDoneRequest": {
    "session_id": "string",
    "treatment_id": "integer",
    "day": "integer"
  }
}
```

## 10. Data Requirements

### 10.1 Product Catalog Source

- Source path: `tra/1/1.2/ProductCatalog_Translated_EN.xlsx`
- Parser: `rag/catalog_loader.py`
- Seed script: `db/seed.py`
- Vector ingestion: `rag/ingest.py`
- Vector store path: `db/chroma_db/`

Each parsed product record must include:

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

The prototype has a fixed demo price map for selected product IDs and defaults
to group price `25.0` and single price `35.0` when no explicit demo price is
configured.

### 10.2 Relational Database

The database is SQLAlchemy-backed. `DATABASE_URL` controls the backend and
defaults to `sqlite:///db/agro_mind.db`. MySQL-style URLs are supported when the
appropriate driver is installed.

Tables and required fields:

#### `customers`

- `id`: integer primary key.
- `external_id`: optional unique indexed string.
- `name`: optional customer name.
- `location`: optional customer location.
- `crop_type`: optional primary crop.
- `last_recommended_product`: optional product ID.
- `created_at`: timestamp.

#### `sessions`

- `id`: string primary key, usually UUID/session identifier.
- `customer_id`: optional foreign key to `customers.id`.
- `last_intent`: optional last routed intent.
- `started_at`: timestamp.
- `last_active`: timestamp updated on change.

#### `messages`

- `id`: integer primary key.
- `session_id`: foreign key to `sessions.id`.
- `role`: `user` or `assistant`.
- `content`: message text.
- `intent`: optional routed intent.
- `has_image`: boolean.
- `created_at`: timestamp.

#### `message_attachments`

- `id`: integer primary key.
- `message_id`: foreign key to `messages.id`.
- `mime_type`: default `image/jpeg`.
- `data_base64`: stored base64 payload.
- `size_bytes`: decoded byte size when available.
- `created_at`: timestamp.

#### `products`

- `id`: product ID such as `AF0001`.
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
- `active`

#### `diagnoses`

- `id`: integer primary key.
- `customer_id`: foreign key to customer.
- `session_id`: optional session foreign key.
- `message_id`: optional source user message.
- `crop_type`: optional crop.
- `problem_summary`
- `diagnosis_text`
- `symptoms`
- `severity`: `low`, `medium`, `high`, `critical`, or `unknown`.
- `recommended_product_id`: optional product foreign key.
- `status`: `open`, `monitoring`, `resolved`, or `escalated`.
- `created_at`, `updated_at`.

#### `carts`

- `id`: integer primary key.
- `customer_id`: foreign key.
- `session_id`: optional session foreign key.
- `status`: `active`, `converted`, `abandoned`, or `cleared`.
- `created_at`, `updated_at`.

#### `cart_items`

- `id`: integer primary key.
- `cart_id`: foreign key.
- `product_id`: foreign key.
- `quantity`: integer.
- `unit_price`: float.
- `is_group_buy`: boolean.
- `source`: `recommended`, `manual`, or `follow_up`.
- `diagnosis_id`: optional diagnosis foreign key.
- `created_at`, `updated_at`.

#### `orders`

- `id`: string primary key.
- `customer_id`: optional foreign key.
- `product_id`: optional product foreign key.
- `cart_id`: optional cart foreign key.
- `diagnosis_id`: optional diagnosis foreign key.
- `quantity`: integer.
- `total_amount`: float.
- `is_group_buy`: boolean.
- `status`: `pending`, `paid`, `packed`, `shipped`, `out_for_delivery`,
  `delivered`, or `cancelled`.
- `tracking_number`
- `courier`
- `shipped_from`
- `estimated_delivery`
- `created_at`, `updated_at`.

#### `refunds`

- `id`: integer primary key.
- `order_id`: foreign key.
- `reason`
- `status`: `approved`, `under_review`, or `rejected`.
- `return_required`: boolean.
- `created_at`.

#### `escalations`

- `id`: integer primary key.
- `session_id`: indexed string.
- `risk_category`: required string.
- `triggered_phrase`: optional text.
- `human_summary`: optional text.
- `resolved`: boolean.
- `created_at`: timestamp.

#### `follow_ups`

- `id`: integer primary key.
- `customer_id`: foreign key.
- `order_id`: optional order foreign key.
- `product_id`: optional product foreign key.
- `diagnosis_id`: optional diagnosis foreign key.
- `due_at`: timestamp.
- `status`: `pending`, `sent`, `answered`, or `cancelled`.
- `result_note`: optional text.
- `created_at`.

#### `treatments`

- `id`: integer primary key.
- `customer_id`: foreign key.
- `session_id`: optional session foreign key.
- `start_date`: string `YYYY-MM-DD`.
- `crop`
- `disease`
- `product_id`: free string, not a foreign key.
- `duration`
- `instructions`
- `quantity_per_dose`
- `daily_tasks`: JSON list stored as text.
- `status`: `active`, `completed`, or `cancelled`.
- `created_at`.

### 10.3 Lightweight Schema Migration

`db/engine.py` currently uses `Base.metadata.create_all()` and a lightweight
`ALTER TABLE ADD COLUMN` helper for prototype schema drift. This is acceptable
for local/demo use. Production readiness requires a real migration tool such as
Alembic.

## 11. Model and Retrieval Requirements

- `QWEN_API_KEY` or `DASHSCOPE_API_KEY` must configure model access.
- `QWEN_BASE_URL` defaults to the DashScope OpenAI-compatible base URL.
- `QWEN_MODEL` defaults to `qwen-turbo` in the LLM adapter.
- `/health` reports `qwen-plus` as its default model label if the env var is
  absent, so health display and adapter defaults should be aligned in future.
- `QWEN_VISION_MODEL` defaults to `qwen-vl-plus`.
- `QWEN_EMBED_MODEL` defaults to `text-embedding-v3`.
- Chroma retrieval must read from `db/chroma_db/`.
- If Chroma cannot initialize, product recommendation must fall back to local
  catalog keyword search.
- Optional weather/web context may be used only for local weather, season, spray
  timing, or climate-related questions. It must not be used as authority for
  product identity, dosage, price, or catalog claims.

## 12. Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `QWEN_API_KEY` | yes for model-backed responses | DashScope/Qwen API key |
| `DASHSCOPE_API_KEY` | alternative | Alternative API key variable |
| `QWEN_BASE_URL` | optional | OpenAI-compatible DashScope base URL |
| `QWEN_MODEL` | optional | Text model |
| `QWEN_VISION_MODEL` | optional | Vision model |
| `QWEN_EMBED_MODEL` | optional | Embedding model |
| `DATABASE_URL` | optional | SQLAlchemy connection URL |
| `LOG_LEVEL` | optional | Backend log level |
| `AGRO_MIND_API_URL` | frontend optional | Backend URL for Streamlit |

Secrets must be kept in `.env` or deployment secret storage and must not be
committed.

## 13. Non-Functional Requirements

### Safety and Trust

- Safety screening must be pre-LLM and pre-commerce.
- Product cards must render from structured catalog records.
- The assistant must state uncertainty when evidence is insufficient.
- High-risk messages must stop automated guidance and create an escalation when
  possible.

### Performance

- Streaming should reduce perceived latency for LLM-backed paths.
- Intent classification should remain keyword-based where feasible.
- Profile reads may use a short in-memory TTL cache.
- Database helpers should open and close sessions per operation.
- Background threads may be used for non-critical memory/treatment persistence,
  but they must not change the final response contract.

### Reliability

- Local startup must work with SQLite defaults.
- Startup database initialization and product seeding must be idempotent.
- Chroma absence must not crash the product recommendation path.
- Invalid user input must produce explicit client errors.
- Order and follow-up routes must be scoped to the current session/customer.

### Security and Privacy

- Do not log API keys or database passwords.
- Mask database passwords in logs.
- Do not commit `.env`, runtime SQLite data, Chroma indexes, or user uploads.
- Uploaded images are currently persisted as base64 attachments when included in
  chat; retention policy must be defined before production use.
- The current session ID approach is not production authentication. Production
  use requires identity, authorization, CSRF/session protections as applicable,
  and per-user data access controls.

### Accessibility and UI Quality

- Target WCAG AA contrast.
- Use minimum 44px touch targets where possible.
- Avoid relying only on color for state.
- Respect reduced-motion preferences.
- Keep chat copy concise and readable outdoors.
- Keep empty UI panels subdued; show cart/treatment/shipment data only when it
  carries useful state.

## 14. Testing and Acceptance Criteria

### Local Startup

- `pip install -r requirements.txt` succeeds in a supported Python environment.
- `uvicorn main:app --reload --port 8000` starts the API.
- `GET /health` returns `status=ok`.
- `streamlit run frontend/app.py` starts the UI.
- The UI connects through `AGRO_MIND_API_URL`.

### Safety

- "I want to drink pesticide" escalates and does not recommend a product.
- Pesticide/herbicide eye, skin, ingestion, breathing, poisoning, and self-harm
  examples escalate.
- Safe dosage, shipping, harvest interval, authenticity, livestock, and angry
  customer examples do not escalate.
- Escalation writes to the `escalations` table when the database is available.

### Catalog and Retrieval

- `GET /catalog` returns parsed product records.
- `GET /catalog/preview?limit=8` returns only preview fields and clamps limit.
- `get_product_by_id()` is case-insensitive.
- Catalog search returns relevant products and respects `max_results`.
- Products have positive group and single prices.
- Chroma ingestion through `python -m rag.ingest` creates/updates
  `db/chroma_db/`.

### Chat and Routing

- Image input routes to diagnosis.
- Crop symptom text routes to diagnosis.
- Usage questions with product names or order IDs route to product handling.
- Order IDs without usage terms route to logistics.
- Short Arabic weed replies can use prior conversation context.
- Streaming emits token events for async LLM paths and metadata at completion.
- Product tags are hidden from the final UI and converted to product cards.

### Commerce

- Single item add succeeds with quantity 1.
- Group-buy add below 10 units fails.
- Group-buy add at 10 or more units succeeds.
- Cart clear returns a new empty active cart.
- Checkout creates orders and marks the cart converted.
- Order list and single order lookup are scoped to the current customer.

### Treatments

- Diagnosis/product recommendations can create treatment records in the
  background when extractable product treatment details exist.
- Active treatments appear in `/treatments`.
- Today's incomplete tasks appear in `/tasks/today`.
- `/tasks/done` toggles a specific treatment day.
- Treatments complete automatically when all tasks are done.

### Frontend

- Backend-offline state is visible and user-friendly.
- Starter prompts work on an empty chat.
- Follow-up chips work mid-conversation.
- Image upload preview appears before sending.
- Streamed text appears inside the assistant bubble.
- Safety responses render as safety banners.
- Product cards show catalog product data and purchase controls.
- Group-buy button is disabled below 10 units.
- Cart rail updates after add, clear, and checkout.
- Treatment task checkboxes update backend state.

### Web and Weather Context

- Weather-related questions with a supported city can include Open-Meteo
  temperature, humidity, rain, and wind context.
- Weather-related questions without a city ask the user for the city.
- External weather context is used only for spray timing/weather risk.
- Product identity, dosage, price, and catalog claims remain catalog/database
  grounded and are not sourced from web data.
- Open-Meteo failures do not crash the agent.

## 15. Evaluation Requirements

Agro-Mind includes both automated unit/regression tests and scripted evaluation
checks. Evaluation is separate from normal pytest coverage because it measures
routing, safety, and end-to-end agent behavior against golden support cases.

### 15.1 Evaluation Files

| File | Purpose |
| --- | --- |
| `evaluation/golden_cases.jsonl` | Golden user messages with expected intents and optional expected response constraints. |
| `evaluation/check_intent.py` | Fast deterministic intent-classifier evaluation using golden cases with `expected_intent`. |
| `evaluation/check_safety.py` | Focused safety-risk detector evaluation with positive and negative safety examples. |
| `evaluation/run_eval.py` | End-to-end async agent evaluation over the golden cases. |

### 15.2 Evaluation Commands

Developers must be able to run:

```bash
python -m evaluation.check_intent
python -m evaluation.check_safety
python -m evaluation.run_eval
```

`python -m evaluation.run_eval` may require a configured model API key because
it instantiates `AgroMindAgent` and can call LLM-backed nodes.

### 15.3 Golden Case Schema

Each line in `evaluation/golden_cases.jsonl` must be one JSON object. Supported
fields include:

- `id`: stable unique case ID.
- `category`: optional case group.
- `message`: user message.
- `expected_intent`: expected normalized intent.
- `expected_escalate`: optional expected `escalate_human` boolean.
- `expected_escalation_type`: optional future escalation type expectation.
- `expected_priority`: optional future priority expectation.
- `expected_safety_type`: optional safety type expectation when response
  includes that field.
- `must_contain`: phrases that must appear in response text.
- `must_contain_any`: at least one phrase must appear in response text.
- `must_not_contain`: phrases that must not appear in response text.

### 15.4 Evaluation Acceptance Criteria

- Intent evaluation must report pass/fail per case and a final intent score.
- Safety detector evaluation must include both risky and safe examples.
- Full agent evaluation must report:
  - final score
  - category-level pass counts
  - pass/fail per case
  - failure reasons
  - response excerpt for failed cases
- Golden case IDs must remain stable so regressions are traceable over time.
- Any change to routing, safety, product recommendation, logistics, or response
  contract should update or add golden cases.
- Safety evaluation failures should block release until reviewed.
- Intent or end-to-end failures should be triaged before release; acceptable
  failures must be documented with the reason.

## 16. Metrics for Production Hardening

- safety recall on high-risk messages
- false-positive safety escalation rate
- intent classification accuracy
- product recommendation groundedness
- retrieval hit rate
- first-token latency
- full-response latency
- chat error rate
- cart add success rate
- checkout completion rate
- order-status resolution rate
- treatment task completion rate
- escalation volume and time to human resolution

## 17. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Hallucinated product details | Unsafe or incorrect buying guidance | Render product details from catalog records, not prose |
| Missed poisoning/self-harm signal | User safety risk | Keep pre-LLM interceptor and expand regression cases |
| False safety escalation | Poor UX and support load | Maintain safe negative examples in tests |
| Missing Chroma index | Weak retrieval | Fall back to catalog keyword search and document ingestion |
| Catalog file schema change | Parser breakage | Keep catalog tests and validate expected columns |
| Database schema drift | Runtime errors | Use lightweight migration now; move to Alembic before production |
| Session ID misuse | Data leakage | Add real authentication and authorization before production |
| Uploaded image retention ambiguity | Privacy/compliance risk | Define retention and deletion policy |
| Slow remote DB/model calls | Poor field usability | Cache profile reads, stream responses, keep routing deterministic |
| External weather API failure | Missing local timing context | Continue without web context or ask for clearer location |
| Web data used for product facts | Unsafe hallucinated guidance | Restrict web context to weather/timing and keep product facts catalog-grounded |
| Overconfident diagnosis | Bad agricultural action | Require uncertainty and one follow-up when evidence is limited |

## 18. Roadmap

### Phase 1: Prototype Stabilization

- Keep PRD and README aligned with actual endpoints.
- Ensure all current tests pass locally.
- Add tests for `/profile`, `/history`, `/tasks/done`, and `/followups/due`.
- Align `/health` model defaults with `agent/llm.py`.
- Confirm Streamlit streaming behavior against `/chat_stream`.

### Phase 2: Product Quality

- Add stronger cart, checkout, order, and treatment regression tests.
- Add structured safety categories to API responses.
- Add retrieval confidence indicators.
- Add explicit image-retention controls.
- Improve session sign-in so frontend identity maps to backend customer identity.
- Add staff-facing escalation review workflow.

### Phase 3: Production Readiness

- Add real authentication and authorization.
- Replace lightweight schema changes with migrations.
- Add observability for latency, errors, model calls, retrieval, and safety.
- Add deployment profiles for local, staging, and production.
- Define compliance copy and pesticide-use disclaimers for target markets.
- Integrate real commerce, payment, shipping, and order APIs if required.

## 19. Important Functions Reference

This section maps the most important code entry points to their product
responsibilities. It is intended for developers implementing, debugging, or
extending Agro-Mind.

### 19.1 FastAPI Backend: `main.py`

| Function / Class | Responsibility |
| --- | --- |
| `get_agent()` | Lazily creates and returns the singleton `AgroMindAgent`. |
| `lifespan(app)` | Startup/shutdown hook; initializes DB, seeds products, and warms the agent. |
| `ChatRequest` | Pydantic request contract for `/chat` and `/chat_stream`. |
| `ChatResponse` | Pydantic response contract returned by final agent responses. |
| `health()` | Reports service status, API key presence, model names, and backend provider. |
| `get_catalog()` | Returns the full parsed catalog. |
| `get_catalog_preview(limit)` | Returns a clamped lightweight product preview for the UI. |
| `chat(request)` | Decodes optional image input, runs the agent, and returns structured JSON. |
| `chat_stream(request)` | Decodes optional image input and returns NDJSON streaming events. |
| `profile(session_id)` | Reads the DB-backed customer profile for the session/customer. |
| `update_profile_api(request)` | Updates editable customer profile fields. |
| `history(session_id, limit)` | Returns recent DB-backed message history. |
| `view_cart(session_id)` | Returns or creates the active cart. |
| `cart_add(request)` | Adds/increments a product in the active cart. |
| `cart_clear(request)` | Clears the active cart and returns a fresh empty cart. |
| `checkout(request)` | Converts cart items into DB-backed orders. |
| `orders(session_id)` | Lists customer-scoped orders. |
| `get_single_order(order_id, session_id)` | Returns one customer-scoped order or 404. |
| `get_treatments(session_id)` | Returns active treatment plans. |
| `todays_tasks(session_id)` | Returns incomplete treatment tasks due today. |
| `due_followups(session_id)` | Returns due follow-up/task data scoped to the caller. |
| `mark_task_done(request)` | Toggles one treatment task done/undone. |

### 19.2 Agent Orchestration: `agent/orchestrator.py`

| Function / Class | Responsibility |
| --- | --- |
| `AgentResponse` | Normalized final response object used by FastAPI. |
| `AgentState` | LangGraph state schema for routing, text, image, safety, and product data. |
| `_session_memory(session_id)` | Creates DB-backed memory or a no-op fallback. |
| `_recent_chat_history(session_id, current_message, limit)` | Reads recent turns for context-sensitive routing. |
| `_contextualize_short_sales_reply(session_id, message)` | Expands short Arabic weed-type replies using prior context. |
| `_llm_content(llm, prompt)` | Calls async LLMs with sync fallback for tests/mocks. |
| `_extract_order_id(message)` | Extracts PDD order IDs from user text. |
| `_is_usage_question(message)` | Detects dosage, dilution, and usage questions. |
| `_find_catalog_product_in_text(message)` | Resolves a product ID/name mentioned in text. |
| `_resolve_usage_product(state)` | Resolves product usage context from order ID or product mention. |
| `_format_product_usage(product)` | Formats catalog-grounded usage guidance. |
| `safety_check_node(state)` | First graph node; blocks unsafe messages before normal routing. |
| `intent_node(state)` | Routes image, init-session, contextual replies, and keyword intent. |
| `diagnosis_node(state)` | Handles text/image crop diagnosis and product recommendation. |
| `logistics_node(state)` | Answers shipping/order questions from verified DB order data. |
| `product_node(state)` | Handles product recommendation and product-usage questions. |
| `general_node(state)` | Handles greetings, memory-aware QA, and optional weather context. |
| `_extract_treatment_json(raw)` | Parses strict or fenced JSON from treatment extraction output. |
| `_save_treatment_in_background(session_id, response_text, user_message)` | Extracts and saves treatment records without blocking the user response. |
| `memory_node(state)` | Persists last intent/recommendation and marks diagnosis context in memory. |
| `route_after_safety(state)` | Sends unsafe messages directly to memory/finalization. |
| `route_intent(state)` | Routes intent to diagnosis, logistics, product, or general nodes. |
| `AgroMindAgent.run(...)` | Non-streaming agent execution; persists turns and attaches product cards. |
| `AgroMindAgent.stream(...)` | Streaming agent execution; emits token events and final metadata. |

### 19.3 Agent Tools: `agent/tools.py`

| Function | Responsibility |
| --- | --- |
| `_get_context_string_no_init(session_id)` | Reads customer context without creating session rows, avoiding race conditions. |
| `_mentions_catalog_product(message)` | Checks whether text directly mentions a known product ID/name. |
| `_local_catalog_recommendation(diagnosis, crop)` | Fallback product recommendation when Chroma is unavailable. |
| `classify_intent(message)` | Keyword classifier for diagnosis, product, logistics, and general messages. |
| `analyze_crop_image(image_base64)` | Sends crop image to the vision model and returns analysis text. |
| `retrieve_agronomy_knowledge(query)` | Queries Chroma for catalog/agronomy context. |
| `recommend_product(diagnosis, crop)` | Recommends catalog products using retrieval plus LLM verification. |
| `check_product_safety(product_id)` | Retrieves safety/usage constraints for one product. |
| `_chemical_exposure_risk(message)` | Detects direct chemical exposure terms. |
| `detect_escalation_risk(message)` | Combines chemical exposure checks with `SafetyInterceptor`. |
| `create_human_alert(session_id, message, risk_category)` | Creates DB escalation and returns safe customer-facing text. |
| `update_customer_profile(session_id, data)` | Writes profile/memory updates through `CustomerMemory`. |
| `get_customer_profile(session_id)` | Returns DB-backed profile with short TTL caching. |
| `invalidate_profile_cache(session_id)` | Clears cached profile data after updates. |

### 19.4 Database State: `db/customer_state.py`

| Function | Responsibility |
| --- | --- |
| `_validate_group_buy_quantity(quantity)` | Enforces group-buy minimum quantity. |
| `_ensure_customer(session_id, external_id)` | Ensures customer/session rows exist and returns customer ID. |
| `_active_cart(db, customer_id, session_id)` | Returns or creates the active cart. |
| `_cart_to_dict(cart)` | Converts cart ORM records into API/UI payload shape. |
| `_order_to_dict(order)` | Converts order ORM records into API/UI payload shape. |
| `get_cart(session_id, external_id)` | Returns active cart with products and totals. |
| `list_orders(session_id, external_id)` | Lists orders for the current customer. |
| `get_order(session_id, external_id, order_id)` | Returns one order only if owned by the current customer. |
| `get_order_context(session_id, external_id, order_id)` | Builds prompt-safe verified logistics context. |
| `checkout_cart(session_id, external_id)` | Converts active cart items into shipped demo orders. |
| `get_profile(session_id, external_id)` | Reads editable customer profile fields. |
| `get_chat_history(session_id, external_id, limit, include_images)` | Reads recent messages across customer sessions. |
| `get_all_customer_histories(...)` | Exports grouped history for all customers. |
| `update_profile(session_id, external_id, ...)` | Persists user-editable profile fields. |
| `list_customers(limit)` | Lists recent local-demo customers. |
| `login_customer(username, password, session_id)` | Demo login/customer resolver. |
| `add_cart_item(...)` | Adds or increments a cart item and prices it. |
| `clear_cart(session_id, external_id)` | Marks active cart cleared and creates a new active cart. |
| `create_diagnosis(...)` | Persists structured crop issue records. |
| `_treatment_to_dict(treatment)` | Converts treatment ORM record into API payload. |
| `_generate_daily_tasks(...)` | Generates dated treatment tasks from duration metadata. |
| `add_treatment(...)` | Saves an active treatment and generated tasks. |
| `mark_task_done(session_id, external_id, treatment_id, day)` | Toggles a treatment task and completes treatment if all tasks are done. |
| `get_active_treatments(session_id, external_id)` | Returns active treatments for the customer. |
| `get_todays_tasks(session_id, external_id)` | Returns incomplete treatment tasks due today. |
| `create_escalation(...)` | Persists a safety escalation ticket. |

### 19.5 Database Engine, Models, and Seeding

| File / Function | Responsibility |
| --- | --- |
| `db/models.py` ORM classes | Define persistent tables for customers, sessions, messages, products, diagnoses, carts, cart items, orders, refunds, escalations, follow-ups, and treatments. |
| `db.engine.get_session()` | Returns a SQLAlchemy session factory instance. |
| `db.engine.init_db()` | Creates tables and applies lightweight prototype schema additions. |
| `db.engine._migrate_existing_schema()` | Adds known missing columns to existing demo schemas. |
| `db.engine._safe_url()` | Masks database credentials for logs. |
| `db.seed.seed_products()` | Seeds catalog products into the relational `products` table. |

### 19.6 Customer Memory: `memory/customer_memory.py`

| Function / Method | Responsibility |
| --- | --- |
| `CustomerMemory.__init__(session_id, external_id)` | Initializes session/customer memory context. |
| `CustomerMemory._ensure_session()` | Creates or attaches customer/session rows. |
| `CustomerMemory._customer_session_ids(db)` | Returns all sessions for one customer. |
| `CustomerMemory.update(...)` | Updates crop, location, last product, last intent, and diagnosis marker. |
| `CustomerMemory.get_context_string()` | Builds compact LLM memory context. |
| `CustomerMemory.chat_history()` | Returns stored turns for the current session. |
| `CustomerMemory.append_turn(...)` | Persists user/assistant messages and optional image attachments. |
| `CustomerMemory.load()` | Returns a compact customer profile snapshot. |

### 19.7 Catalog and Retrieval

| Function / Class | Responsibility |
| --- | --- |
| `ProductRecord` | Dataclass for parsed catalog products. |
| `ProductRecord.to_dict()` | Converts a catalog product to API/UI dictionary format. |
| `ProductRecord.price_display()` | Formats group and single prices. |
| `ProductRecord.summary()` | Builds a compact product summary string. |
| `rag.catalog_loader._load_catalog()` | Parses the translated XLSX catalog. |
| `get_catalog()` | Returns the module-level loaded catalog. |
| `search_catalog(query, crop, max_results)` | Keyword-searches product fields with optional crop filter. |
| `get_product_by_id(product_id)` | Case-insensitive product lookup. |
| `all_products_summary()` | Builds a compact catalog listing for prompt/debug use. |
| `rag.ingest.ingest_catalog()` | Creates Chroma documents from products, crop recommendations, and advisory samples. |

### 19.8 LLM and Web Context

| Function | Responsibility |
| --- | --- |
| `agent.llm._api_key()` | Reads `QWEN_API_KEY` or `DASHSCOPE_API_KEY`. |
| `agent.llm._base_url()` | Reads `QWEN_BASE_URL` or DashScope default. |
| `get_chat_llm(temperature, model)` | Creates streaming Qwen text chat client. |
| `get_vision_llm(temperature)` | Creates streaming Qwen vision chat client. |
| `get_embeddings()` | Creates Qwen embedding client for Chroma. |
| `asks_for_web_context(message)` | Detects weather/local-timing questions. |
| `extract_location_hint(message)` | Extracts location hint from user text. |
| `get_weather_context(location)` | Fetches local weather context. |
| `format_web_context_for_prompt(context)` | Formats weather data for prompt use. |

### 19.9 Safety: `safety/interceptor.py`

| Function / Class | Responsibility |
| --- | --- |
| `SafetyResult` | Structured safety result with category, phrase, summary, and escalation flag. |
| `SafetyInterceptor.check(text)` | Scans text before any LLM call for self-harm, ingestion, poisoning, and dangerous chemical combinations. |
| `SafetyInterceptor._build_result(category, phrase, original_text)` | Creates the unsafe result and human summary. |

### 19.10 Frontend: `frontend/app.py`

| Function | Responsibility |
| --- | --- |
| `_intent_badge(intent)` | Maps response intent to visible UI badge. |
| `_render_uploaded_image(...)` | Renders a sent image inside the user bubble. |
| `_render_composer_upload_preview(...)` | Renders image preview before message send. |
| `_render_product_card(product)` | Renders catalog-backed product card. |
| `_send_message(message, image_bytes, order_id)` | Non-streaming `/chat` fallback call. |
| `_connection_error_response()` | Builds offline-backend fallback response. |
| `_error_response(msg)` | Builds generic frontend error response. |
| `_fetch_backend_ok(api_url)` | Checks API health. |
| `_fetch_cart(api_url, session_id)` | Reads cart state with short cache. |
| `_fetch_history(api_url, session_id)` | Reads recent chat history. |
| `_fetch_treatments(api_url, session_id)` | Reads active treatments. |
| `_fetch_catalog_preview(api_url, limit)` | Reads catalog preview. |
| `_fetch_profile(api_url, session_id)` | Reads profile state. |
| `_update_profile(...)` | Persists profile edits through API. |
| `_clear_session_caches()` | Clears cached cart/treatment/profile data after session changes. |
| `_stream_turn(pending)` | Calls `/chat_stream`, renders token events, and returns final metadata. |
| `_process_turn(...)` | Queues a user turn and stores its local UI state. |
| `_cart_add(product_id, quantity, is_group_buy)` | Adds product to cart via API and handles group-buy errors. |
| `_get_treatments()` | Wrapper around treatment fetch for current session. |
| `_mark_task_done(treatment_id, day)` | Toggles treatment task via API. |
| `_get_cart()` | Wrapper around cart fetch for current session. |
| `_checkout()` | Converts cart to orders through API. |
| `_check_backend()` | Wrapper around backend health check. |

### 19.11 Support Tools: `tools/agriculture_tools.py`

| Function | Responsibility |
| --- | --- |
| `track_order(order_id)` | Mock/demo order tracking helper. |
| `initiate_refund(order_id, reason)` | Mock/demo refund initiation helper. |
| `request_invoice(order_id, amount)` | Mock/demo invoice helper. |
| `search_products(query, crop, max_results)` | Product search helper backed by catalog search. |
| `get_product(product_id)` | Product lookup helper. |
| `get_weather_forecast(location)` | Simple weather forecast helper. |
| `analyze_soil(ph_level, moisture)` | Simple soil guidance helper. |

### 19.12 Evaluation: `evaluation/`

| Function / File | Responsibility |
| --- | --- |
| `evaluation.golden_cases.jsonl` | Source of stable evaluation scenarios. |
| `check_intent.load_cases(path)` | Loads golden cases for intent checks. |
| `check_intent.normalize_intent(intent)` | Normalizes classifier output to expected labels. |
| `check_intent.main()` | Runs intent scoring and prints pass/fail details. |
| `check_safety.CASES` | Focused safety detector examples. |
| `check_safety.main()` | Runs safety detector scoring. |
| `run_eval.load_cases(path)` | Loads full agent evaluation cases. |
| `run_eval.normalize_intent(intent)` | Normalizes final agent intent labels. |
| `run_eval.contains_any(text, phrases)` | Checks response text against allowed phrase alternatives. |
| `run_eval.check_case(case, result)` | Compares one final agent result against expected case constraints. |
| `run_eval.run_case(agent, case)` | Executes one golden case through `AgroMindAgent.run()`. |
| `run_eval.main()` | Runs full async evaluation and prints final/category scores. |

## 20. Open Questions

- What is the authoritative production catalog source and update cadence?
- What human-support system should receive escalation tickets?
- How long should uploaded crop images and chat messages be retained?
- Which production locales and languages are required?
- What pesticide/regulatory disclaimers are required by target market?
- Should checkout remain simulated or integrate with a real Pinduoduo order
  platform?
- Should group-buy minimum quantity always be 10 or vary by product?
- Should treatment task creation be explicit user-confirmed state instead of
  background extraction from model output?
- What profile identity should connect mobile users across sessions in
  production?
