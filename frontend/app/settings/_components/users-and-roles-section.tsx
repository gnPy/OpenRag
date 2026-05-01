"use client";

import { Loader2, Search, ShieldCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useAssignRoleMutation } from "@/app/api/mutations/useAssignRoleMutation";
import { useRevokeRoleMutation } from "@/app/api/mutations/useRevokeRoleMutation";
import {
  type AdminRole,
  useGetAdminRolesQuery,
} from "@/app/api/queries/useGetAdminRolesQuery";
import {
  type AdminUser,
  useGetAdminUsersQuery,
} from "@/app/api/queries/useGetAdminUsersQuery";
import { RolePermissionsPreview } from "@/components/role-permissions-preview";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/contexts/auth-context";

import { AuditLogFeed } from "./audit-log-feed";

const ROLE_BADGE_VARIANT: Record<string, "default" | "secondary" | "outline"> =
  {
    admin: "default",
    developer: "secondary",
    user: "outline",
    viewer: "outline",
  };

interface UserRowProps {
  u: AdminUser;
  roles: AdminRole[];
  onAssign: (userId: string, roleId: string) => void;
  onRevoke: (userId: string, roleId: string, roleName: string) => void;
  pending: boolean;
  selfDbId?: string;
}

function UserRow({
  u,
  roles,
  onAssign,
  onRevoke,
  pending,
  selfDbId,
}: UserRowProps) {
  const [selectedRole, setSelectedRole] = useState<string>("");
  const isSelf = selfDbId && selfDbId === u.id;

  return (
    <div className="flex items-center justify-between gap-3 py-3 border-b last:border-b-0">
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <Avatar className="rounded-md w-8 h-8 shrink-0">
          {u.picture_url && (
            <AvatarImage src={u.picture_url} alt={u.display_name ?? ""} />
          )}
          <AvatarFallback className="text-xs rounded-md">
            {(u.display_name ?? u.email ?? "?").charAt(0).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate flex items-center gap-1.5">
            {u.display_name ?? "(unnamed)"}
            {isSelf && (
              <Badge variant="outline" className="text-[10px] py-0 px-1.5">
                you
              </Badge>
            )}
          </p>
          <p className="text-xs text-muted-foreground truncate">
            {u.email ?? u.oauth_subject}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap justify-end">
        {u.roles.length === 0 ? (
          <span className="text-xs text-muted-foreground italic">no roles</span>
        ) : (
          u.roles.map((r) => {
            const role = roles.find((rr) => rr.name === r);
            return (
              <Badge
                key={r}
                variant={ROLE_BADGE_VARIANT[r] ?? "outline"}
                className="gap-1"
              >
                {r}
                {role && (
                  <RolePermissionsPreview
                    name={role.name}
                    description={role.description}
                    permissions={role.permissions}
                  />
                )}
                {role && (
                  <button
                    type="button"
                    aria-label={`Remove ${r}`}
                    disabled={pending}
                    onClick={() => onRevoke(u.id, role.id, role.name)}
                    className="hover:bg-foreground/10 rounded-sm -mr-1 ml-0.5 disabled:opacity-50"
                  >
                    <X size={12} />
                  </button>
                )}
              </Badge>
            );
          })
        )}

        <Select
          value={selectedRole}
          onValueChange={(v) => {
            setSelectedRole("");
            const role = roles.find((rr) => rr.id === v);
            if (role) onAssign(u.id, role.id);
          }}
          disabled={pending}
        >
          <SelectTrigger className="h-7 w-[140px] text-xs">
            <SelectValue placeholder="+ Assign role" />
          </SelectTrigger>
          <SelectContent>
            {roles
              .filter((r) => !u.roles.includes(r.name))
              .map((r) => (
                <SelectItem key={r.id} value={r.id} className="text-xs">
                  <div className="flex items-center justify-between gap-2 w-full">
                    <span className="capitalize">{r.name}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {r.permissions.length} perms
                    </span>
                  </div>
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export function UsersAndRolesSection() {
  const { user: currentUser } = useAuth();
  const usersQuery = useGetAdminUsersQuery();
  const rolesQuery = useGetAdminRolesQuery();
  const assignMutation = useAssignRoleMutation();
  const revokeMutation = useRevokeRoleMutation();

  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<string>("__all");

  const [pendingRevoke, setPendingRevoke] = useState<{
    user_id: string;
    role_id: string;
    role_name: string;
  } | null>(null);

  const onAssign = (user_id: string, role_id: string) => {
    assignMutation.mutate(
      { user_id, role_id },
      {
        onSuccess: () => toast.success("Role assigned"),
        onError: (err: Error) => toast.error(err.message),
      },
    );
  };

  const performRevoke = (user_id: string, role_id: string) => {
    revokeMutation.mutate(
      { user_id, role_id },
      {
        onSuccess: () => toast.success("Role revoked"),
        onError: (err: Error) => toast.error(err.message),
      },
    );
  };

  const onRevoke = (user_id: string, role_id: string, role_name: string) => {
    if (role_name === "admin") {
      setPendingRevoke({ user_id, role_id, role_name });
      return;
    }
    performRevoke(user_id, role_id);
  };

  const isLoading = usersQuery.isLoading || rolesQuery.isLoading;
  const isMutating = assignMutation.isPending || revokeMutation.isPending;
  const users = usersQuery.data ?? [];
  const roles = rolesQuery.data ?? [];

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => {
      if (filterRole !== "__all" && !u.roles.includes(filterRole)) return false;
      if (!q) return true;
      const hay =
        `${u.email ?? ""} ${u.display_name ?? ""} ${u.oauth_subject}`.toLowerCase();
      return hay.includes(q);
    });
  }, [users, search, filterRole]);

  // Resolve current admin's DB id (by oauth subject) so we can mark "you".
  const selfDbId = useMemo(() => {
    if (!currentUser) return undefined;
    const match = users.find(
      (u) =>
        u.oauth_subject === currentUser.user_id || u.id === currentUser.user_id,
    );
    return match?.id;
  }, [users, currentUser]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck size={18} /> Users & Roles
          </CardTitle>
          <CardDescription>
            Assign or revoke roles. Backend enforces all permission checks; this
            UI mirrors the live state.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Search + filter */}
          <div className="flex items-center gap-2 mb-2">
            <div className="relative flex-1">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                placeholder="Search by name, email, or ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-8 pl-8 text-sm"
              />
            </div>
            <Select value={filterRole} onValueChange={setFilterRole}>
              <SelectTrigger className="h-8 w-[160px] text-xs">
                <SelectValue placeholder="All roles" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all" className="text-xs">
                  All roles
                </SelectItem>
                {roles.map((r) => (
                  <SelectItem key={r.id} value={r.name} className="text-xs">
                    <span className="capitalize">{r.name}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
              <Loader2 className="animate-spin" size={14} /> Loading users…
            </div>
          ) : usersQuery.isError ? (
            <div className="text-sm text-destructive">
              Failed to load users: {(usersQuery.error as Error).message}
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="text-sm text-muted-foreground italic py-4">
              {users.length === 0
                ? "No users found, or you do not have permission to list users."
                : "No users match your search."}
            </div>
          ) : (
            <div>
              {filteredUsers.map((u) => (
                <UserRow
                  key={u.id}
                  u={u}
                  roles={roles}
                  onAssign={onAssign}
                  onRevoke={onRevoke}
                  pending={isMutating}
                  selfDbId={selfDbId}
                />
              ))}
            </div>
          )}

          {roles.length > 0 && (
            <div className="mt-6 pt-4 border-t">
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
                Available Roles
              </p>
              <div className="flex flex-wrap gap-1.5">
                {roles.map((r) => (
                  <Badge
                    key={r.id}
                    variant={ROLE_BADGE_VARIANT[r.name] ?? "outline"}
                    className="gap-1"
                  >
                    <span className="capitalize">{r.name}</span>
                    <RolePermissionsPreview
                      name={r.name}
                      description={r.description}
                      permissions={r.permissions}
                    />
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <Button
            variant="ghost"
            size="sm"
            className="mt-4"
            onClick={() => {
              usersQuery.refetch();
              rolesQuery.refetch();
            }}
          >
            Refresh
          </Button>
        </CardContent>
      </Card>

      <AuditLogFeed />

      <Dialog
        open={pendingRevoke !== null}
        onOpenChange={(open) => !open && setPendingRevoke(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="mb-4">Revoke admin role?</DialogTitle>
            <DialogDescription className="text-left">
              <span className="block mb-2">
                You are about to remove the <strong>admin</strong> role from
                this user. They will lose all admin permissions immediately.
              </span>
              <span className="block text-xs text-muted-foreground">
                The backend prevents removing the last admin in the workspace.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setPendingRevoke(null)}
              size="sm"
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (pendingRevoke) {
                  performRevoke(pendingRevoke.user_id, pendingRevoke.role_id);
                  setPendingRevoke(null);
                }
              }}
              size="sm"
            >
              Revoke admin
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
