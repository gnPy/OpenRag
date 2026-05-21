"use client";

import { ErrorFilled, IncidentReporter } from "@carbon/icons-react";
import { ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { type Task } from "@/contexts/task-context";
import { getFailedFileEntries } from "@/lib/task-utils";
import { formatTaskTimestamp, parseTimestamp } from "@/lib/time-utils";
import { cn } from "@/lib/utils";

interface TaskErrorContentProps {
  task: Task;
  mode?: "recent" | "past";
  nowMs?: number;
  showHeader?: boolean;
}

export function TaskErrorContent({
  task,
  mode = "recent",
  nowMs = Date.now(),
  showHeader = true,
}: TaskErrorContentProps) {
  const [accordionValue, setAccordionValue] = useState("");
  const isExpanded = accordionValue === "failed-files";

  const failedEntries = useMemo(() => getFailedFileEntries(task), [task]);

  const failedCount = task.failed_files ?? failedEntries.length;
  const successCount = task.successful_files ?? 0;
  const timestamp =
    parseTimestamp(task.created_at) ?? parseTimestamp(task.updated_at);
  const statusLabel = "Failed";
  const statusPillClassName =
    "text-destructive border-failure-pill bg-failure-soft";

  if (failedCount <= 0 && failedEntries.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-1 w-full",
        showHeader
          ? "rounded-task border border-muted py-mmd px-4 hover:bg-muted/60 transition-colors"
          : "pt-2",
      )}
    >
      {showHeader && (
        <>
          <div className="flex items-center justify-between gap-1.5 min-w-0">
            <div className="flex items-center gap-2.5 min-w-0 ">
              <ErrorFilled className="size-5 shrink-0 text-destructive" />
              <p className="text-mmd truncate">
                Task {task.task_id.slice(0, 8)}...
              </p>
            </div>
            {!isExpanded && (
              <p
                className={`text-xs shrink-0 border rounded-full px-2 py-1 ${statusPillClassName}`}
              >
                {statusLabel}
              </p>
            )}
          </div>

          <div className="flex flex-col justify-between gap-1 pl-[30px]">
            <p className="text-xxs text-muted-foreground whitespace-nowrap leading-4 min-h-4">
              {formatTaskTimestamp(timestamp, mode, nowMs)}
            </p>
          </div>
        </>
      )}

      <Accordion
        type="single"
        collapsible
        className="rounded-task border-0"
        value={accordionValue}
        onValueChange={(value) =>
          setAccordionValue(value === "failed-files" ? "failed-files" : "")
        }
      >
        <AccordionItem value="failed-files" className="border-0 rounded-none">
          <AccordionTrigger className="group px-0 py-0 text-sm text-muted-foreground hover:text-foreground transition-colors [&>svg:first-child]:hidden">
            <div className="flex w-full items-center justify-between gap-2 pl-[30px]">
              <div className="flex items-center gap-1">
                <span className="text-xs">
                  {successCount} success · {failedCount} failed
                </span>
                <ChevronDown className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
              </div>
              <button
                type="button"
                aria-label="Report incident"
                className="inline-flex shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onPointerDown={(event) => event.stopPropagation()}
              >
                <IncidentReporter className="size-4" />
              </button>
            </div>
          </AccordionTrigger>
          <AccordionContent className="p-0 pt-2">
            <div className="flex flex-col gap-2 pt-2">
              {failedEntries.map(([filePath, fileInfo], index) => {
                const fileName =
                  fileInfo.filename || filePath.split("/").pop() || filePath;
                const message =
                  typeof fileInfo.error === "string" && fileInfo.error.trim()
                    ? fileInfo.error.trim()
                    : task.error || "Unknown error";

                return (
                  <div
                    key={`${task.task_id}-${filePath}-${index}`}
                    className="space-y-1 rounded border-destructive/20 bg-failure-soft py-mmd px-4"
                  >
                    <p className="text-xs font-semibold text-failure-file truncate">
                      {fileName}
                    </p>
                    <p className="text-xs text-failure-message break-words">
                      {message}
                    </p>
                  </div>
                );
              })}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
