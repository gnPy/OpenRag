"use client";

import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import type { IngestSettings } from "@/components/cloud-picker/types";
import {
  getDefaultIngestSettings,
  readPersistedIngestSettings,
  writePersistedIngestSettings,
} from "@/lib/ingest-settings-persistence";

/**
 * Ingest panel state persisted in localStorage so choices survive refresh.
 */
export function usePersistedIngestSettings(): [
  IngestSettings,
  Dispatch<SetStateAction<IngestSettings>>,
] {
  const [ingestSettings, setIngestSettings] = useState<IngestSettings>(() => {
    return readPersistedIngestSettings() ?? getDefaultIngestSettings();
  });

  useEffect(() => {
    writePersistedIngestSettings(ingestSettings);
  }, [ingestSettings]);

  return [ingestSettings, setIngestSettings];
}
