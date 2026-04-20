# OpenRAG — Claude Code Project Instructions

## Stack
- **Backend**: FastAPI + OpenSearch, Python (`src/`)
- **Frontend**: Next.js / TypeScript (`frontend/`)
- **Logging**: `structlog` — structured JSON in production, pretty console in development

---

## Logging Standards (MANDATORY)

> Read this before writing any backend log statement. These rules are non-negotiable.
> Full reference: `/logging-standards` slash command or `.agents/skills/logging-standards/README.md`

### Logger initialisation
Every Python module that logs must declare its logger as the first non-import statement:

```python
from utils.logging_config import get_logger
logger = get_logger(__name__)
```

Never use `import logging; logging.getLogger(...)` directly anywhere in `src/`.

---

### Subsystem tags — always prefix the event string

| Tag | Use for |
|-----|---------|
| `[API]` | HTTP middleware, request/response |
| `[AUTH]` | Authentication, session, JWT, OAuth |
| `[CHAT]` | Chat service, LLM calls |
| `[LF]` | Langflow service calls |
| `[SEARCH]` | Search service queries |
| `[INGEST]` | Document ingestion pipeline |
| `[CONNECTOR]` | Connector sync, OAuth, webhooks |
| `[CONFIG]` | Config manager, settings changes |
| `[OPENSEARCH]` | OpenSearch operations |
| `[AGENT]` | `src/agent.py` operations |

```python
# CORRECT
logger.info("[INGEST] Run started", flow_id=self.flow_id_ingest, filename=filename)
logger.warning("[CONNECTOR] Sync failed", connector_id=connector_id, error=str(e))

# WRONG — no tag, f-string interpolation, not structured
logger.info(f"Starting ingestion for {filename}")
```

---

### Log levels

| Level | When to use |
|-------|-------------|
| `DEBUG` | Developer diagnostics; hidden in production by default |
| `INFO` | Normal operational events (service started, request completed, file indexed) |
| `WARNING` | Degraded but recoverable (retry, fallback, missing optional config) |
| `ERROR` | Failure that affects a user request |
| `CRITICAL` | System-wide failure or imminent shutdown |

```python
# CORRECT level usage
logger.info("[CONNECTOR] Sync complete", connector_id=id, documents=n)
logger.warning("[LF] Langflow API key regenerated due to auth failure")
logger.error("[SEARCH] OpenSearch query failed", index=index, error=str(e))

# WRONG — using info for a failure condition
logger.info("Error listing connectors", error=str(e))  # should be logger.error
```

---

### Structured fields — keyword args, never f-strings

```python
# CORRECT — structured, queryable in any log aggregator
logger.info("[SEARCH] Query complete", hits=len(results), duration_ms=duration)
logger.error("[AUTH] Token validation failed", user_id=user_id, error=str(e))

# WRONG — f-string; unqueryable, leaks data
logger.info(f"[SEARCH] Query returned {len(results)} hits in {duration}ms")
```

---

### Exception handling — `logger.exception()`, never `traceback.print_exc()`

```python
# CORRECT — stack trace captured through structlog pipeline, structured and filterable
try:
    ...
except Exception as e:
    logger.exception("[CONNECTOR] Sync failed", connector_id=connector_id)
    raise

# WRONG — bypasses structlog entirely, dumps raw text to stderr
except Exception as e:
    logger.error(f"Sync failed: {e}")
    import traceback
    traceback.print_exc()
```

---

### Security — NEVER log credentials

The following must **never** appear in log output:

- API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `WATSONX_APIKEY`, `IBM_COS_API_KEY`, …)
- Passwords (`OPENSEARCH_PASSWORD`, database connection strings)
- Tokens (JWT, bearer, access tokens, refresh tokens, client secrets)
- Full HTTP header dicts (they contain the above via Langflow global vars)

```python
# CORRECT — log safe metadata only
logger.info("[INGEST] Run started", flow_id=self.flow_id_ingest, filename=filename)

# WRONG — headers dict contains every API key in the system
logger.info(f"[LF] Headers {headers}")
```

If you must log any header dict, use `sanitize_headers()` from `utils.logging_config`:
```python
from utils.logging_config import sanitize_headers
logger.debug("[LF] Headers (sanitised)", headers=sanitize_headers(headers))
```

---

### `print()` is banned in production code

Replace every `print(...)` with the appropriate `logger.<level>(...)` call.  
The only exception is `if __name__ == "__main__":` blocks, which must be removed before merging.

---

## Key architectural files

| File | Purpose |
|------|---------|
| `src/utils/logging_config.py` | structlog config, `sanitize_headers()`, stdlib bridge, processor chain |
| `src/bootstrap.py` | Calls `configure_from_env()` before any module-level code runs |
| `src/main.py` | `RequestLoggingMiddleware` — correlation IDs, `X-Request-ID` response header |

### How the logging system works

1. `bootstrap.py` is the **first import** in `main.py`. It calls `configure_from_env()` immediately after `load_dotenv()`, so structlog is fully configured before any other module-level log fires.
2. `RequestLoggingMiddleware` (pure ASGI, not `BaseHTTPMiddleware`) binds a `request_id` to structlog's contextvars. Every log line emitted during that request automatically carries `request_id=` — no manual threading needed.
3. The stdlib bridge in `configure_stdlib_logging()` routes uvicorn, httpx, opensearch-py, and MCP server logs through the same pipeline. Third-party libraries are capped at `ERROR` level.
4. `LOG_FORMAT=json` switches output to newline-delimited JSON (for ELK/Datadog/Splunk). Default is the pretty console format for local development.

---

## Connector pattern

To add a new connector: create `src/connectors/<name>/` with `auth.py`, `connector.py`, `__init__.py`. See memory file for the full 8-step checklist.

---

## Workflow preferences

- **Never commit directly** to any branch without explicit user request. Stage changes and wait.
