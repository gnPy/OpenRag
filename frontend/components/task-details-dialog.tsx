"use client";

import {
  CheckCircle,
  ChevronDown,
  Clock,
  Loader2,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import {
  type Task,
  type TaskFileEntry,
} from "@/app/api/queries/useGetTasksQuery";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTask } from "@/contexts/task-context";
import { parseTimestamp } from "@/lib/time-utils";

type NormalizedStatus = "completed" | "failed" | "processing" | "pending";
type TabValue = "all" | NormalizedStatus;

interface FileRow {
  path: string;
  filename: string;
  normalizedStatus: NormalizedStatus;
  duration?: number;
  error?: string;
}

function normalizeFileStatus(
  status: TaskFileEntry["status"],
): NormalizedStatus {
  switch (status) {
    case "completed":
      return "completed";
    case "failed":
    case "error":
      return "failed";
    case "running":
    case "processing":
      return "processing";
    default:
      return "pending";
  }
}

function buildFileRows(task: Task): FileRow[] {
  return Object.entries(task.files || {}).map(([path, info]) => ({
    path,
    filename: info.filename || path.split("/").pop() || path,
    normalizedStatus: normalizeFileStatus(info.status),
    duration:
      typeof info.duration_seconds === "number"
        ? info.duration_seconds
        : undefined,
    error:
      typeof info.error === "string" && info.error.trim()
        ? info.error.trim()
        : typeof task.error === "string" && info.status === "failed"
          ? task.error.trim()
          : undefined,
  }));
}

function formatDuration(seconds?: number): string | null {
  if (seconds == null || seconds < 0) return null;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

function formatRelativeTime(dateString: string): string {
  const date = parseTimestamp(dateString);
  if (!date) return "Unknown time";
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

const STATUS_STYLES: Record<NormalizedStatus, string> = {
  completed: "bg-green-500/10 text-green-500 border-green-500/20",
  failed: "bg-red-500/10 text-red-500 border-red-500/20",
  processing: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  pending: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
};

const STATUS_LABELS: Record<NormalizedStatus, string> = {
  completed: "Completed",
  failed: "Failed",
  processing: "Processing",
  pending: "Pending",
};

function FileStatusIcon({ status }: { status: NormalizedStatus }) {
  switch (status) {
    case "completed":
      return <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-red-500 shrink-0" />;
    case "processing":
      return (
        <Loader2 className="h-4 w-4 text-blue-500 animate-spin shrink-0" />
      );
    case "pending":
      return <Clock className="h-4 w-4 text-yellow-500 shrink-0" />;
  }
}

function TaskStatusBadge({ status }: { status: Task["status"] }) {
  const isActive =
    status === "pending" || status === "running" || status === "processing";
  if (isActive)
    return (
      <Badge
        variant="outline"
        className="rounded-full bg-blue-500/10 text-blue-500 border-blue-500/20"
      >
        {status === "pending" ? "Pending" : "Processing"}
      </Badge>
    );
  if (status === "failed" || status === "error")
    return (
      <Badge
        variant="outline"
        className="rounded-full bg-red-500/10 text-red-500 border-red-500/20"
      >
        Failed
      </Badge>
    );
  if (status === "completed")
    return (
      <Badge
        variant="outline"
        className="rounded-full bg-green-500/10 text-green-500 border-green-500/20"
      >
        Completed
      </Badge>
    );
  return null;
}

interface FileRowItemProps {
  row: FileRow;
  isExpanded: boolean;
  onToggle: () => void;
}

function FileRowItem({ row, isExpanded, onToggle }: FileRowItemProps) {
  const hasError = !!row.error;

  return (
    <div className="border-b border-border last:border-0">
      <div
        className={`flex items-center gap-3 px-6 py-3 text-sm ${hasError ? "cursor-pointer hover:bg-muted/50 transition-colors" : ""}`}
        onClick={hasError ? onToggle : undefined}
        role={hasError ? "button" : undefined}
      >
        <FileStatusIcon status={row.normalizedStatus} />
        <span className="flex-1 min-w-0 truncate text-xs font-medium">
          {row.filename}
        </span>
        <span className="text-xs text-muted-foreground shrink-0 tabular-nums">
          {formatDuration(row.duration) ?? "—"}
        </span>
        <Badge
          variant="outline"
          className={`rounded-full text-xs shrink-0 ${STATUS_STYLES[row.normalizedStatus]}`}
        >
          {STATUS_LABELS[row.normalizedStatus]}
        </Badge>
        {hasError && (
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground shrink-0 transition-transform duration-150 ${isExpanded ? "rotate-180" : ""}`}
          />
        )}
      </div>
      {isExpanded && row.error && (
        <div className="px-6 pb-3 pl-[52px]">
          <div className="rounded-lg border border-destructive/20 bg-failure-soft p-3">
            <p className="text-xs text-failure-message break-words">
              {row.error}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export function TaskDetailsDialog() {
  const { tasks, selectedTaskId, setSelectedTaskId } = useTask();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabValue>("all");

  const task = useMemo(
    () => tasks.find((t) => t.task_id === selectedTaskId) ?? null,
    [tasks, selectedTaskId],
  );

  const allRows = useMemo(() => (task ? buildFileRows(task) : []), [task]);

  const counts = useMemo(() => {
    const c = { completed: 0, failed: 0, processing: 0, pending: 0 };
    allRows.forEach((r) => c[r.normalizedStatus]++);
    return c;
  }, [allRows]);

  const filteredRows = useMemo(
    () =>
      activeTab === "all"
        ? allRows
        : allRows.filter((r) => r.normalizedStatus === activeTab),
    [allRows, activeTab],
  );

  const tabs: { value: TabValue; label: string; count: number }[] = [
    { value: "all", label: "All", count: allRows.length },
    ...(counts.completed > 0
      ? [
          {
            value: "completed" as TabValue,
            label: "Completed",
            count: counts.completed,
          },
        ]
      : []),
    ...(counts.failed > 0
      ? [{ value: "failed" as TabValue, label: "Failed", count: counts.failed }]
      : []),
    ...(counts.processing > 0
      ? [
          {
            value: "processing" as TabValue,
            label: "Processing",
            count: counts.processing,
          },
        ]
      : []),
    ...(counts.pending > 0
      ? [
          {
            value: "pending" as TabValue,
            label: "Pending",
            count: counts.pending,
          },
        ]
      : []),
  ];

  function handleClose() {
    setSelectedTaskId(null);
    setExpandedRow(null);
    setActiveTab("all");
  }

  if (!task) return null;

  const succeededCount = task.successful_files ?? counts.completed;
  const failedCount = task.failed_files ?? counts.failed;
  const totalCount = task.total_files ?? allRows.length;

  return (
    <Dialog
      open={!!selectedTaskId}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <div className="flex items-center gap-3 flex-wrap pr-8">
            <DialogTitle className="text-base font-semibold">
              Task {task.task_id}
            </DialogTitle>
            <TaskStatusBadge status={task.status} />
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1 flex-wrap">
            <span>Started {formatRelativeTime(task.created_at)}</span>
            {formatDuration(task.duration_seconds) && (
              <>
                <span>·</span>
                <span>{formatDuration(task.duration_seconds)}</span>
              </>
            )}
            <span>·</span>
            <span className="text-green-600">{succeededCount} succeeded</span>
            <span className="text-red-500">{failedCount} failed</span>
            <span className="text-muted-foreground">{totalCount} total</span>
          </div>
        </DialogHeader>

        <Tabs
          value={activeTab}
          onValueChange={(v) => {
            setActiveTab(v as TabValue);
            setExpandedRow(null);
          }}
          className="flex flex-col flex-1 min-h-0"
        >
          <div className="px-6 border-b border-border shrink-0">
            <TabsList className="inline-flex gap-0 h-auto p-0 bg-transparent w-auto justify-start">
              {tabs.map((tab) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className="flex-row items-center gap-1.5 px-3 py-2.5 h-auto w-auto border-0 border-b-2 border-transparent rounded-none text-xs font-medium text-muted-foreground bg-transparent data-[state=active]:bg-transparent data-[state=active]:border-foreground data-[state=active]:text-foreground"
                >
                  {tab.label}
                  <span className="text-[10px] tabular-nums opacity-60">
                    {tab.count}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <div className="flex-1 overflow-y-auto">
            {filteredRows.length === 0 ? (
              <p className="p-8 text-sm text-muted-foreground text-center">
                No files in this category.
              </p>
            ) : (
              filteredRows.map((row) => (
                <FileRowItem
                  key={row.path}
                  row={row}
                  isExpanded={expandedRow === row.path}
                  onToggle={() =>
                    setExpandedRow(expandedRow === row.path ? null : row.path)
                  }
                />
              ))
            )}
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
