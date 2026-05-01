"use client";

import { Activity, Loader2, RefreshCw } from "lucide-react";

import {
  type AuditEvent,
  useGetAuditEventsQuery,
} from "@/app/api/queries/useGetAuditEventsQuery";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const EVENT_BADGE: Record<
  string,
  {
    label: string;
    variant: "default" | "secondary" | "destructive" | "outline";
  }
> = {
  "user.bootstrap_admin": { label: "Bootstrap admin", variant: "default" },
  "user.created": { label: "User created", variant: "secondary" },
  "user.updated": { label: "User updated", variant: "secondary" },
  "user.deleted": { label: "User deleted", variant: "destructive" },
  "user.merged_legacy": { label: "Merged legacy", variant: "outline" },
  "user.role.assigned": { label: "Role assigned", variant: "default" },
  "user.role.revoked": { label: "Role revoked", variant: "destructive" },
  "role.created": { label: "Role created", variant: "default" },
  "role.updated": { label: "Role updated", variant: "secondary" },
  "role.deleted": { label: "Role deleted", variant: "destructive" },
  "permission.denied": { label: "Permission denied", variant: "outline" },
};

function formatRelative(iso: string): string {
  const ts = new Date(iso).getTime();
  const diffSec = Math.round((Date.now() - ts) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return new Date(iso).toLocaleString();
}

function summarizeMetadata(e: AuditEvent): string | null {
  const m = e.audit_metadata;
  if (!m) return null;
  if (typeof m.role_name === "string") return `→ ${m.role_name}`;
  if (typeof m.role === "string") return `→ ${m.role}`;
  if (typeof m.required === "string") return `(${m.required})`;
  if (typeof m.name === "string") return `“${m.name}”`;
  return null;
}

export function AuditLogFeed() {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useGetAuditEventsQuery({ limit: 20 });
  const events = data ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Activity size={18} /> Recent Activity
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label="Refresh audit log"
            className="h-7 w-7 p-0"
          >
            <RefreshCw
              className={
                isFetching ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"
              }
            />
          </Button>
        </CardTitle>
        <CardDescription>
          Last 20 RBAC events. Backend writes one row per role assignment,
          revocation, or permission denial.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
            <Loader2 className="animate-spin" size={14} /> Loading…
          </div>
        ) : isError ? (
          <div className="text-sm text-destructive">
            Failed to load audit log: {(error as Error).message}
          </div>
        ) : events.length === 0 ? (
          <div className="text-sm text-muted-foreground italic py-3">
            No events yet (or you do not have{" "}
            <code className="text-xs">audit:read</code>).
          </div>
        ) : (
          <ul className="divide-y">
            {events.map((e) => {
              const meta = EVENT_BADGE[e.event] ?? {
                label: e.event,
                variant: "outline" as const,
              };
              const summary = summarizeMetadata(e);
              return (
                <li key={e.id} className="py-2 flex items-start gap-3">
                  <Badge variant={meta.variant} className="shrink-0 mt-0.5">
                    {meta.label}
                  </Badge>
                  <div className="min-w-0 flex-1 text-sm">
                    <p className="truncate">
                      <span className="text-muted-foreground">
                        {e.actor_user_id ? "by " : "system "}
                      </span>
                      {e.actor_user_id && (
                        <span className="font-mono text-xs">
                          {e.actor_user_id.slice(0, 8)}…
                        </span>
                      )}
                      {e.target_id && (
                        <span className="text-muted-foreground">
                          {" → "}
                          <span className="font-mono text-xs">
                            {e.target_id.slice(0, 8)}…
                          </span>
                        </span>
                      )}
                      {summary && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          {summary}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatRelative(e.ts)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
