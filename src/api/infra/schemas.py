"""Pydantic shapes for the /api/infra/* plane."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class OpenSearchStatus(BaseModel):
    status: Literal["healthy", "degraded", "unconfigured"]
    configured: bool
    last_setup_at: Optional[str] = None
    drift: bool = False
    message: str = ""


class UserCreateBody(BaseModel):
    email: str
    display_name: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    oauth_provider: Optional[str] = None
    oauth_subject: Optional[str] = None


class UserPatchBody(BaseModel):
    is_active: Optional[bool] = None
    display_name: Optional[str] = None
    roles: Optional[List[str]] = None


class UserRolesReplaceBody(BaseModel):
    roles: List[str]


class UserOut(BaseModel):
    id: str
    oauth_provider: str
    oauth_subject: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    picture_url: Optional[str] = None
    is_active: bool
    roles: List[str]
    created_at: Optional[str] = None
    last_login: Optional[str] = None
