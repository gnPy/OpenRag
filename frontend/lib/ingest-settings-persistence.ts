import {
  DEFAULT_INGEST_EMBEDDING_MODEL,
  getIngestChunkSettingsError,
  type IngestSettings,
} from "@/components/cloud-picker/types";

const STORAGE_KEY = "openrag.ingest-settings.v1";

export function getDefaultIngestSettings(): IngestSettings {
  return {
    chunkSize: 1000,
    chunkOverlap: 200,
    ocr: false,
    pictureDescriptions: false,
    embeddingModel: DEFAULT_INGEST_EMBEDDING_MODEL,
  };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function parseStoredIngestSettings(raw: unknown): IngestSettings | null {
  if (!isRecord(raw)) return null;
  const { chunkSize, chunkOverlap, ocr, pictureDescriptions, embeddingModel } =
    raw;
  if (
    typeof chunkSize !== "number" ||
    typeof chunkOverlap !== "number" ||
    typeof ocr !== "boolean" ||
    typeof pictureDescriptions !== "boolean" ||
    typeof embeddingModel !== "string" ||
    !embeddingModel.trim()
  ) {
    return null;
  }
  const candidate: IngestSettings = {
    chunkSize,
    chunkOverlap,
    ocr,
    pictureDescriptions,
    embeddingModel: embeddingModel.trim(),
  };
  if (getIngestChunkSettingsError(candidate)) return null;
  return candidate;
}

export function readPersistedIngestSettings(): IngestSettings | null {
  if (typeof window === "undefined") return null;
  try {
    const parsed: unknown = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || "",
    );
    return parseStoredIngestSettings(parsed);
  } catch {
    return null;
  }
}

export function writePersistedIngestSettings(settings: IngestSettings): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // ignore quota / private mode
  }
}
