import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useGetCurrentProviderModelsQuery } from "../queries/useGetModelsQuery";
import type { Settings } from "../queries/useGetSettingsQuery";

export interface UpdateSettingsRequest {
  // Agent settings
  llm_model?: string;
  llm_provider?: string;
  system_prompt?: string;

  // Knowledge settings
  chunk_size?: number;
  chunk_overlap?: number;
  table_structure?: boolean;
  ocr?: boolean;
  picture_descriptions?: boolean;
  embedding_model?: string;
  embedding_provider?: string;

  // Provider-specific settings (for dialogs)
  model_provider?: string; // Deprecated, kept for backward compatibility
  api_key?: string;
  endpoint?: string;
  project_id?: string;

  // Provider-specific API keys
  openai_api_key?: string;
  anthropic_api_key?: string;
  watsonx_api_key?: string;
  watsonx_endpoint?: string;
  watsonx_project_id?: string;
  ollama_endpoint?: string;
  remove_ollama_config?: boolean;
  remove_openai_config?: boolean;
  remove_anthropic_config?: boolean;
  remove_watsonx_config?: boolean;
}

export interface UpdateSettingsResponse {
  message: string;
  settings?: Settings;
}

function mergeKnowledgeIntoSettingsCache(
  prev: Settings | undefined,
  variables: UpdateSettingsRequest,
): Settings | undefined {
  if (!prev) return prev;
  const v = variables;
  const touched =
    v.chunk_size !== undefined ||
    v.chunk_overlap !== undefined ||
    v.table_structure !== undefined ||
    v.ocr !== undefined ||
    v.picture_descriptions !== undefined ||
    v.embedding_model !== undefined ||
    v.embedding_provider !== undefined;
  if (!touched) return prev;
  const base = prev.knowledge ?? {};
  return {
    ...prev,
    knowledge: {
      ...base,
      ...(v.chunk_size !== undefined ? { chunk_size: v.chunk_size } : {}),
      ...(v.chunk_overlap !== undefined
        ? { chunk_overlap: v.chunk_overlap }
        : {}),
      ...(v.table_structure !== undefined
        ? { table_structure: v.table_structure }
        : {}),
      ...(v.ocr !== undefined ? { ocr: v.ocr } : {}),
      ...(v.picture_descriptions !== undefined
        ? { picture_descriptions: v.picture_descriptions }
        : {}),
      ...(v.embedding_model !== undefined
        ? { embedding_model: v.embedding_model }
        : {}),
      ...(v.embedding_provider !== undefined
        ? { embedding_provider: v.embedding_provider }
        : {}),
    },
  };
}

export const useUpdateSettingsMutation = (
  options?: Omit<
    UseMutationOptions<UpdateSettingsResponse, Error, UpdateSettingsRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();
  const { refetch: refetchModels } = useGetCurrentProviderModelsQuery();

  async function updateSettings(
    variables: UpdateSettingsRequest,
  ): Promise<UpdateSettingsResponse> {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(variables),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to update settings");
    }

    return response.json();
  }

  return useMutation({
    mutationFn: updateSettings,
    onSuccess: async (data, variables, context) => {
      // Merge knowledge fields immediately so ingest / other UIs sync without waiting on refetch.
      queryClient.setQueryData<Settings>(["settings"], (prev) =>
        mergeKnowledgeIntoSettingsCache(prev, variables),
      );
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      refetchModels(); // Refetch models for the settings page
      options?.onSuccess?.(data, variables, context);
    },
    onError: options?.onError,
    onSettled: options?.onSettled,
  });
};
