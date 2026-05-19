from collections.abc import Iterable

from utils.logging_config import get_logger

logger = get_logger(__name__)


async def collect_visible_document_ids(
    opensearch_client,
    *,
    index: str,
    query: dict,
    source: bool | list[str] = False,
    page_size: int = 1000,
    scroll_ttl: str = "2m",
) -> list[str]:
    """Collect visible document IDs for a query using the caller's OpenSearch client."""
    search_body = {"query": query, "size": page_size, "_source": source}
    response = await opensearch_client.search(
        index=index,
        body=search_body,
        scroll=scroll_ttl,
    )
    scroll_id = response.get("_scroll_id")
    document_ids: list[str] = []

    try:
        while True:
            hits = response.get("hits", {}).get("hits", [])
            document_ids.extend(hit["_id"] for hit in hits if hit.get("_id"))
            if not hits or len(hits) < page_size or not scroll_id:
                break
            response = await opensearch_client.scroll(scroll_id=scroll_id, scroll=scroll_ttl)
            scroll_id = response.get("_scroll_id") or scroll_id
    finally:
        if scroll_id and hasattr(opensearch_client, "clear_scroll"):
            try:
                await opensearch_client.clear_scroll(scroll_id=scroll_id)
            except Exception as e:
                logger.debug("Failed to clear OpenSearch scroll context", error=str(e))

    return document_ids


async def bulk_delete_document_ids(
    opensearch_client,
    *,
    index: str,
    document_ids: Iterable[str],
    refresh: bool = True,
) -> int:
    """Delete concrete OpenSearch document IDs through the caller's client."""
    bulk_body = []
    for document_id in document_ids:
        bulk_body.append({"delete": {"_index": index, "_id": document_id}})

    if not bulk_body:
        return 0

    response = await opensearch_client.bulk(body=bulk_body, refresh=refresh)
    deleted_count = 0
    for item in response.get("items", []):
        delete_result = item.get("delete", {})
        if delete_result.get("result") == "deleted":
            deleted_count += 1

    if response.get("errors"):
        logger.warning(
            "Bulk delete completed with OpenSearch item errors",
            attempted=len(bulk_body),
            deleted=deleted_count,
        )

    return deleted_count
