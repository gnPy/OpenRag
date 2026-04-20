# Logging Standards — OpenRAG Backend

This skill defines the mandatory logging conventions for the OpenRAG Python backend.
All AI coding agents (Cursor, Windsurf, Claude Code, etc.) must follow these rules when
writing or reviewing backend code under `src/`.

Full reference: `.claude/commands/logging-standards.md`  
Auto-loaded rules: `CLAUDE.md` at repo root

---

## Quick reference

### Logger setup (every file)
```python
from utils.logging_config import get_logger
logger = get_logger(__name__)
```

### Tag every log event
```python
logger.info("[INGEST] Run started", flow_id=flow_id, filename=filename)
logger.warning("[CONNECTOR] Retry", attempt=n, error=str(e))
logger.exception("[AUTH] OAuth callback failed")  # in except block
```

### Tag → subsystem mapping
| Tag | Area |
|-----|------|
| `[API]` | HTTP middleware / request-response |
| `[AUTH]` | Authentication, OAuth, JWT |
| `[CHAT]` | Chat service |
| `[LF]` | Langflow calls |
| `[SEARCH]` | Search service |
| `[INGEST]` | Document ingestion |
| `[CONNECTOR]` | Connector sync / auth |
| `[CONFIG]` | Config manager / settings |
| `[OPENSEARCH]` | OpenSearch operations |
| `[AGENT]` | Agent execution |

---

## The five rules

### 1. Structured fields — keyword args, not f-strings
```python
logger.info("[SEARCH] Complete", hits=n, duration_ms=ms)   # CORRECT
logger.info(f"[SEARCH] Got {n} hits in {ms}ms")            # WRONG
```

### 2. Log levels
- `DEBUG` — diagnostics, hidden in prod
- `INFO` — normal operation
- `WARNING` — degraded but recoverable
- `ERROR` — request-affecting failure
- `CRITICAL` — system-wide failure

### 3. Exceptions — logger.exception(), not traceback.print_exc()
```python
except Exception:
    logger.exception("[CONNECTOR] Sync failed", connector_id=id)  # CORRECT
    raise
```

### 4. Never log credentials
API keys, passwords, tokens, JWT, full header dicts, and `config.to_dict()` are all banned from log output. Use `sanitize_headers()` from `utils.logging_config` if header inspection is needed.

### 5. No bare print() in production code

---

## Infrastructure files
| File | Role |
|------|------|
| `src/utils/logging_config.py` | structlog config, processor chain, `sanitize_headers()` |
| `src/bootstrap.py` | Calls `configure_from_env()` before any module-level code |
| `src/main.py` | `RequestLoggingMiddleware` — auto-binds `request_id` to all logs |

---

## Correlation IDs
`RequestLoggingMiddleware` (pure ASGI, not `BaseHTTPMiddleware`) generates a UUID per request and binds it to structlog contextvars. Every log line in that request automatically includes `request_id=` with no manual effort from application code.

## Output modes
- Default: pretty console with colours and `file:line` location
- `LOG_FORMAT=json`: newline-delimited JSON for log aggregators (ELK, Datadog, Splunk)
- `LOG_LEVEL=DEBUG`: enables debug output
