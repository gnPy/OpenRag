"use client";

import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { IngestSettings } from "@/components/cloud-picker/types";
import { useAuth } from "@/contexts/auth-context";
import {
  getDefaultIngestSettings,
  knowledgeSettingsToIngestSettings,
} from "@/lib/ingest-settings-knowledge";

/**
 * Ingest panel: mirrors saved `/api/settings` knowledge whenever that query loads or reloads
 * (browser refresh, navigation, refetch after Settings save). Nothing is persisted for this page;
 * local tweaks are only for the current run until the next settings load.
 */
export function useSessionIngestSettings(): [
  IngestSettings,
  Dispatch<SetStateAction<IngestSettings>>,
] {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const { data, isSuccess, dataUpdatedAt } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const [ingestSettings, setIngestSettings] = useState<IngestSettings>(
    getDefaultIngestSettings,
  );

  useEffect(() => {
    if (!isSuccess) return;
    setIngestSettings(knowledgeSettingsToIngestSettings(data?.knowledge));
  }, [isSuccess, dataUpdatedAt, data?.knowledge]);

  return [ingestSettings, setIngestSettings];
}
