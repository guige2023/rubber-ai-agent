import React, { useState, useEffect } from 'react';
import { RefreshIconButton } from '../components/RefreshIconButton';
import { modelsApi, type LlmProviderConfig, type ModelRoutingConfig, type ModelReadiness } from '../api/models';
import { systemApi } from '../api/system';
import {
  Cpu, Globe, Key, Save, Gauge, ChevronRight,
} from 'lucide-react';
import { cn } from '../utils/cn';

const buildModelOptionValue = (provider: string, model: string) => `${provider}:${model}`;

type SettingsTab = 'models' | 'logs';

interface ProviderCardProps {
  config: LlmProviderConfig;
  onSave: (apiKey: string | undefined, baseUrl: string, model?: string) => Promise<void>;
  t: (key: string) => string;
}

function ProviderCard({ config, onSave, t }: ProviderCardProps) {
  const [apiKey, setApiKey] = useState(config.api_key || '');
  const [baseUrl, setBaseUrl] = useState(config.base_url || '');
  const [model, setModel] = useState(config.model || '');
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setApiKey(config.api_key || '');
    setBaseUrl(config.base_url || '');
    setModel(config.model || '');
    setApiKeyDirty(false);
    setSaveError(null);
  }, [config]);

  const supportsModel = Boolean(config.metadata.supports_model);
  const apiKeyChanged = apiKeyDirty && apiKey !== (config.api_key || '');
  const baseUrlChanged = baseUrl !== (config.base_url || '');
  const modelChanged = supportsModel && model !== (config.model || '');
  const hasChanges = apiKeyChanged || baseUrlChanged || modelChanged;

  return (
    <div className="glass rounded-[2.5rem] p-6 border border-white/5 space-y-6 relative overflow-hidden group min-h-[280px] flex flex-col">
      <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

      <div className="flex items-center justify-between relative z-10">
        <h3 className="text-lg font-bold tracking-tight">{config.metadata.label}</h3>
        <div className={cn(
          "px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border",
          config.api_key ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
        )}>
          {config.api_key ? t('settings.linked') : t('settings.missing')}
        </div>
      </div>

      <div className="space-y-4 relative z-10">
        {saveError && (
          <div className="rounded-lg border border-red-400/20 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-100">
            {saveError}
          </div>
        )}
        <div className="space-y-2">
          <label className="text-[10px] font-bold text-white/20 uppercase tracking-widest ml-1">{t('settings.api_key')}</label>
          <div className="relative">
            <Key size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20" />
            <input
              type="password"
              value={apiKey}
              onChange={(e) => { setApiKey(e.target.value); setApiKeyDirty(true); }}
              placeholder={t('settings.api_key_placeholder')}
              className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
            />
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-bold text-white/20 uppercase tracking-widest ml-1">{t('settings.base_url')}</label>
          <div className="relative">
            <Globe size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20" />
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => { setBaseUrl(e.target.value); }}
              placeholder={config.metadata.placeholder_base_url}
              className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
            />
          </div>
        </div>

        {supportsModel && (
          <div className="space-y-2">
            <label className="text-[10px] font-bold text-white/20 uppercase tracking-widest ml-1">{t('settings.model')}</label>
            <div className="relative">
              <Cpu size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20" />
              <input
                type="text"
                value={model}
                onChange={(e) => { setModel(e.target.value); }}
                placeholder={config.metadata.placeholder_model || t('settings.model_placeholder')}
                className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
              />
            </div>
          </div>
        )}
      </div>

      <div className="mt-auto pt-4 relative z-10">
        <button
          onClick={async () => {
            setSaveError(null);
            setIsSaving(true);
            try {
              await onSave(apiKeyDirty ? apiKey : undefined, baseUrl, modelChanged ? model : undefined);
              setApiKeyDirty(false);
            } catch (error) {
              setSaveError(error instanceof Error ? error.message : String(error));
            } finally {
              setIsSaving(false);
            }
          }}
          disabled={!hasChanges || isSaving}
          className={cn(
            "w-full py-4 rounded-2xl text-[11px] font-bold uppercase tracking-widest shadow-lg flex items-center justify-center gap-2 group/save transition-all active:scale-[0.98]",
            hasChanges && !isSaving
              ? "bg-white text-[#080808] hover:bg-white/90"
              : "bg-white/5 text-white/20 cursor-not-allowed"
          )}
        >
          <Save size={14} className="group-hover/save:rotate-12 transition-transform" />
          {isSaving ? t('settings.validating') : t('settings.save')}
        </button>
      </div>
    </div>
  );
}

interface SettingsViewProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

export function SettingsView({ call, isConnected, t }: SettingsViewProps) {
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('models');
  const [activeModel, setActiveModel] = useState<string | null>(null);
  const [modelReadiness, setModelReadiness] = useState<ModelReadiness | null>(null);
  const [modelRouting, setModelRouting] = useState<ModelRoutingConfig | null>(null);
  const [llmConfigs, setLlmConfigs] = useState<LlmProviderConfig[]>([]);
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  const [isRefreshingModels, setIsRefreshingModels] = useState(false);
  const [backendLogContent, setBackendLogContent] = useState('');
  const [backendLogSource, setBackendLogSource] = useState<'app' | 'sidecar'>('app');
  const [isRefreshingLogs, setIsRefreshingLogs] = useState(false);
  const logsEndRef = React.useRef<HTMLDivElement>(null);

  const refreshModelSettings = async () => {
    if (!isConnected) return;
    setIsRefreshingModels(true);
    try {
      const [model, readiness, configs, models, routing] = await Promise.all([
        call('get_active_model'),
        call('get_model_readiness'),
        call('get_llm_configs'),
        call('get_available_models'),
        call('get_model_routing'),
      ]);
      setActiveModel((model as string | null) ?? null);
      setModelReadiness(readiness as ModelReadiness);
      setLlmConfigs(configs as LlmProviderConfig[]);
      setAvailableModels(models as Record<string, string[]>);
      setModelRouting(routing as ModelRoutingConfig);
    } catch (error) {
      console.error('Failed to refresh model settings:', error);
    } finally {
      setIsRefreshingModels(false);
    }
  };

  const refreshBackendLogs = async (source: 'app' | 'sidecar' = backendLogSource) => {
    if (!isConnected) return;
    setIsRefreshingLogs(true);
    try {
      const logs = await call('read_backend_logs', { source, lines: 160 });
      setBackendLogContent((logs as { content: string }).content || '');
      setBackendLogSource(source);
    } catch (error) {
      console.error('Failed to load backend logs:', error);
      setBackendLogContent(t('settings.logs_load_failed'));
    } finally {
      setIsRefreshingLogs(false);
    }
  };

  useEffect(() => {
    if (isConnected) {
      if (settingsTab === 'models') {
        refreshModelSettings();
      } else {
        refreshBackendLogs(backendLogSource);
      }
    }
  }, [isConnected, settingsTab]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [backendLogContent]);

  const handleSaveConfig = async (
    provider: string,
    apiKey: string | undefined,
    baseUrl: string,
    model?: string
  ) => {
    const params: Record<string, string> = { provider, base_url: baseUrl };
    if (apiKey !== undefined) params.api_key = apiKey;
    if (model !== undefined) params.model = model;
    const result = await call('set_llm_config', params) as { status?: string; message?: string };
    if (result?.status === 'error') {
      throw new Error(result.message || 'Failed to validate provider configuration.');
    }
    await refreshModelSettings();
  };

  const handleSetActiveModel = async (model: string) => {
    const previousActiveModel = activeModel;
    setActiveModel(model);
    try {
      await call('set_active_model', { model });
    } catch (error) {
      console.error('Failed to set active model:', error);
      setActiveModel(previousActiveModel);
      await refreshModelSettings();
    }
  };

  const handleSetModelRoutingEnabled = async (enabled: boolean) => {
    setModelRouting((current) => current ? { ...current, enabled } : current);
    try {
      const result = await call('set_model_routing', { enabled }) as any;
      if (result?.status === 'error') {
        setModelRouting((current) => current ? { ...current, enabled: !enabled } : current);
        throw new Error(result.message || 'Failed to update model routing.');
      }
      if (result?.config) {
        setModelRouting(result.config as ModelRoutingConfig);
      }
    } catch (error) {
      setModelRouting((current) => current ? { ...current, enabled: !enabled } : current);
      throw error;
    }
  };

  const providerLabels = Object.fromEntries(
    llmConfigs.map((config) => [config.provider, config.metadata?.label || config.provider])
  );
  const availableModelValues = Object.entries(availableModels).flatMap(([provider, models]) =>
    models.map((model) => buildModelOptionValue(provider, model))
  );
  const selectedModelValue = activeModel && availableModelValues.includes(activeModel) ? activeModel : '';
  const shouldWarnModelSelector = modelReadiness?.issue?.code === 'no_runnable_model';
  const shouldHighlightModelSelector = availableModelValues.length > 0 && !selectedModelValue;

  const getModelSelectorPlaceholder = () => {
    if (availableModelValues.length > 0) return t('settings.select_model_placeholder');
    switch (modelReadiness?.issue?.code) {
      case 'missing_base_url': return t('settings.missing_base_url_placeholder');
      default: return t('settings.no_models');
    }
  };

  const getInlineModelHint = () => {
    if (availableModelValues.length > 0) return t('settings.inline_select_model_hint');
    switch (modelReadiness?.issue?.code) {
      case 'missing_base_url': return t('settings.inline_missing_base_url_hint');
      default: return t('settings.inline_model_hint');
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-12 pb-20">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-4xl font-black tracking-tight mb-2">{t('nav.settings')}</h2>
          <p className="text-sm text-white/30 font-medium">{t('settings.subtitle')}</p>
        </div>
        <div className="flex items-center gap-3 rounded-2xl bg-white/5 border border-white/10 p-1">
          <button
            onClick={() => setSettingsTab('models')}
            className={cn(
              'px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
              settingsTab === 'models' ? 'bg-white text-[#080808]' : 'text-white/50 hover:bg-white/10'
            )}
          >
            {t('settings.tabs.models')}
          </button>
          <button
            onClick={() => { setSettingsTab('logs'); refreshBackendLogs(backendLogSource); }}
            className={cn(
              'px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
              settingsTab === 'logs' ? 'bg-white text-[#080808]' : 'text-white/50 hover:bg-white/10'
            )}
          >
            {t('settings.tabs.logs')}
          </button>
        </div>
      </header>

      {settingsTab === 'models' ? (
        <div className="space-y-12">
          {/* Active Model */}
          <section className="flex items-center justify-between glass rounded-3xl p-6 border border-white/10 shadow-xl">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-xl border border-white/10 bg-white/5 flex items-center justify-center shrink-0">
                <Cpu className="text-white/60" size={20} />
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-bold tracking-tight text-white/70">{t('settings.active_model_label')}</span>
                {(!modelReadiness?.ready) && (
                  <p className="max-w-2xl text-xs font-medium leading-5 text-white/48">{getInlineModelHint()}</p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="relative">
                {(shouldWarnModelSelector || shouldHighlightModelSelector) && (
                  <span
                    className={cn(
                      "pointer-events-none absolute left-3.5 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full",
                      shouldWarnModelSelector
                        ? "bg-amber-300 shadow-[0_0_0_4px_rgba(252,211,77,0.08)]"
                        : "bg-sky-300 shadow-[0_0_0_4px_rgba(125,211,252,0.08)]"
                    )}
                  />
                )}
                <select
                  value={selectedModelValue}
                  onChange={(e) => handleSetActiveModel(e.target.value)}
                  className={cn(
                    "min-w-[18rem] rounded-xl py-2.5 pr-4 text-xs font-bold outline-none transition-all cursor-pointer ring-1 appearance-none",
                    shouldWarnModelSelector
                      ? "pl-8 border border-amber-300/55 bg-black/40 text-amber-50 ring-amber-300/20"
                      : shouldHighlightModelSelector
                        ? "pl-8 border border-sky-200/35 bg-sky-300/[0.08] text-white ring-sky-300/15"
                        : "pl-4 border border-white/10 bg-white/5 ring-white/5 hover:bg-white/10"
                  )}
                >
                  <option value="" disabled>{getModelSelectorPlaceholder()}</option>
                  {Object.entries(availableModels).map(([provider, models]) => (
                    <optgroup key={provider} label={providerLabels[provider] || provider.toUpperCase()}>
                      {models.map(m => (
                        <option key={buildModelOptionValue(provider, m)} value={buildModelOptionValue(provider, m)}>
                          {m}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            </div>
          </section>

          {/* Model Routing */}
          <section className="flex items-center justify-between gap-6 glass rounded-3xl p-6 border border-white/10 shadow-xl">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-xl border border-white/10 bg-white/5 flex items-center justify-center shrink-0">
                <Gauge className="text-white/60" size={20} />
              </div>
              <div className="space-y-1.5">
                <span className="text-sm font-bold tracking-tight text-white/70">{t('settings.model_routing_title')}</span>
                <p className="max-w-2xl text-xs font-medium leading-5 text-white/40">{t('settings.model_routing_subtitle')}</p>
                <p className={cn(
                  "min-h-5 text-[11px] font-semibold leading-5 transition-opacity",
                  modelRouting?.enabled ? "text-white/30 opacity-100" : "text-white/20 opacity-0"
                )}>
                  {modelRouting
                    ? t('settings.model_routing_detail').replace('{classifier}', modelRouting.classifier_model).replace('{flash}', modelRouting.flash_model)
                    : t('settings.model_routing_detail').replace('{classifier}', 'gemini:gemini-3.1-flash-lite-preview').replace('{flash}', 'gemini:gemini-3-flash-preview')
                  }
                </p>
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={modelRouting?.enabled ?? false}
              onClick={() => handleSetModelRoutingEnabled(!(modelRouting?.enabled ?? false)).catch(console.error)}
              disabled={!isConnected || isRefreshingModels}
              className={cn(
                "relative h-7 w-12 shrink-0 rounded-full border transition-colors",
                modelRouting?.enabled ? "border-emerald-300/40 bg-emerald-300/30" : "border-white/10 bg-white/10",
                (!isConnected || isRefreshingModels) && "cursor-not-allowed opacity-50"
              )}
            >
              <span className={cn(
                "absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-lg transition-transform",
                modelRouting?.enabled && "translate-x-5"
              )} />
            </button>
          </section>

          {/* Providers */}
          <section className="space-y-6">
            <header className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-2xl font-bold tracking-tight mb-2">{t('settings.providers_title')}</h2>
                <p className="text-sm text-white/30 font-medium">{t('settings.providers_subtitle')}</p>
              </div>
              <RefreshIconButton
                onClick={() => refreshModelSettings()}
                disabled={!isConnected || isRefreshingModels}
                isLoading={isRefreshingModels}
                label={t('settings.models_refresh')}
              />
            </header>

            <div className="grid grid-cols-1 gap-6">
              {llmConfigs.map(config => (
                <ProviderCard
                  key={config.provider}
                  config={config}
                  t={t}
                  onSave={(apiKey, baseUrl, model) => handleSaveConfig(config.provider, apiKey, baseUrl, model)}
                />
              ))}
            </div>
          </section>
        </div>
      ) : (
        <section className="space-y-6">
          <header className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-2xl font-bold tracking-tight mb-2">{t('settings.logs_title')}</h2>
              <p className="text-sm text-white/30 font-medium">{t('settings.logs_subtitle')}</p>
            </div>
            <RefreshIconButton
              onClick={() => refreshBackendLogs(backendLogSource)}
              isLoading={isRefreshingLogs}
              label={t('settings.logs_refresh')}
            />
          </header>

          <div className="glass rounded-3xl p-6 border border-white/10 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <button
                onClick={() => refreshBackendLogs('app')}
                className={cn(
                  'px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
                  backendLogSource === 'app' ? 'bg-white text-[#080808]' : 'bg-white/5 text-white/50 hover:bg-white/10'
                )}
              >
                {t('settings.logs_app_tab')}
              </button>
              <button
                onClick={() => refreshBackendLogs('sidecar')}
                className={cn(
                  'px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
                  backendLogSource === 'sidecar' ? 'bg-white text-[#080808]' : 'bg-white/5 text-white/50 hover:bg-white/10'
                )}
              >
                {t('settings.logs_sidecar_tab')}
              </button>
            </div>

            <pre className="min-h-[280px] max-h-[420px] overflow-auto rounded-2xl bg-black/30 border border-white/5 p-4 text-xs leading-6 text-white/75 whitespace-pre-wrap break-words">
              {backendLogContent || t('settings.logs_empty')}
              <div ref={logsEndRef} />
            </pre>
          </div>
        </section>
      )}
    </div>
  );
}
