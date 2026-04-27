import type { KnowledgeSettings } from "@/app/api/queries/useGetSettingsQuery";
import {
  DEFAULT_INGEST_EMBEDDING_MODEL,
  type IngestSettings,
} from "@/components/cloud-picker/types";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";

export function getDefaultIngestSettings(): IngestSettings {
  return knowledgeSettingsToIngestSettings(undefined);
}

/** Map saved knowledge settings (Settings page) to ingest UI shape. */
export function knowledgeSettingsToIngestSettings(
  k: KnowledgeSettings | undefined,
): IngestSettings {
  return {
    chunkSize: k?.chunk_size ?? DEFAULT_KNOWLEDGE_SETTINGS.chunk_size,
    chunkOverlap: k?.chunk_overlap ?? DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap,
    ocr: k?.ocr ?? DEFAULT_KNOWLEDGE_SETTINGS.ocr,
    pictureDescriptions:
      k?.picture_descriptions ??
      DEFAULT_KNOWLEDGE_SETTINGS.picture_descriptions,
    embeddingModel:
      k?.embedding_model?.trim() || DEFAULT_INGEST_EMBEDDING_MODEL,
  };
}
