"""
Utility functions for constructing OpenSearch queries consistently.
"""
from typing import List, Optional, Union


def build_filename_query(filename: str) -> dict:
    """
    Build a standardized query for finding documents by filename.

    Args:
        filename: The exact filename to search for

    Returns:
        A dict containing the OpenSearch query body
    """
    return {
        "term": {
            "filename": filename
        }
    }


def build_filename_search_body(filename: str, size: int = 1, source: Union[bool, List[str]] = False) -> dict:
    """
    Build a complete search body for checking if a filename exists.

    Args:
        filename: The exact filename to search for
        size: Number of results to return (default: 1)
        source: Whether to include source fields, or list of specific fields to include (default: False)

    Returns:
        A dict containing the complete OpenSearch search body
    """
    return {
        "query": build_filename_query(filename),
        "size": size,
        "_source": source
    }


def build_rename_match_query(
    owner: Optional[str],
    filename_aliases: List[str],
    document_id: Optional[str] = None,
) -> dict:
    """
    Bool query matching all chunks for a rename: optional owner, filename in aliases,
    optional document_id (must match every targeted chunk when provided).
    """
    must: List[dict] = []
    if owner and owner != "anonymous":
        must.append({"term": {"owner": owner}})
    should_terms = [{"term": {"filename": a}} for a in filename_aliases if a]
    must.append({"bool": {"should": should_terms, "minimum_should_match": 1}})
    did = (document_id or "").strip()
    if did:
        must.append({"term": {"document_id": did}})
    return {"bool": {"must": must}}


def build_document_id_match_query(
    owner: Optional[str],
    document_id: str,
) -> dict:
    """All chunks for a logical document (owner + document_id)."""
    did = (document_id or "").strip()
    must: List[dict] = [{"term": {"document_id": did}}]
    if owner and owner != "anonymous":
        must.insert(0, {"term": {"owner": owner}})
    return {"bool": {"must": must}}


def build_document_id_not_matching_filenames_query(
    owner: Optional[str],
    document_id: str,
    filenames_to_match: List[str],
) -> dict:
    """
    Chunks for this document_id whose filename is not exactly one of filenames_to_match.
    Used to finish a rename when the UI 'current' name no longer matches indexed filenames.
    """
    did = (document_id or "").strip()
    must: List[dict] = [{"term": {"document_id": did}}]
    if owner and owner != "anonymous":
        must.insert(0, {"term": {"owner": owner}})
    terms = [t for t in filenames_to_match if t]
    if not terms:
        return {"bool": {"must": must}}
    return {
        "bool": {
            "must": must,
            "must_not": [
                {
                    "bool": {
                        "should": [{"term": {"filename": t}} for t in terms],
                        "minimum_should_match": 1,
                    }
                }
            ],
        }
    }


def build_rename_collision_query(
    owner: Optional[str],
    candidate_filenames: List[str],
    exclude_document_id: Optional[str] = None,
) -> dict:
    """
    True for chunks that use one of candidate_filenames, optionally scoped by owner,
    excluding the document being renamed (same document_id on all its chunks).
    """
    must: List[dict] = []
    if owner and owner != "anonymous":
        must.append({"term": {"owner": owner}})
    should_terms = [{"term": {"filename": c}} for c in candidate_filenames if c]
    must.append({"bool": {"should": should_terms, "minimum_should_match": 1}})
    ex = (exclude_document_id or "").strip()
    if ex:
        return {
            "bool": {
                "must": must,
                "must_not": [{"term": {"document_id": ex}}],
            }
        }
    return {"bool": {"must": must}}


def build_filename_delete_body(filename: str) -> dict:
    """
    Build a delete-by-query body for removing all documents with a filename.

    Args:
        filename: The exact filename to delete

    Returns:
        A dict containing the OpenSearch delete-by-query body
    """
    return {
        "query": build_filename_query(filename)
    }