#!/usr/bin/env python3
"""Entrypoint for the OpenRAG Langflow container.

The container now runs as langflow user (UID 1000) by default. If started as
root (legacy mode), this script will fix permissions and drop privileges.

Modern deployments should use:
- Podman with :U flag for automatic UID mapping
- Docker with proper host UID mapping (--user flag or compose user directive)
- Kubernetes with fsGroup or runAsUser security context
"""
import os
import pathlib
import pwd
import sys

# Check if running as root (legacy mode)
if os.getuid() == 0:
    print("WARNING: Container started as root. Fixing volume permissions and dropping to langflow user.", file=sys.stderr)
    print("Consider using proper UID mapping (Podman :U flag or Docker --user) instead.", file=sys.stderr)
    
    data_dir = pathlib.Path("/app/langflow-data")
    
    try:
        data_dir.chmod(0o777)
    except OSError:
        pass
    
    # Look up uid 1000's passwd entry so we can restore HOME and USER correctly
    # after dropping privileges.
    try:
        pw = pwd.getpwuid(1000)
        home = pw.pw_dir
        user = pw.pw_name
    except KeyError:
        home = "/app"
        user = "langflow"
    
    # Drop from root to langflow (uid=1000, gid=1000).
    os.setgid(1000)
    os.setuid(1000)
    
    # Restore environment variables to reflect the unprivileged user.
    os.environ["HOME"] = home
    os.environ["USER"] = user

# Running as non-root (default) - proceed directly
os.execvp(sys.argv[1], sys.argv[1:])
