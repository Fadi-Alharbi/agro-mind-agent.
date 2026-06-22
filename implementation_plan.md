# Implementation Plan: Real-time Streaming for Immediate Responses

The agent currently waits until the entire response is fully generated before sending it to the UI, which can take several seconds and make it feel slow. To make the agent reply immediately ("بشكل فوري و سريع"), we will implement **real-time streaming** (like ChatGPT) so words appear on the screen as they are being generated.

## User Review Required

> [!IMPORTANT]
> Implementing streaming requires changes to both the FastAPI backend and the Streamlit frontend. The backend will use Server-Sent Events (SSE) / JSON-lines, and the frontend will use `st.write_stream` to display tokens instantly. Please approve this architectural change.

## Proposed Changes

### 1. Update LangGraph Nodes to Async (`agent/orchestrator.py`)
- Convert all graph nodes (`general_node`, `diagnosis_node`, etc.) to `async def`.
- Replace synchronous `.invoke()` calls with `.ainvoke()` for all LLM calls.
- Add `streaming=True` to the LLM definitions in `agent/llm.py`.

### 2. New Streaming Endpoint (`main.py`)
- Add a new endpoint `POST /chat_stream` that returns a `StreamingResponse`.
- Use LangGraph's `.astream_events(version="v2")` to capture tokens emitted by the LLM in real-time.
- Yield JSON-lines containing the tokens: `{"type": "token", "content": "hello"}`.
- Once the graph finishes execution, yield the final state metadata (intent, recommended products, safety flags): `{"type": "metadata", "data": {...}}`.

### 3. Update Streamlit UI (`frontend/app.py`)
- Modify `_send_message` to handle the new streaming endpoint using `requests.post(..., stream=True)`.
- Use an interactive chat container with `st.write_stream()` so the user sees the text typed out instantly instead of a static "Analyzing..." spinner.
- Parse the final metadata line to trigger the product cards and intent badges once the text generation completes.

## Verification Plan
### Automated Tests
- No new automated tests are required. Existing logic remains the same, only the delivery mechanism changes.

### Manual Verification
- Send a message (e.g. "hi" or "my tomato has spots") and verify that the text streams immediately into the chat bubble.
- Verify that product cards and safety banners still appear correctly after the text finishes streaming.
