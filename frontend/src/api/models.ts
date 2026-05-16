import { invoke } from '@tauri-apps/api/core';

export type ModelReadinessIssueCode =
  | 'no_runnable_model'
  | 'missing_api_key'
  | 'missing_base_url'
  | 'active_model_invalid';

export type ModelReadinessIssue = {
  code: ModelReadinessIssueCode;
  provider?: string;
  missing?: string[];
};

export type ModelReadiness = {
  ready: boolean;
  active_model: string | null;
  issue: ModelReadinessIssue | null;
};

export type ModelRoutingConfig = {
  enabled: boolean;
  classifier_model: string;
  flash_model: string;
  flash_fallback_model?: string;
  default_model: string;
  classifier_threshold: number;
  classifier_timeout_seconds: number;
};

export type LlmProviderMetadata = {
  label: string;
  placeholder_base_url?: string;
  placeholder_model?: string;
  supports_model?: boolean;
};

export type LlmProviderConfig = {
  provider: string;
  api_key: string;
  base_url: string;
  model?: string;
  metadata: LlmProviderMetadata;
};

export const modelsApi = {
  getActiveModel: () => invoke<string | null>('get_active_model'),

  setActiveModel: (model: string) =>
    invoke('set_active_model', { model }),

  getModelReadiness: () =>
    invoke<ModelReadiness>('get_model_readiness'),

  getLlmConfigs: () =>
    invoke<LlmProviderConfig[]>('get_llm_configs'),

  getAvailableModels: () =>
    invoke<Record<string, string[]>>('get_available_models'),

  getModelRouting: () =>
    invoke<ModelRoutingConfig>('get_model_routing'),

  setLlmConfig: (params: {
    provider: string;
    api_key?: string;
    base_url: string;
    model?: string;
  }) => invoke('set_llm_config', params),

  setModelRouting: (params: { enabled: boolean }) =>
    invoke('set_model_routing', params),
};
