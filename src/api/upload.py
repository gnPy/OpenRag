from dependencies import get_models_service
import os
from typing import Optional
from urllib.parse import urlparse

import boto3
from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from dependencies import (
    get_document_service,
    get_task_service,
    get_chat_service,
    get_session_manager,
    get_current_user,
)
from session_manager import User
from utils.logging_config import get_logger
from config.limits import (
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_MB,
    FileTooLargeError,
    format_size,
    is_within_size_limit,
    partition_by_size,
)

logger = get_logger(__name__)


class UploadPathBody(BaseModel):
    path: str


class UploadBucketBody(BaseModel):
    s3_url: str


async def upload(
    file: UploadFile = File(...),
    document_service=Depends(get_document_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Upload a single file"""
    try:
        if file.size is not None and not is_within_size_limit(file.size):
            err = FileTooLargeError(file.filename or "upload", file.size)
            logger.warning(
                "[INGEST] Upload rejected — file too large",
                filename=err.filename,
                size_bytes=err.size_bytes,
                limit_bytes=err.limit_bytes,
            )
            return JSONResponse({"error": str(err)}, status_code=413)

        from config.settings import is_no_auth_mode
        is_no_auth = is_no_auth_mode()
        owner_user_id = user.user_id if (user and not is_no_auth) else None
        owner_name = user.name if user else None
        owner_email = user.email if user else None

        result = await document_service.process_upload_file(
            file,
            owner_user_id=owner_user_id,
            jwt_token=user.jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )
        return JSONResponse(result, status_code=201)
    except Exception as e:
        error_msg = str(e)
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            logger.warning("[INGEST] Upload rejected — access denied", error=error_msg)
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            logger.exception("[INGEST] Upload failed")
            return JSONResponse({"error": error_msg}, status_code=500)


async def upload_path(
    body: UploadPathBody,
    task_service=Depends(get_task_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Upload all files from a directory path"""
    if not body.path or not os.path.isdir(body.path):
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    file_paths = [
        os.path.join(root, fn) for root, _, files in os.walk(body.path) for fn in files
    ]

    if not file_paths:
        return JSONResponse({"error": "No files found in directory"}, status_code=400)

    sized = [(p, os.path.getsize(p)) for p in file_paths]
    ok_sized, skipped = partition_by_size(sized)
    if skipped:
        logger.warning(
            "[INGEST] Skipping oversized files from directory",
            skipped_count=len(skipped),
            limit_bytes=MAX_UPLOAD_SIZE_BYTES,
            skipped=[{"filename": s.filename, "size_bytes": s.size_bytes} for s in skipped],
        )
    if not ok_sized:
        return JSONResponse(
            {
                "error": (
                    f"All files exceed the upload size limit of "
                    f"{format_size(MAX_UPLOAD_SIZE_BYTES)}"
                ),
                "skipped_files": [
                    {"filename": s.filename, "size_bytes": s.size_bytes} for s in skipped
                ],
            },
            status_code=413,
        )
    file_paths = [p for p, _ in ok_sized]

    jwt_token = user.jwt_token

    from config.settings import is_no_auth_mode
    is_no_auth = is_no_auth_mode()
    owner_user_id = user.user_id if (user and not is_no_auth) else None
    owner_name = user.name if user else None
    owner_email = user.email if user else None

    from api.documents import _ensure_index_exists
    await _ensure_index_exists(jwt_token)

    task_id = await task_service.create_upload_task(
        owner_user_id,
        file_paths,
        jwt_token=jwt_token,
        owner_name=owner_name,
        owner_email=owner_email,
    )

    return JSONResponse(
        {
            "task_id": task_id,
            "total_files": len(file_paths),
            "status": "accepted",
            "skipped_files": [
                {"filename": s.filename, "size_bytes": s.size_bytes} for s in skipped
            ],
        },
        status_code=201,
    )


async def upload_context(
    file: UploadFile = File(...),
    previous_response_id: Optional[str] = Form(None),
    endpoint: str = Form("langflow"),
    document_service=Depends(get_document_service),
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Upload a file and add its content as context to the current conversation"""
    filename = file.filename or "uploaded_document"
    user_id = user.user_id if user else None

    if file.size is not None and not is_within_size_limit(file.size):
        err = FileTooLargeError(filename, file.size)
        logger.warning(
            "[INGEST] Context upload rejected — file too large",
            filename=err.filename,
            size_bytes=err.size_bytes,
            limit_bytes=err.limit_bytes,
        )
        return JSONResponse({"error": str(err)}, status_code=413)

    jwt_token = user.jwt_token

    doc_result = await document_service.process_upload_context(file, filename)

    response_text, response_id = await chat_service.upload_context_chat(
        doc_result["content"],
        filename,
        user_id=user_id,
        jwt_token=jwt_token,
        previous_response_id=previous_response_id,
        endpoint=endpoint,
    )

    response_data = {
        "status": "context_added",
        "filename": doc_result["filename"],
        "pages": doc_result["pages"],
        "content_length": doc_result["content_length"],
        "response_id": response_id,
        "confirmation": response_text,
    }

    return JSONResponse(response_data)


async def upload_options(
    user: User = Depends(get_current_user),
):
    """Return availability of upload features"""
    aws_enabled = bool(
        os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
    )
    from config.settings import UPLOAD_BATCH_SIZE
    return JSONResponse(
        {
            "aws": aws_enabled,
            "upload_batch_size": UPLOAD_BATCH_SIZE,
            "max_upload_size_mb": MAX_UPLOAD_SIZE_MB,
            "max_upload_size_bytes": MAX_UPLOAD_SIZE_BYTES,
        }
    )


async def upload_bucket(
    body: UploadBucketBody,
    task_service=Depends(get_task_service),
    models_service=Depends(get_models_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Process all files from an S3 bucket URL"""
    if not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
        return JSONResponse(
            {"error": "AWS credentials not configured"}, status_code=400
        )

    if not body.s3_url or not body.s3_url.startswith("s3://"):
        return JSONResponse({"error": "Invalid S3 URL"}, status_code=400)

    parsed = urlparse(body.s3_url)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")

    s3_client = boto3.client("s3")
    keys = []
    skipped_bucket: list[dict] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            size = obj.get("Size", 0)
            if not is_within_size_limit(size):
                skipped_bucket.append({"filename": key, "size_bytes": size})
                continue
            keys.append(key)

    if skipped_bucket:
        logger.warning(
            "[INGEST] Skipping oversized S3 objects",
            skipped_count=len(skipped_bucket),
            limit_bytes=MAX_UPLOAD_SIZE_BYTES,
        )

    if not keys:
        return JSONResponse(
            {
                "error": (
                    "No files found in bucket"
                    if not skipped_bucket
                    else f"All objects exceed the upload size limit of "
                         f"{format_size(MAX_UPLOAD_SIZE_BYTES)}"
                ),
                "skipped_files": skipped_bucket,
            },
            status_code=400 if not skipped_bucket else 413,
        )

    jwt_token = user.jwt_token

    from models.processors import S3FileProcessor

    from config.settings import is_no_auth_mode
    is_no_auth = is_no_auth_mode()
    owner_user_id = user.user_id if (user and not is_no_auth) else None
    owner_name = user.name if user else None
    owner_email = user.email if user else None
    task_user_id = user.user_id if (user and not is_no_auth) else None

    from api.documents import _ensure_index_exists
    await _ensure_index_exists(jwt_token)

    processor = S3FileProcessor(
        task_service.document_service,
        bucket,
        models_service=models_service,
        s3_client=s3_client,
        owner_user_id=owner_user_id,
        jwt_token=jwt_token,
        owner_name=owner_name,
        owner_email=owner_email,
    )

    task_id = await task_service.create_custom_task(task_user_id, keys, processor)

    return JSONResponse(
        {
            "task_id": task_id,
            "total_files": len(keys),
            "status": "accepted",
            "skipped_files": skipped_bucket,
        },
        status_code=201,
    )
