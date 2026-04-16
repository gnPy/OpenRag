# OpenRAG Scalable Ingestion Architecture

## Background

Performance benchmarks on GKE (53 nodes: n2-std-32 + e2-std-8) with arXiv scientific PDFs showed a hard ceiling of **~2 files/second (0.60 MB/s)** regardless of how many Langflow workers were added. This document analyzes why, and defines a path to 10–40 f/s.

---

## Benchmark Summary

| LF Workers | LF CPU | Queue Depth | OR BE Workers | Result |
|---|---|---|---|---|
| 1 | 7.25 | 2 | 100 | 0.07 f/s |
| 7 | 7.25 | 50 | 100 | 0.73 f/s |
| 48 | 7.25 | 100 | 100 | LF deadlock |
| 48 | 26 | 80 | 80 | 1.66 f/s |
| 72 | 26 | 80 | 80 | 1.86 f/s |
| **96** | **26** | **160** | **160** | **1.99 f/s** ← plateau |
| 8 | 7.25 | 100 | 100 | LF Queue Pool error |

Adding more Langflow workers beyond 72 yields zero improvement. The system hit a hard ceiling imposed by Langflow's internal scheduler, not by Docling or OpenSearch.

---

## Root Cause Analysis

### 1. Langflow is the Bottleneck

Langflow plateaus at ~2 f/s due to its internal task queue mechanics. At high concurrency it exhibits:
- **Queue pool saturation** (`LF Queue Pool error`) at ≥100 workers + 100 queue depth
- **Internal deadlocks** at 48 workers + 100 queue depth
- **No throughput gain** from 72 → 96 workers (both 1.86 f/s at 80 queue depth)

Langflow was not designed as a high-throughput batch processing engine. It is an orchestration UI layer with significant per-task overhead (flow serialization, Postgres task state, internal scheduler).

### 2. OpenRAG BE Cannot Scale Horizontally

The backend is a **single uvicorn worker** with an `asyncio.Semaphore(4)` (default) capping concurrent file processing. All task state lives in-process memory — there is no cross-pod coordination.

**Code reference:** `src/services/task_service.py:44`

### 3. Serial OpenSearch Indexing

Each text chunk is indexed in a separate round-trip:
```python
# Current: processors.py:294–346
for i, (chunk, vect) in enumerate(...):
    await opensearch_client.index(index=..., id=chunk_id, body=chunk_doc)
```
For a 200-chunk document, this is 200 sequential HTTP calls to OpenSearch. At 5 ms/call, that's 1 second of indexing overhead alone per document.

### 4. Docling HTTP Client Pool Too Small

The `docling_http_client` in `src/config/settings.py` uses default `httpx` limits (5 max keepalive connections). With 48 Docling replicas deployed, only 5 concurrent connections can be maintained — serializing requests across asyncio tasks and leaving most Docling capacity unused.

### 5. OpenSearch and Docling Are NOT the Bottleneck

- **OpenSearch** handled the ingestion rate reliably across all test configurations. No errors.
- **Docling** scaled horizontally (HPA to 60 replicas) and reduced latency proportionally. The bottleneck is the pipeline upstream of Docling, not Docling itself.

---

## Current Architecture

```
Client
  │
  ▼
OpenRAG BE (1 pod, 1 uvicorn worker)
  │   asyncio.Semaphore(4) limits concurrency
  │   In-memory task state; cannot scale horizontally
  │
  ▼  HTTP — every file, sequentially through Langflow
Langflow (1 pod, up to 96 workers)   ← HARD BOTTLENECK (~2 f/s ceiling)
  │   Internal scheduler serialization
  │   Queue pool saturation at high concurrency
  │   Deadlocks at ≥48 workers + deep queue
  │
  ▼
Docling (48–60 replicas, HPA)         ← Horizontally scalable, not the bottleneck
  │
  ▼
OpenSearch (3-node cluster)           ← Handles load; serial indexing wastes latency
```

**Cost breakdown (current ~$15K/month):**
- Docling: ~$11.25K/month (75%)
- Langflow: ~$1.5K/month (10%)
- OpenSearch + misc: ~$2.25K/month (15%)

---

## Target Architecture

```
                  ┌────────────────────────────────────────────────┐
                  │                GKE Cluster                     │
                  │                                                │
Client ───────────┼──▶  OpenRAG API Pods (2–4 replicas)           │
                  │     - FastAPI; accepts uploads + sync triggers  │
                  │     - Enqueues job descriptors to Valkey       │
                  │     - Proxies task status from Valkey          │
                  │     - RollingUpdate; no write-PVC dependency   │
                  │     - HPA: CPU > 60% → scale 2–4              │
                  │                   │                            │
                  │                LPUSH                           │
                  │                   ▼                            │
                  │     Valkey (already deployed in cluster)       │
                  │     - ingest:queue  (LIST — job queue)         │
                  │     - task:{id}     (HASH — task counters)     │
                  │     - file:{id}     (HASH — per-file status)   │
                  │     - lock:dedup:{hash}  (NX EX — dedup lock) │
                  │     - 24h TTL on completed task state          │
                  │                   │                            │
                  │                BRPOP                           │
                  │                   ▼                            │
                  │     Ingestion Worker Pods (4–12 replicas)      │
                  │     - No HTTP port; pure asyncio process       │
                  │     - 8 asyncio tasks per pod (MAX_WORKERS=8)  │
                  │     - DISABLE_INGEST_WITH_LANGFLOW=true        │
                  │     - Stateless; no PVC mount needed           │
                  │     - KEDA ScaledObject: queue depth > 20      │
                  │              ↙             ↘                    │
                  │   Docling Pods        OpenSearch (3+ nodes)    │
                  │   (48–60 via HPA)     Bulk API: 100 chunks/req │
                  │   K8s ClusterIP svc   refresh_interval: 5s    │
                  │   (round-robin LB)                             │
                  │                                                │
                  │   Langflow — chat flows ONLY                   │
                  │   Scale down: 96 → 16 workers                  │
                  │   Completely removed from ingestion hot path   │
                  └────────────────────────────────────────────────┘
```

### Why Valkey?

Valkey is already deployed in the cluster. It is Redis-compatible, and the required pattern (LPUSH + BRPOP) needs only the `redis>=5.0.0` Python package — no Celery broker abstraction, no schema migrations, sub-millisecond dispatch latency. The existing Valkey instance can be reused as-is.

---

## Phased Implementation

### Phase 1 — No New Infrastructure (Target: 8–10 f/s)

Three config/code changes, deployable immediately.

#### 1a. Disable Langflow for ingestion

Set in the OpenRAG BE Deployment:
```yaml
- name: DISABLE_INGEST_WITH_LANGFLOW
  value: "true"
- name: MAX_WORKERS
  value: "16"
```

The `DISABLE_INGEST_WITH_LANGFLOW` flag already exists. When `true`, the backend uses `process_document_standard()` directly: `Docling → embeddings → OpenSearch`. No Langflow involved.

#### 1b. Bulk OpenSearch indexing

**File:** `src/models/processors.py:294–346`

Replace the per-chunk loop:
```python
# Before (200 round-trips per document)
for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
    await opensearch_client.index(index=get_index_name(), id=chunk_id, body=chunk_doc)

# After (1–2 bulk calls per document)
actions = []
for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings)):
    chunk_id = f"{file_hash}_{i}"
    chunk_doc = { ... }  # same structure as today
    actions.append({"index": {"_index": get_index_name(), "_id": chunk_id}})
    actions.append(chunk_doc)

batch_size = int(os.getenv("BULK_BATCH_SIZE", "100"))
for i in range(0, len(actions), batch_size * 2):
    batch = actions[i : i + batch_size * 2]
    response = await opensearch_client.bulk(body=batch)
    if response.get("errors"):
        for item in response["items"]:
            if item.get("index", {}).get("error"):
                logger.error("Bulk index error: %s", item["index"]["error"])
```

New env var: `BULK_BATCH_SIZE` (default `100`). The ACL fields (`owner`, `allowed_users`, `allowed_groups`) in `chunk_doc` are unchanged — this is a drop-in replacement.

#### 1c. Expand Docling HTTP client pool

**File:** `src/config/settings.py` (where `docling_http_client` is initialized)

```python
# Before
docling_http_client = httpx.AsyncClient(timeout=...)

# After
docling_http_client = httpx.AsyncClient(
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    timeout=...
)
```

Default httpx limits are 5 keepalive connections. With 48 Docling replicas, this bottlenecks parallel dispatch. 200 connections saturates the full Docling fleet.

#### Phase 1 throughput estimate

With `MAX_WORKERS=16` and per-file time of ~1.1s (Docling ~0.8s + embeddings ~0.1s + bulk index ~0.1s + overhead ~0.1s):
- Theoretical: 16 / 1.1 ≈ **14.5 f/s**
- Real-world: **8–10 f/s** (network jitter, GC, embedding API latency)

---

### Phase 2 — Distributed Workers (Target: 15–25 f/s)

Enables horizontal scaling by making the ingestion path stateless and queue-driven.

#### 2a. Add Valkey dependency

**File:** `pyproject.toml`
```toml
"redis>=5.0.0",   # Valkey-compatible; redis.asyncio for async BRPOP
```

#### 2b. New `src/utils/queue.py` — ValkeyQueue abstraction

```python
import redis.asyncio as redis
import json, time

class ValkeyQueue:
    def __init__(self, url: str):
        self.client = redis.from_url(url, decode_responses=True)

    async def enqueue(self, queue: str, job: dict) -> None:
        await self.client.lpush(queue, json.dumps(job))

    async def blpop(self, queue: str, timeout: int = 30) -> str | None:
        result = await self.client.brpop(queue, timeout=timeout)
        return result[1] if result else None

    async def set_task_state(self, task_id: str, **fields) -> None:
        await self.client.hset(f"task:{task_id}", mapping=fields)
        await self.client.expire(f"task:{task_id}", 86400)

    async def get_task_state(self, task_id: str) -> dict | None:
        return await self.client.hgetall(f"task:{task_id}") or None

    async def increment_task_counter(self, task_id: str, field: str, amount: int = 1) -> None:
        await self.client.hincrby(f"task:{task_id}", field, amount)
```

**Job descriptor schema (JSON enqueued by API pods):**
```json
{
  "task_id": "uuid",
  "processor_type": "DocumentFileProcessor",
  "file_key": "/tmp/tmpXXX.pdf",
  "filename": "report.pdf",
  "user_id": "user@example.com",
  "jwt_token": "...",
  "owner_name": "Alice",
  "owner_email": "alice@example.com",
  "connector_type": "local",
  "allowed_users": [],
  "allowed_groups": [],
  "enqueued_at": 1713000000.0
}
```
Connector jobs (S3, Google Drive) use `connection_id` + `file_id` instead of `file_key`.

#### 2c. Modify `src/services/task_service.py`

Add Valkey-backed mode alongside the existing in-memory path:

```python
class TaskService:
    def __init__(self, valkey_queue: ValkeyQueue | None = None):
        self._valkey = valkey_queue
        # ... existing init unchanged

    async def create_custom_task(self, items, ...) -> str:
        task_id = str(uuid4())
        if self._valkey:
            # Write initial state to Valkey; enqueue each item as a job
            await self._valkey.set_task_state(task_id,
                status="PENDING", total=len(items),
                processed=0, successful=0, failed=0)
            for item in items:
                await self._valkey.enqueue("ingest:queue", {
                    "task_id": task_id, **item.to_job_dict()
                })
            return task_id
        # Fallback: existing asyncio.Semaphore path unchanged
        return await self._legacy_create_task(items, ...)

    async def get_task_status(self, task_id: str) -> dict | None:
        if self._valkey:
            state = await self._valkey.get_task_state(task_id)
            if not state:
                return None
            # Return same JSON shape as existing in-memory path
            return {"status": state["status"], "processed_files": int(state["processed"]), ...}
        return self._task_store.get(task_id)
```

**Fallback guarantee:** When `VALKEY_URL` is not set, `ValkeyQueue` is `None`, and `TaskService` uses the existing `asyncio.Semaphore` path unchanged. Local dev / Docker Compose are unaffected.

#### 2d. New `src/worker.py` — worker process entrypoint

```python
import asyncio, os, json
from utils.queue import ValkeyQueue
from config.settings import clients
from models.processors import TaskProcessor

async def process_job(queue: ValkeyQueue, raw: str) -> None:
    job = json.loads(raw)
    task_id = job["task_id"]
    try:
        await queue.set_task_state(task_id, **{job["file_key"]: "RUNNING"})
        processor = TaskProcessor()
        await processor.process_document_standard(
            file_path=job["file_key"],
            filename=job["filename"],
            user_id=job["user_id"],
            # ... remaining fields from job
        )
        await queue.increment_task_counter(task_id, "successful")
    except Exception as e:
        await queue.increment_task_counter(task_id, "failed")
    finally:
        await queue.increment_task_counter(task_id, "processed")

async def worker_loop(queue: ValkeyQueue) -> None:
    while True:
        raw = await queue.blpop("ingest:queue", timeout=30)
        if raw:
            asyncio.create_task(process_job(queue, raw))

async def main() -> None:
    await clients.initialize_worker_mode()  # skip Langflow init
    queue = ValkeyQueue(os.environ["VALKEY_URL"])
    worker_count = int(os.getenv("MAX_WORKERS", "8"))
    await asyncio.gather(*[worker_loop(queue) for _ in range(worker_count)])

if __name__ == "__main__":
    asyncio.run(main())
```

No FastAPI. No Semaphore needed (BRPOP provides natural concurrency bounding).

#### 2e. Kubernetes: Split API and Worker Deployments

**API deployment changes** (`deployment.yaml`):
```yaml
strategy:
  type: RollingUpdate     # was: Recreate
replicas: 2
env:
  - name: OPENRAG_ROLE
    value: api
  - name: VALKEY_URL
    value: valkey://valkey.valkey.svc.cluster.local:6379
```

**New `worker-deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openrag-ingestion-workers
spec:
  replicas: 4
  template:
    spec:
      containers:
        - name: worker
          image: "{{ same OpenRAG image }}"
          command: ["python", "-m", "worker"]
          env:
            - name: OPENRAG_ROLE
              value: worker
            - name: DISABLE_INGEST_WITH_LANGFLOW
              value: "true"
            - name: VALKEY_URL
              value: valkey://valkey.valkey.svc.cluster.local:6379
            - name: MAX_WORKERS
              value: "8"
            - name: BULK_BATCH_SIZE
              value: "100"
            - name: DOCLING_SERVE_URL
              value: http://docling-serve.docling.svc.cluster.local:5001
          resources:
            requests:
              cpu: "2"
              memory: 4Gi
            limits:
              cpu: "4"
              memory: 8Gi
          # No PVC mounts — fully stateless
```

**KEDA ScaledObject** (queue-depth autoscaling):
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ingestion-worker-scaler
spec:
  scaleTargetRef:
    name: openrag-ingestion-workers
  minReplicaCount: 4
  maxReplicaCount: 12
  triggers:
    - type: redis
      metadata:
        address: valkey.valkey.svc.cluster.local:6379
        listName: ingest:queue
        listLength: "20"   # scale up when > 20 jobs pending
```

#### 2f. OpenSearch refresh interval

During heavy batch ingestion, set `refresh_interval: 5s` on the index (default is 1s). The explicit `indices.refresh()` call in `task_service.py:424` at task completion still ensures freshness before the task is marked COMPLETED.

```python
await opensearch_client.indices.put_settings(
    index=get_index_name(),
    body={"index": {"refresh_interval": "5s"}}
)
```

---

### Phase 3 — Scale Out (Target: 25–40 f/s)

After Phase 2 profiling, the bottleneck shifts from pipeline orchestration to embedding API throughput.

- **More worker pods:** Scale to 8–12 worker pods (requires 60+ Docling replicas proportionally)
- **Ollama embeddings:** Scale Ollama horizontally behind a K8s ClusterIP service (same load-balancing pattern as Docling)
- **OpenAI embeddings:** Add token-bucket rate-limit shaping in the worker to stay within API tier limits
- **OpenSearch:** Add 1–2 data nodes if bulk indexing P99 latency exceeds 200 ms
- **Docling HPA tuning:** Set `scaleDown.stabilizationWindowSeconds: 300` to prevent rapid scale-down thrashing during sustained ingestion

---

## Environment Variables Reference

| Variable | Deployment | Default | Purpose |
|---|---|---|---|
| `DISABLE_INGEST_WITH_LANGFLOW` | BE / Worker | `false` | `true` = bypass Langflow |
| `OPENRAG_ROLE` | Both | `api` | `api` or `worker` |
| `VALKEY_URL` | Both | unset | Redis/Valkey connection string |
| `MAX_WORKERS` | Worker | `4` | Asyncio concurrency per pod |
| `BULK_BATCH_SIZE` | Worker | `100` | OpenSearch bulk batch size |
| `DOCLING_SERVE_URL` | Worker | auto-detect | Docling ClusterIP DNS |
| `DOCLING_HTTP_MAX_CONNECTIONS` | Worker | `200` | httpx connection pool |
| `INGESTION_TIMEOUT` | Worker | `3600` | Per-file timeout (seconds) |
| `VALKEY_TASK_TTL` | Worker | `86400` | Task state expiry (seconds) |

---

## Expected Throughput

| Phase | Configuration | Est. Throughput | vs. Baseline |
|---|---|---|---|
| Baseline | Langflow, 96 workers, 1 BE pod | ~2 f/s (0.60 MB/s) | 1× |
| Phase 1 | No Langflow, bulk index, pool fix, `MAX_WORKERS=16` | **8–10 f/s** | 4–5× |
| Phase 2 | + 4 worker pods × 8 asyncio workers (32 concurrent) | **15–25 f/s** | 7–12× |
| Phase 3 | + 12 worker pods, 60 Docling replicas | **25–40 f/s** | 12–20× |

**The 10 f/s target is achievable in Phase 1 with a single pod and no new infrastructure.**

---

## Cost Projection

| Component | Current | Phase 1 | Phase 2 |
|---|---|---|---|
| Langflow (reduce 96 → 16 workers for chat only) | ~$1,500/mo | ~$500/mo | ~$500/mo |
| Docling (better utilization, same HPA) | ~$11,250/mo | ~$9,000/mo | ~$8,500/mo |
| Worker pods (4 × 2 CPU/4Gi, new) | $0 | $0 | ~$200/mo |
| OpenSearch + misc | ~$2,250/mo | ~$2,250/mo | ~$2,250/mo |
| **Total** | **~$15,000/mo** | **~$11,750/mo** | **~$11,450/mo** |

**Net savings after Phase 2: ~$3,500/month while achieving 7–12× throughput improvement.**

Docling cost reduction comes from better utilization (workers feed Docling continuously instead of Langflow creating idle gaps) and more efficient HPA scale-down during off-peak.

---

## Backward Compatibility

| Scenario | Impact |
|---|---|
| `DISABLE_INGEST_WITH_LANGFLOW=false` (default) | No change. All Langflow code paths untouched. |
| `VALKEY_URL` not set | `TaskService` uses existing in-memory `asyncio.Semaphore` path. Docker Compose / local dev unchanged. |
| Connector sync + webhooks | `ConnectorFileProcessor` → `process_document_standard()` unchanged; only task dispatch mechanism changes (enqueue vs. inline). API returns same `task_id` immediately. |
| ACL model | `chunk_doc` structure in bulk call is identical to the current per-chunk call. `allowed_users`, `allowed_groups`, `owner` fields unchanged. |
| Task status API `GET /tasks/{task_id}` | Response JSON shape preserved. `TaskService.get_task_status()` returns identical dict from in-memory or Valkey. |
| Chat endpoint | `LANGFLOW_CHAT_FLOW_ID` continues to route through Langflow. No change. |

---

## Critical Files to Modify

| File | Change | Phase |
|---|---|---|
| `src/models/processors.py:294–346` | Replace per-chunk `index()` with `bulk()` | 1 |
| `src/config/settings.py` | Expand `docling_http_client` connection limits | 1 |
| `pyproject.toml` | Add `redis>=5.0.0` | 2 |
| `src/utils/queue.py` *(new)* | `ValkeyQueue` abstraction | 2 |
| `src/services/task_service.py` | Valkey-backed enqueue + status-read mode | 2 |
| `src/worker.py` *(new)* | Worker process entrypoint (asyncio, no FastAPI) | 2 |
| `kubernetes/.../backend/deployment.yaml` | `OPENRAG_ROLE=api`, `RollingUpdate` strategy | 2 |
| `kubernetes/.../backend/worker-deployment.yaml` *(new)* | Worker Deployment | 2 |
| `kubernetes/.../backend/worker-scaledobject.yaml` *(new)* | KEDA queue-depth autoscaler | 2 |
| `kubernetes/.../values.yaml` | `worker.*` section, `ingestion.*` params | 2 |

---

## Verification Plan

**Phase 1 (local/single-pod):**
1. Set `DISABLE_INGEST_WITH_LANGFLOW=true`, `MAX_WORKERS=8`, `BULK_BATCH_SIZE=50`
2. Upload 100 PDFs via perf client or UI
3. Confirm OpenSearch slow-log shows bulk calls (not individual `index`)
4. Measure f/s from task completion timestamps in logs

**Phase 2 (GKE):**
1. Deploy API + worker pods; verify job flow: `LLEN ingest:queue` shrinks as workers consume
2. Run perf client at 160 concurrent requests
3. Watch KEDA trigger worker scale-out as queue depth builds
4. `GET /api/tasks/{task_id}` must return accurate counts mid-flight
5. `valkey-cli MONITOR` to verify BRPOP and HSET patterns

**Regression:**
- Connector sync (Google Drive / S3) with non-Langflow path — verify ACL fields in indexed chunks
- Upload 10 files with `DISABLE_INGEST_WITH_LANGFLOW=false` — Langflow path still functional
- Chat endpoint responds correctly (Langflow chat flow unaffected)
