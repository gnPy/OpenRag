"use client";

import type { Dispatch, SetStateAction } from "react";
import { useEffect } from "react";
import {
  useGetIBMModelsQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ModelProvider } from "@/app/settings/_helpers/model-helpers";
import {
  DEFAULT_INGEST_EMBEDDING_MODEL,
  type IngestSettings,
} from "@/components/cloud-picker/types";
import { useAuth } from "@/contexts/auth-context";

/**
 * Syncs ingest `embeddingModel` from app settings (`useGetSettingsQuery`): `knowledge.embedding_model`
 * when set, otherwise the provider list default while state is still the initial placeholder.
 */
export function useIngestEmbeddingFromSettings(
  setIngestSettings: Dispatch<SetStateAction<IngestSettings>>,
): void {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const { data: apiSettings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const currentProvider = (apiSettings.knowledge?.embedding_provider ||
    "openai") as ModelProvider;

  const { data: openaiModelsData } = useGetOpenAIModelsQuery(undefined, {
    enabled: (isAuthenticated || isNoAuthMode) && currentProvider === "openai",
  });
  const { data: ollamaModelsData } = useGetOllamaModelsQuery(undefined, {
    enabled: (isAuthenticated || isNoAuthMode) && currentProvider === "ollama",
  });
  const { data: ibmModelsData } = useGetIBMModelsQuery(undefined, {
    enabled: (isAuthenticated || isNoAuthMode) && currentProvider === "watsonx",
  });

  const modelsData =
    currentProvider === "openai"
      ? openaiModelsData
      : currentProvider === "ollama"
        ? ollamaModelsData
        : currentProvider === "watsonx"
          ? ibmModelsData
          : openaiModelsData;

  useEffect(() => {
    const explicit = apiSettings.knowledge?.embedding_model?.trim();
    if (explicit) {
      setIngestSettings((prev) => {
        if (prev.embeddingModel === explicit) return prev;
        // Do not override a restored or user-chosen model (only seed from settings
        // while still on the initial placeholder).
        if (prev.embeddingModel !== DEFAULT_INGEST_EMBEDDING_MODEL) return prev;
        return { ...prev, embeddingModel: explicit };
      });
      return;
    }

    const fromList = modelsData?.embedding_models?.find(
      (m) => m.default,
    )?.value;
    if (!fromList) return;

    setIngestSettings((prev) => {
      if (prev.embeddingModel === fromList) return prev;
      if (prev.embeddingModel !== DEFAULT_INGEST_EMBEDDING_MODEL) return prev;
      return { ...prev, embeddingModel: fromList };
    });
  }, [apiSettings.knowledge?.embedding_model, modelsData, setIngestSettings]);
}
