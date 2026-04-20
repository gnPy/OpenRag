---
name: logging-standards
description: OpenRAG backend logging standards and conventions. Use when writing any new log statement, reviewing existing logs, or adding logging to a new module. Enforces structlog usage, subsystem tags, correct log levels, structured fields, security rules, and exception handling patterns.
---

# Logging Standards

OpenRAG uses **structlog** for all backend logging. The pipeline is configured in `src/utils/logging_config.py` and initialised in `src/bootstrap.py`. Every log line automatically carries `request_id`, `service`, `env`, and `version` fields.

---

## 1. Logger initialisation

Every module that emits logs must declare its logger as the **first non-import line**:

```python
from utils.logging_config import get_logger
logger = get_logger(__name__)
```

**Never** use `import logging; logging.getLogger(...)` directly. It bypasses the structlog pipeline.

---

## 2. Subsystem tags

Every log event string must be prefixed with the subsystem tag. This makes logs filterable in any aggregator without schema knowledge.

| Tag | Module / area |
|-----|---------------|
| `[API]` | `RequestLoggingMiddleware`, HTTP request/response |
| `[AUTH]` | `src/api/auth.py`, `src/dependencies.py`, `src/services/auth_service.py` |
| `[CHAT]` | `src/services/chat_service.py` |
| `[LF]` | Langflow calls in `src/services/langflow_*.py`, `src/config/settings.py` |
| `[SEARCH]` | `src/services/search_service.py` |
| `[INGEST]` | `src/services/langflow_file_service.py`, `src/api/upload.py` |
| `[CONNECTOR]` | `src/connectors/`, `src/api/connectors.py` |
| `[CONFIG]` | `src/config/config_manager.py`, `src/api/settings.py` |
| `[OPENSEARCH]` | `src/utils/opensearch_utils.py`, `src/utils/acl_utils.py` |
| `[AGENT]` | `src/agent.py` |

```python
# CORRECT
logger.info("[CONNECTOR] Sync started", connector_id=conn_id, connector_type=ctype)
logger.warning("[LF] Langflow key regenerated due to auth failure")
logger.error("[OPENSEARCH] Index creation failed", index=index_name, error=str(e))

# WRONG
logger.info(f"Starting sync for {conn_id}")           # no tag, f-string
logger.info("Sync started", connector_id=conn_id)     # no tag
```

---

## 3. Log levels

| Level | Use when |
|-------|----------|
| `DEBUG` | Developer diagnostics only — hidden in prod by default (`LOG_LEVEL=INFO`) |
| `INFO` | Normal operational event: service started, request completed, document indexed |
| `WARNING` | Degraded but recoverable: retry, fallback, optional config missing, parameter substitution |
| `ERROR` | Failure that affects the current user request |
| `CRITICAL` | System-wide failure / imminent shutdown |

### Common misuses to avoid

```python
# info → warning (failure / degraded path)
logger.warning("[API] max_tokens failed, trying max_completion_tokens")   # CORRECT
logger.info("max_tokens parameter failed, trying max_completion_tokens")  # WRONG

# info → error (explicit error with exception detail)
logger.error("[CONNECTOR] Error listing connectors", error=str(e))  # CORRECT
logger.info("Error listing connectors", error=str(e))               # WRONG

# debug → warning (security / auth rejection is always warning+)
logger.warning("[SEARCH] user_id missing, rejecting search request")  # CORRECT
logger.debug("search_service: user_id is None/empty, returning auth error")  # WRONG

# debug → info (operational state should be visible in prod)
logger.info("[OPENSEARCH] Index already exists", index_name=index_name)  # CORRECT
logger.debug("OpenSearch index already exists", index_name=index_name)  # WRONG
```

---

## 4. Structured fields — keyword args, not f-strings

structlog renders keyword arguments as structured key=value pairs. They are queryable in ELK, Datadog, Splunk, and any other log aggregator. f-strings are not.

```python
# CORRECT — structured, filterable
logger.info("[SEARCH] Query complete", hits=len(results), duration_ms=ms, filters=bool(f))
logger.error("[AUTH] Token expired", user_id=user_id, expires_at=exp)
logger.warning("[CONNECTOR] Retry", attempt=attempt, max_retries=max_r, error=str(e))

# WRONG — f-string, unqueryable
logger.info(f"[SEARCH] Query returned {len(results)} hits in {ms}ms")
logger.error(f"Token expired for {user_id}, expires at {exp}")
```

---

## 5. Exception handling

Use `logger.exception()` inside `except` blocks. It automatically captures the current exception's stack trace through the structlog pipeline (as a structured `exception` dict in JSON mode, formatted text in console mode).

```python
# CORRECT
try:
    result = await do_something()
except SomeSpecificError:
    raise  # let it propagate without extra log noise
except Exception as e:
    logger.exception("[CONNECTOR] Sync failed", connector_id=connector_id)
    raise  # or return error response

# WRONG — bypasses structlog, dumps raw stack trace to stderr
except Exception as e:
    logger.error(f"Sync failed: {e}")
    import traceback
    traceback.print_exc()
```

**Remove `import traceback` and all `traceback.print_exc()` calls.** They have no place in production code.

---

## 6. Security — credentials must never appear in logs

### Banned from log output
- API keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `WATSONX_APIKEY`, `IBM_COS_API_KEY`, `AWS_SECRET_ACCESS_KEY`
- Passwords: `OPENSEARCH_PASSWORD`, database connection strings
- Tokens: JWT, bearer tokens, access tokens, refresh tokens, client secrets, HMAC keys
- Full header dicts (Langflow global-var headers contain all of the above)
- Full config objects (`.to_dict()` on config includes all provider credentials)

### What to log instead

```python
# WRONG — dumps every API key in the system
logger.info(f"[LF] Headers {headers}")
logger.debug("Configuration loaded", config=self._config.to_dict())

# CORRECT — log only safe metadata
logger.info("[INGEST] Run started", flow_id=self.flow_id_ingest, filename=filename)
logger.debug("[CONFIG] Configuration loaded successfully")
```

### sanitize_headers() for header inspection

If you genuinely need to inspect headers for debugging, use the provided utility:

```python
from utils.logging_config import sanitize_headers
logger.debug("[LF] Headers (sanitised)", headers=sanitize_headers(headers))
# Output: {"X-LANGFLOW-GLOBAL-VAR-OPENAI-API-KEY": "***", "X-LANGFLOW-GLOBAL-VAR-JWT": "***", ...}
```

---

## 7. print() is banned

```python
# WRONG
print(f"Error checking ACL for {document_id}: {e}")
print(connector.authenticate())

# CORRECT
logger.error("[OPENSEARCH] ACL check failed", document_id=document_id, error=str(e))
# (debug __main__ blocks should be removed before merging)
```

---

## 8. Operational touchpoints — log lifecycle events

Every major operation should have a start and complete/fail log at `INFO` level:

```python
# Connector sync
logger.info("[CONNECTOR] Sync started", connector_id=id, connector_type=ctype)
logger.info("[CONNECTOR] Sync complete", connector_id=id, documents_processed=n, duration_ms=ms)
logger.exception("[CONNECTOR] Sync failed", connector_id=id)  # in except block

# Document ingestion
logger.info("[INGEST] Run started", flow_id=flow_id, filename=filename, mimetype=mime)
logger.info("[INGEST] Run complete", status_code=resp.status_code, duration_ms=ms)

# Search
logger.info("[SEARCH] Query started", embedding_model=model, query_preview=query[:50])
logger.info("[SEARCH] Query complete", hits=len(results), duration_ms=ms, filters_applied=bool(f))

# Chat
logger.info("[CHAT] Session request", session_id=session_id, stream=stream)
logger.info("[CHAT] Session complete", session_id=session_id, duration_ms=ms)
```

---

## 9. How correlation IDs work

`RequestLoggingMiddleware` in `src/main.py` is a **pure ASGI middleware** (not `BaseHTTPMiddleware`). On each HTTP request it:

1. Reads `X-Request-ID` from incoming headers or generates a UUID
2. Binds `request_id`, `method`, `path` to structlog's contextvars
3. Every `logger.*()` call during that request automatically inherits those fields — no threading, no manual passing
4. Injects `X-Request-ID` into the response headers

This means every log line for a given request is correlated without any extra work from application code.

```
[INFO] [chat.py:127] [CHAT] Langflow request failed   request_id=abc-123 method=POST path=/api/chat
[INFO] [agent.py:264] [AGENT] Streaming failed         request_id=abc-123 method=POST path=/api/chat
```

> **Important**: Always use pure ASGI middleware for anything that binds structlog contextvars. `BaseHTTPMiddleware` / `@app.middleware("http")` runs the endpoint in a task group that copies the context, so `bind_contextvars()` calls in endpoint handlers won't propagate back.

---

## 10. Production vs development output

| Env var | Output |
|---------|--------|
| `LOG_FORMAT=json` (production) | Newline-delimited JSON with `dict_tracebacks` for structured exceptions |
| (default) | Pretty console format with colours, file:line location |
| `LOG_LEVEL=DEBUG` | Enables debug-level output |

In JSON mode every log line is a complete JSON object:
```json
{"event": "[INGEST] Run started", "service": "openrag", "env": "production", "version": "0.3.2",
 "level": "info", "timestamp": "2026-04-20T22:30:38Z", "request_id": "abc-123",
 "flow_id": "...", "filename": "report.pdf"}
```

Third-party library logs (opensearch-py, httpx, boto3, uvicorn) are suppressed below `ERROR` level via the stdlib bridge in `configure_stdlib_logging()`. Python `UserWarning` / `DeprecationWarning` noise is silenced via `py.warnings: CRITICAL`.
