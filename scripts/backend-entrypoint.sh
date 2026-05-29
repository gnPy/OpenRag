#!/bin/sh
# backend-entrypoint.sh — start application as non-root user.
#
# The container now runs as appuser (UID 1000) by default. If the container
# is explicitly started as root (e.g., for legacy Docker setups without proper
# volume UID mapping), this script will fix permissions and drop to appuser.
#
# Modern deployments should use:
# - Podman with :U flag for automatic UID mapping
# - Docker with proper host UID mapping (--user flag or compose user directive)
# - Kubernetes with fsGroup or runAsUser security context

set -e

if [ "$(id -u)" = "0" ]; then
    # Running as root (legacy mode) - fix permissions and drop privileges
    echo "WARNING: Container started as root. Fixing volume permissions and dropping to appuser."
    echo "Consider using proper UID mapping (Podman :U flag or Docker --user) instead."
    chown -R appuser:appuser \
        /app/keys \
        /app/flows \
        /app/config \
        /app/data \
        /app/openrag-documents \
        2>/dev/null || true
    # Preserve environment (including PATH with virtualenv) when dropping to appuser
    exec runuser -u appuser --preserve-environment -- "$@"
else
    # Running as non-root (default) - proceed directly
    exec "$@"
fi
