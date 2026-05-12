"""Infra-admin plane.

Higher-privilege endpoints (OpenSearch security setup, post-bootstrap user
provisioning) gated by either:

  * a configurable JWT claim (SaaS / on_prem mode), or
  * HTTP Basic auth (OSS mode)

This plane bypasses the DB-resident RBAC at /api/admin/* entirely so an
operator can bootstrap a fresh install before any user rows exist.
"""

from api.infra.endpoints import router

__all__ = ["router"]
