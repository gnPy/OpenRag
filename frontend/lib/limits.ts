export interface UploadLimits {
  maxUploadSizeMb: number;
  maxUploadSizeBytes: number;
}

export interface SkippedFile {
  name: string;
  size: number;
}

export interface PartitionResult<T> {
  ok: T[];
  skipped: SkippedFile[];
}

const DEFAULT_LIMITS: UploadLimits = {
  maxUploadSizeMb: 1.0,
  maxUploadSizeBytes: 1_048_576,
};

let cachedLimits: UploadLimits | null = null;

export async function fetchUploadLimits(
  forceRefresh = false,
): Promise<UploadLimits> {
  if (cachedLimits && !forceRefresh) return cachedLimits;
  try {
    const res = await fetch("/api/upload_options");
    if (!res.ok) return DEFAULT_LIMITS;
    const data = await res.json();
    const mb =
      typeof data.max_upload_size_mb === "number"
        ? data.max_upload_size_mb
        : DEFAULT_LIMITS.maxUploadSizeMb;
    const bytes =
      typeof data.max_upload_size_bytes === "number"
        ? data.max_upload_size_bytes
        : Math.round(mb * 1024 * 1024);
    cachedLimits = { maxUploadSizeMb: mb, maxUploadSizeBytes: bytes };
    return cachedLimits;
  } catch {
    return DEFAULT_LIMITS;
  }
}

export function formatSize(bytes: number): string {
  if (bytes == null) return "unknown";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function isWithinSizeLimit(
  sizeBytes: number | undefined | null,
  limitBytes: number,
): boolean {
  if (sizeBytes == null || sizeBytes < 0) return true;
  return sizeBytes <= limitBytes;
}

export function partitionFilesBySize(
  files: File[],
  limitBytes: number,
): PartitionResult<File> {
  const ok: File[] = [];
  const skipped: SkippedFile[] = [];
  for (const file of files) {
    if (isWithinSizeLimit(file.size, limitBytes)) {
      ok.push(file);
    } else {
      skipped.push({ name: file.name, size: file.size });
    }
  }
  return { ok, skipped };
}

export function partitionConnectorFilesBySize<
  T extends { name?: string; size?: number },
>(files: T[], limitBytes: number): PartitionResult<T> {
  const ok: T[] = [];
  const skipped: SkippedFile[] = [];
  for (const file of files) {
    if (isWithinSizeLimit(file.size, limitBytes)) {
      ok.push(file);
    } else {
      skipped.push({ name: file.name ?? "(unnamed)", size: file.size ?? 0 });
    }
  }
  return { ok, skipped };
}

import { useEffect, useState } from "react";

export function useUploadLimits(): UploadLimits {
  const [limits, setLimits] = useState<UploadLimits>(
    cachedLimits ?? DEFAULT_LIMITS,
  );
  useEffect(() => {
    let cancelled = false;
    fetchUploadLimits().then((l) => {
      if (!cancelled) setLimits(l);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return limits;
}

export function describeSkipped(
  skipped: SkippedFile[],
  limitBytes: number,
): string {
  const limitStr = formatSize(limitBytes);
  const names = skipped
    .slice(0, 3)
    .map((s) => `${s.name} (${formatSize(s.size)})`)
    .join(", ");
  const more = skipped.length > 3 ? ` and ${skipped.length - 3} more` : "";
  return `Exceeds ${limitStr} limit: ${names}${more}`;
}
