import React, { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Send, RefreshCw, Copy, Check, X, ChevronDown, ChevronRight,
  ExternalLink, Search, Slash, BarChart3, Globe, Cpu, Gauge, Plus, Trash2
} from 'lucide-react';
import { cn } from '../utils/cn';
import { Markdown } from '../components/Markdown';
import { InlineToolPreview } from '../components/InlineToolPreview';
import { SessionInsightsDrawer } from '../components/SessionInsightsDrawer';
import { CommandPalette } from '../components/CommandPalette';
import { SessionSearch } from '../components/SessionSearch';
import type { Message } from '../hooks/useSessions';
import type { ToolActivityPayload } from '../hooks/useBackendConnection';

const CHAT_RAIL_CLASS = 'mx-auto w-full max-w-[72rem]';

function pad2(v: number) { return String(v).padStart(2, '0'); }

function formatMessageTimestamp(createdAt?: string) {
  if (!createdAt) return '';
  const d = new Date(createdAt);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const isToday = d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  const time = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  return isToday ? time : `${d.getFullYear()}/${pad2(d.getMonth()+1)}/${pad2(d.getDate())} ${time}`;
}

function formatTokenCount(v?: number | null) {
  return Math.max(0, Number(v || 0)).toLocaleString();
}

function formatUsdCost(v?: number | null) {
  const a = Math.max(0, Number(v || 0));
  if (a === 0) return '$0.00';
  if (a < 0.01) return `$${a.toFixed(6)}`;
  return `$${a.toFixed(4)}`;
}

function getHttpUrl(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  try {
    const u = new URL(v);
    return u.protocol === 'http:' || u.protocol === 'https:' ? v : null;
  } catch { return null; }
}

function getToolActivityDisplayName(toolName: string, t: (k: string) => string) {
  const translated = t(`tools.${toolName}`);
  return translated !== `tools.${toolName}` ? translated : toolName;
}

function buildToolActivityCopyLine(activity: ToolActivityPayload, t: (k: string) => string) {
  const segs: string[] = [getToolActivityDisplayName(activity.tool_name, t)];
  const i = activity.input;
  if (i?.url) segs.push(String(i.url));
  if (i?.skill_name) segs.push(`[${String(i.skill_name)}]`);
  if (i?.command) segs.push(String(i.command));
  if (i?.path) segs.push(String(i.path));
  if (i?.title) segs.push(`"${String(i.title)}"`);
  if (activity.duration_ms !== undefined) segs.push(`${activity.duration_ms}ms`);
  if (activity.output) segs.push(activity.output);
  return segs.join(' ');
}

function getToolActivityKey(activity: ToolActivityPayload, idx: number) {
  return activity.event_id || `${activity.run_id}-${activity.tool_name}-${idx}`;
}

function isAssistantPending(msg: Message): boolean {
  return msg.role === 'assistant' && msg.metadata?.run?.status === 'pending';
}

function getMessageToolActivities(msg: Message, toolActivities: ToolActivityPayload[]) {
  const runId = msg.metadata?.run?.id;
  if (!isAssistantPending(msg) || !runId) return [];
  return toolActivities.filter((a) => a.run_id === runId);
}

function getMessageCopyText(msg: Message, toolActivities: ToolActivityPayload[], t: (k: string) => string) {
  if (!isAssistantPending(msg)) return msg.content.trim();
  const lines = toolActivities.map((a) => buildToolActivityCopyLine(a, t));
  return [msg.content.trim(), ...lines].filter(Boolean).join('\n').trim();
}

function getSortedRequestModelUsage(modelUsage: any) {
  return Object.entries(modelUsage.request?.by_model || {}).sort(
    ([, l]: [string, any], [, r]: [string, any]) => ((r.total_tokens || 0) - (l.total_tokens || 0))
  );
}

interface ChatViewProps {
  // Session state from App
  messages: Message[];
  sessions: any[];
  currentSessionId: string | null;
  currentUsage: { input_tokens: number; output_tokens: number; total_tokens: number };
  isSubmitting: boolean;
  isExecuting: boolean;
  hasOlderMessages: boolean;
  isLoadingOlderMessages: boolean;
  isConnected: boolean;
  toolActivities: ToolActivityPayload[];
  modelReadiness: any;
  availableModels: Record<string, string[]>;
  // Actions
  execute: (content: string) => Promise<any>;
  stopActiveRun: () => void;
  switchSession: (id: string) => void;
  createNewSession: () => Promise<any>;
  deleteSession: (id: string) => void;
  renameSession: (id: string, title: string) => Promise<any>;
  loadOlderMessages: () => Promise<boolean>;
  refreshSessions: () => void;
  call: (method: string, params?: any) => Promise<any>;
  // i18n
  t: (key: string) => string;
  locale: string;
  changeLanguage: (lang: 'en' | 'zh') => void;
}

export function ChatView({
  messages, sessions, currentSessionId, currentUsage,
  isSubmitting, isExecuting, hasOlderMessages, isLoadingOlderMessages,
  isConnected, toolActivities, modelReadiness, availableModels,
  execute, stopActiveRun, switchSession, createNewSession, deleteSession,
  renameSession, loadOlderMessages, refreshSessions, call, t, locale, changeLanguage,
}: ChatViewProps) {
  const [input, setInput] = useState('');
  const [sendMode, setSendMode] = useState<'mod_enter' | 'enter'>(() =>
    localStorage.getItem('rabaiagent_send_mode') === 'enter' ? 'enter' : 'mod_enter'
  );
  const [isSendMenuOpen, setIsSendMenuOpen] = useState(false);
  const [composerNotice, setComposerNotice] = useState<string | null>(null);
  const [isInsightsOpen, setIsInsightsOpen] = useState(false);
  const [expandedToolActivityKeys, setExpandedToolActivityKeys] = useState<Set<string>>(() => new Set());
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);
  const [openModelUsageKey, setOpenModelUsageKey] = useState<string | null>(null);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState('');
  const [activeModel, setActiveModel] = useState<string | null>(null);

  const chatScrollRef = useRef<HTMLDivElement>(null);
  const chatContentRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sessionTitleInputRef = useRef<HTMLInputElement>(null);
  const isSavingSessionTitleRef = useRef(false);
  const pendingHistoryScrollOffsetRef = useRef<number | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const autoScrollSessionRef = useRef(currentSessionId);
  const copyResetTimerRef = useRef<number | null>(null);
  const didApplyInitialModelRouteRef = useRef(false);

  const sendShortcutHint = sendMode === 'enter'
    ? t('chat.send_shortcut_enter_hint')
    : t('chat.send_shortcut_mod_enter_hint');

  const isModelReady = modelReadiness?.ready ?? true;

  const buildModelOptionValue = (provider: string, model: string) => `${provider}:${model}`;
  const providerLabels = Object.fromEntries(
    Object.entries(availableModels).map(([p]) => [p, p])
  );
  const availableModelValues = Object.entries(availableModels).flatMap(([p, ms]) =>
    ms.map((m) => buildModelOptionValue(p, m))
  );
  const selectedModelValue = activeModel && availableModelValues.includes(activeModel) ? activeModel : '';

  // Load active model on mount
  useEffect(() => {
    if (isConnected) {
      call('get_active_model').then((m: any) => setActiveModel(m ?? null)).catch(() => {});
    }
  }, [isConnected]);

  // Set initial model route
  useEffect(() => {
    if (!didApplyInitialModelRouteRef.current && modelReadiness && !modelReadiness.ready) {
      didApplyInitialModelRouteRef.current = true;
    }
  }, [modelReadiness]);

  // Auto-save send mode
  useEffect(() => { localStorage.setItem('rabaiagent_send_mode', sendMode); }, [sendMode]);

  // Composer notice timeout
  useEffect(() => {
    if (!composerNotice) return;
    const id = window.setTimeout(() => setComposerNotice(null), 3200);
    return () => window.clearTimeout(id);
  }, [composerNotice]);

  // Cleanup copy timer
  useEffect(() => () => {
    if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    const ta = inputRef.current;
    if (!ta) return;
    ta.style.height = '0px';
    ta.style.height = `${Math.min(Math.max(ta.scrollHeight, 72), 220)}px`;
  }, [input]);

  // Scroll to bottom on new messages
  const scrollChatToBottom = useCallback(() => {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: 'auto' });
    messagesEndRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
    shouldStickToBottomRef.current = true;
  }, []);

  useLayoutEffect(() => {
    const sc = chatScrollRef.current;
    const pending = pendingHistoryScrollOffsetRef.current;
    if (sc && pending !== null) {
      sc.scrollTop = sc.scrollHeight - pending;
      pendingHistoryScrollOffsetRef.current = null;
      return;
    }
    const changed = autoScrollSessionRef.current !== currentSessionId;
    if (changed) {
      autoScrollSessionRef.current = currentSessionId;
      shouldStickToBottomRef.current = true;
    }
    if (!changed && !shouldStickToBottomRef.current) return;
    scrollChatToBottom();
    const frameId = requestAnimationFrame(scrollChatToBottom);
    return () => cancelAnimationFrame(frameId);
  }, [currentSessionId, messages, toolActivities, scrollChatToBottom]);

  // Resize observer
  useEffect(() => {
    const target = chatContentRef.current || chatScrollRef.current;
    if (!target || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (pendingHistoryScrollOffsetRef.current === null && shouldStickToBottomRef.current) {
        scrollChatToBottom();
      }
    });
    ro.observe(target);
    return () => ro.disconnect();
  }, [scrollChatToBottom]);

  const handleChatScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const sc = e.currentTarget;
    const distToBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight;
    shouldStickToBottomRef.current = distToBottom < 120;
    if (sc.scrollTop > 80 || !hasOlderMessages || isLoadingOlderMessages || !loadOlderMessages) return;
    pendingHistoryScrollOffsetRef.current = sc.scrollHeight - sc.scrollTop;
    loadOlderMessages().then((loaded) => {
      if (!loaded) pendingHistoryScrollOffsetRef.current = null;
    });
  }, [hasOlderMessages, isLoadingOlderMessages, loadOlderMessages]);

  const toggleToolActivityOutput = useCallback((key: string) => {
    setExpandedToolActivityKeys((cur) => {
      const next = new Set(cur);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }, []);

  const handleSend = async () => {
    if (isExecuting) { stopActiveRun(); return; }
    if (!isModelReady || !input.trim()) return;
    const submitted = input;
    const result = await execute(submitted);
    if (result.status === 'started') {
      setComposerNotice(null);
      setInput((cur) => cur === submitted ? '' : cur);
      return;
    }
    if (result.message) setComposerNotice(result.message);
  };

  const handleCopyMessage = useCallback(async (key: string, text: string) => {
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageKey(key);
      if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = window.setTimeout(() => setCopiedMessageKey(null), 1600);
    } catch {}
  }, []);

  const handleCopyModelUsage = useCallback(async (usage: any) => {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(JSON.stringify(usage, null, 2));
  }, []);

  const handleOpenExternalUrl = useCallback(async (url: string) => {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    try { await openUrl(url); } catch { window.open(url, '_blank', 'noopener,noreferrer'); }
  }, []);

  const handleSetActiveModel = useCallback(async (model: string) => {
    const prev = activeModel;
    setActiveModel(model);
    try { await call('set_active_model', { model }); } catch {
      setActiveModel(prev);
      call('get_active_model').then((m: any) => setActiveModel(m ?? null)).catch(() => {});
    }
  }, [activeModel, call]);

  // Session rename
  const startRenamingSession = useCallback((id: string, title: string) => {
    isSavingSessionTitleRef.current = false;
    setEditingSessionId(id);
    setEditingSessionTitle(title);
  }, []);

  const cancelRenamingSession = useCallback(() => {
    isSavingSessionTitleRef.current = false;
    setEditingSessionId(null);
    setEditingSessionTitle('');
  }, []);

  const saveRenamingSession = useCallback(async () => {
    const id = editingSessionId;
    if (!id || isSavingSessionTitleRef.current) return;
    isSavingSessionTitleRef.current = true;
    const title = editingSessionTitle.trim();
    setEditingSessionId(null);
    setEditingSessionTitle('');
    try { await renameSession(id, title); } catch { await refreshSessions(); } finally { isSavingSessionTitleRef.current = false; }
  }, [editingSessionId, editingSessionTitle, renameSession, refreshSessions]);

  useEffect(() => {
    if (!editingSessionId) return;
    requestAnimationFrame(() => { sessionTitleInputRef.current?.focus(); sessionTitleInputRef.current?.select(); });
  }, [editingSessionId]);

  const CHROME_DOWNLOAD_URL = 'https://www.google.com/chrome/';
  const [browserRuntimeStatus, setBrowserRuntimeStatus] = useState<any>(null);

  useEffect(() => {
    if (isConnected) {
      call('get_browser_runtime_status')
        .then((s: any) => setBrowserRuntimeStatus(s))
        .catch(() => setBrowserRuntimeStatus(null));
    }
  }, [isConnected, call]);

  const handleOpenChromeDownload = async () => {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    try { await openUrl(CHROME_DOWNLOAD_URL); } catch { window.open(CHROME_DOWNLOAD_URL, '_blank'); }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex-1 flex flex-col overflow-hidden"
    >
      {/* Browser runtime banner */}
      {browserRuntimeStatus && !browserRuntimeStatus.available && (
        <div className="mx-10 mt-6 rounded-[1.5rem] border border-amber-300/20 bg-amber-400/[0.08] p-4 backdrop-blur-xl">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-amber-300/20 bg-amber-300/10 text-amber-100">
                <Globe size={18} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-black tracking-tight text-amber-50">{t('browser.chrome_required.title')}</p>
                <p className="max-w-3xl text-xs font-medium leading-5 text-white/65">{t('browser.chrome_required.description')}</p>
              </div>
            </div>
            <button
              onClick={handleOpenChromeDownload}
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-2xl bg-white px-4 py-2.5 text-[10px] font-black uppercase tracking-[0.18em] text-[#080808] transition-all hover:bg-white/90 active:scale-[0.98]"
            >
              {t('browser.chrome_required.download')} <ExternalLink size={13} />
            </button>
          </div>
        </div>
      )}

      {/* Chat scroll area */}
      <div
        ref={chatScrollRef}
        onScroll={handleChatScroll}
        className="flex-1 overflow-y-auto p-8 space-y-8 flex flex-col scrollbar-hide"
      >
        {messages.length === 0 ? (
          <div className="flex-1 flex items-center justify-center pb-10">
            <div className={CHAT_RAIL_CLASS}>
              {isModelReady ? (
                <EmptyState t={t} setInput={setInput} />
              ) : (
                <ModelSetupGuide t={t} issue={modelReadiness?.issue} onOpenSettings={() => {}} />
              )}
            </div>
          </div>
        ) : (
          <div ref={chatContentRef} className={cn(CHAT_RAIL_CLASS, "flex flex-col gap-8")}>
            {messages.map((msg, i) => {
              const key = msg.id || `${msg.role}-${i}`;
              const toolActs = getMessageToolActivities(msg, toolActivities);
              const copyText = getMessageCopyText(msg, toolActs, t);
              const isCopied = copiedMessageKey === key;
              const ts = formatMessageTimestamp(msg.created_at);
              const userRunStatus = msg.role === 'user' && msg.metadata?.run?.status === 'canceled'
                ? t('chat.status_canceled') : null;
              const modelUsage = msg.role === 'assistant' ? msg.metadata?.usage : undefined;
              const modelCost = msg.role === 'assistant' ? msg.metadata?.cost : undefined;
              const isUsageOpen = openModelUsageKey === key;
              // Only show detailed usage panel for MessageModelUsage (which has .request)
              const isDetailedUsage = modelUsage && 'request' in modelUsage;
              const requestRows = isDetailedUsage ? getSortedRequestModelUsage(modelUsage) : [];
              const missingPricing = Array.isArray(modelCost?.missing_pricing)
                ? modelCost.missing_pricing.filter((m: string) => Boolean(m)) : [];

              const bubbleClass = cn(
                "relative rounded-[1.5rem] shadow-lg",
                msg.role === 'user'
                  ? "bg-white text-[#080808] font-bold shadow-sm px-6 py-4 text-[14px]"
                  : msg.metadata?.run?.status === 'failed'
                    ? "bg-red-500/10 border border-red-500/30 text-red-100 backdrop-blur-md px-8 py-7 text-[15px] leading-loose"
                    : "bg-transparent border border-white/10 text-white/90 backdrop-blur-md px-8 py-7 text-[15px] leading-loose"
              );
              const metaBarClass = cn(
                "absolute bottom-0 flex items-center gap-2 px-1 py-1 text-[12px] font-medium opacity-0 translate-y-1 transition-all duration-200 group-hover/message:translate-y-0 group-hover/message:opacity-100 group-focus-within/message:translate-y-0 group-focus-within/message:opacity-100",
                msg.role === 'user' ? "right-1 text-white/65" : "left-1 text-white/55"
              );

              return (
                <motion.div
                  key={key}
                  initial={{ opacity: 0, x: msg.role === 'user' ? 20 : -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={cn(
                    "group/message relative min-w-0 max-w-[85%] pb-11",
                    msg.role === 'user' ? "ml-auto" : "mr-auto"
                  )}
                >
                  <div className={bubbleClass}>
                    {isAssistantPending(msg) ? (
                      <div className="space-y-4">
                        <ThinkingIndicator />
                        {toolActs.map((activity, idx) => {
                          const actKey = getToolActivityKey(activity, idx);
                          const actUrl = getHttpUrl(activity.input?.url);
                          const canExpand = Boolean(activity.output && (activity.phase === 'complete' || activity.phase === 'error'));
                          const isExpanded = expandedToolActivityKeys.has(actKey);

                          return (
                            <div key={actKey} className="rounded-xl bg-white/5 text-[12px] font-mono text-white/50">
                              <div
                                role={canExpand ? 'button' : undefined}
                                tabIndex={canExpand ? 0 : undefined}
                                onClick={canExpand ? () => toggleToolActivityOutput(actKey) : undefined}
                                onKeyDown={canExpand ? (e) => { if (e.key === 'Enter' || e.key === ' ') toggleToolActivityOutput(actKey); } : undefined}
                                className={cn(
                                  "flex items-center gap-2 px-4 py-2",
                                  canExpand && "cursor-pointer transition-colors hover:bg-white/[0.04]"
                                )}
                              >
                                {activity.phase === 'start' || activity.phase === 'running'
                                  ? <RefreshCw size={12} className="animate-spin text-white/40 shrink-0" />
                                  : activity.phase === 'error'
                                    ? <X size={12} className="text-red-400 shrink-0" />
                                    : <Check size={12} className="text-green-400 shrink-0" />
                                }
                                <span className="flex min-w-0 flex-1 items-center gap-2 truncate">
                                  <span className="shrink-0">{getToolActivityDisplayName(activity.tool_name, t)}</span>
                                  {actUrl ? (
                                    <button
                                      type="button"
                                      onClick={(e) => { e.stopPropagation(); handleOpenExternalUrl(actUrl); }}
                                      className="inline-flex min-w-0 items-center gap-1 truncate text-left font-normal text-sky-300/75 transition-colors hover:text-sky-200"
                                    >
                                      <span className="truncate">{actUrl}</span>
                                      <ExternalLink size={11} />
                                    </button>
                                  ) : null}
                                  {activity.input?.skill_name && <span className="truncate font-bold text-blue-400">[{activity.input.skill_name}]</span>}
                                  {activity.input?.command && <span className="truncate font-normal text-orange-400">{activity.input.command}</span>}
                                  {activity.input?.path && (
                                    <span className="truncate font-normal text-green-400">{activity.input.path}</span>
                                  )}
                                  {activity.input?.title && <span className="truncate text-white/40 italic">"{activity.input.title}"</span>}
                                </span>
                                {activity.duration_ms !== undefined && <span className="text-white/20 shrink-0">{activity.duration_ms}ms</span>}
                                {canExpand && (isExpanded ? <ChevronDown size={13} className="shrink-0 text-white/30" /> : <ChevronRight size={13} className="shrink-0 text-white/30" />)}
                              </div>
                              {canExpand && isExpanded && (
                                <div className="border-t border-white/5 px-4 pb-3 pt-2">
                                  <div className="mb-1 text-[11px] font-medium text-white/35">
                                    {activity.phase === 'error' ? t('chat.tool_output_error') : t('chat.tool_output_result')}
                                  </div>
                                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black/20 p-2 text-[11px] leading-relaxed text-white/65">
                                    {activity.output}
                                  </pre>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <Markdown content={msg.content} />
                    )}
                  </div>

                  {userRunStatus ? (
                    <div className="mt-2 flex justify-end px-1">
                      <span className="inline-flex items-center rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-white/60">
                        {userRunStatus}
                      </span>
                    </div>
                  ) : null}

                  {(copyText || modelUsage || ts) ? (
                    <div className={metaBarClass}>
                      {copyText ? (
                        <button
                          type="button"
                          onClick={() => handleCopyMessage(key, copyText)}
                          className={cn(
                            "flex h-5 w-5 items-center justify-center transition-colors",
                            msg.role === 'user' ? "text-white/58 hover:text-white/82" : "text-white/48 hover:text-white"
                          )}
                        >
                          {isCopied ? <Check size={14} strokeWidth={2.4} /> : <Copy size={14} strokeWidth={2.2} />}
                        </button>
                      ) : null}
                      {modelUsage ? (
                        <button
                          type="button"
                          onClick={() => setOpenModelUsageKey((cur) => cur === key ? null : key)}
                          className="flex h-5 w-5 items-center justify-center text-white/48 transition-colors hover:text-white"
                        >
                          <Gauge size={14} strokeWidth={2.2} />
                        </button>
                      ) : null}
                      {ts ? <span className="tabular-nums tracking-[0.01em]">{ts}</span> : null}
                    </div>
                  ) : null}

                  {modelUsage && isDetailedUsage && isUsageOpen ? (
                    <div className="absolute bottom-9 left-1 z-20 w-[min(28rem,calc(100vw-3rem))] rounded-2xl border border-white/10 bg-[#101010]/95 p-4 text-left shadow-2xl backdrop-blur-xl">
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[12px] font-black uppercase text-white/45">{t('chat.model_usage')}</div>
                          <div className="mt-1 text-xl font-black leading-none text-white">
                            {formatTokenCount(modelUsage.request?.total?.total_tokens)} tokens
                          </div>
                          <div className="mt-1 text-[12px] font-medium text-white/45">
                            {t('tasks.input_tokens')} {formatTokenCount(modelUsage.request?.total?.input_tokens)}
                            <span className="mx-1 text-white/20">·</span>
                            {t('tasks.output_tokens')} {formatTokenCount(modelUsage.request?.total?.output_tokens)}
                          </div>
                          {modelCost?.total ? (
                            <>
                              <div className="mt-2 text-[12px] font-bold text-emerald-300/85">
                                {formatUsdCost(modelCost.total.total_cost)}
                              </div>
                              {modelCost.complete === false ? (
                                <div className="mt-1 max-w-[22rem] text-[11px] font-medium leading-snug text-amber-200/75">
                                  {t('chat.model_cost_incomplete')}
                                  {missingPricing.length > 0 && (
                                    <span className="ml-1 text-white/38" title={missingPricing.join(', ')}>
                                      {t('chat.model_cost_missing_pricing')}: {missingPricing.join(', ')}
                                    </span>
                                  )}
                                </div>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          onClick={() => handleCopyModelUsage(modelUsage)}
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-white/45 transition-colors hover:text-white"
                        >
                          <Copy size={13} />
                        </button>
                      </div>
                      <div className="space-y-2">
                        {requestRows.map(([modelId, usage]: [string, any]) => (
                          <div key={modelId} className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
                            <div className="truncate text-[12px] font-bold text-white/82">{modelId}</div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-medium text-white/42">
                              <span>{formatTokenCount(usage.total_tokens)} tokens</span>
                              <span>{usage.request_count || 0} requests</span>
                              <span>In: {formatTokenCount(usage.input_tokens)}</span>
                              <span>Out: {formatTokenCount(usage.output_tokens)}</span>
                              {modelCost?.request?.by_model?.[modelId]?.total_cost != null && (
                                <span className="text-emerald-300/75">{formatUsdCost(modelCost.request.by_model[modelId].total_cost)}</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                      {isDetailedUsage && modelUsage.classifier && modelUsage.classifier.request_count > 0 && (
                        <div className="mt-3 border-t border-white/10 pt-3">
                          <div className="mb-2 text-[11px] font-black uppercase text-white/35">{t('chat.model_usage_classifier')}</div>
                          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
                            <div className="truncate text-[12px] font-bold text-white/75">{modelUsage.classifier.model || t('chat.unknown_model')}</div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-medium text-white/42">
                              <span>{formatTokenCount(modelUsage.classifier.total_tokens)} tokens</span>
                              <span>{modelUsage.classifier.request_count} requests</span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : null}
                </motion.div>
              );
            })}
          </div>
        )}
        <div ref={messagesEndRef} />

        {toolActivities.length > 0 && currentSessionId && (
          <div className="px-8 py-4">
            <InlineToolPreview toolActivities={toolActivities} sessionId={currentSessionId} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="px-8 pb-8 pt-0">
        {isModelReady ? (
          <div className={cn(CHAT_RAIL_CLASS, "relative z-20 bg-white/[0.025] backdrop-blur-xl rounded-xl p-1 shadow-2xl group border border-white/10 focus-within:border-white/25 transition-colors")}>
            <div className="flex items-center gap-3 p-2">
              <button
                type="button"
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-white/35 transition-colors hover:border-white/20 hover:bg-white/[0.06] hover:text-white/55"
                title="Commands (Ctrl+K)"
              >
                <Slash size={16} />
              </button>
              <button
                type="button"
                onClick={() => setIsSearchOpen(true)}
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-white/35 transition-colors hover:border-white/20 hover:bg-white/[0.06] hover:text-white/55"
                title="Search (Ctrl+Shift+F)"
              >
                <Search size={16} />
              </button>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => { setInput(e.target.value); if (composerNotice) setComposerNotice(null); }}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
                  if (sendMode === 'enter' && !e.shiftKey) { e.preventDefault(); handleSend(); return; }
                  if (sendMode === 'mod_enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleSend(); }
                }}
                placeholder={t('chat.placeholder')}
                className="flex-1 bg-transparent border-none outline-none px-4 py-4 text-[15px] placeholder:text-white/20 font-medium tracking-tight text-white/90 min-h-[72px] max-h-[220px] resize-none overflow-y-auto"
                rows={1}
              />
              <div className="relative flex flex-shrink-0 items-center pr-1">
                <div className={cn(
                  "flex rounded-lg border transition-all",
                  isExecuting
                    ? "border-white/18 bg-white/[0.08] text-white shadow-[0_14px_34px_rgba(255,255,255,0.08)]"
                    : input.trim()
                      ? "border-white bg-white text-[#080808] shadow-md"
                      : "border-white/10 bg-white/[0.03] text-white/35"
                )}>
                  <button
                    onClick={handleSend}
                    disabled={isSubmitting || (!isExecuting && !input.trim())}
                    className={cn(
                      "group relative h-10 w-10 flex items-center justify-center rounded-l-lg transition-colors active:scale-95 disabled:cursor-not-allowed",
                      isExecuting ? "hover:bg-white/[0.08]" : input.trim() ? "hover:bg-black/[0.04]" : "opacity-55"
                    )}
                  >
                    <span className="pointer-events-none absolute bottom-full left-1/2 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#111] px-2 py-1 font-mono text-[10px] font-bold tracking-[0.04em] text-white/60 opacity-0 shadow-xl transition-opacity group-hover:opacity-100">
                      {isExecuting ? t('chat.stop') : sendShortcutHint}
                    </span>
                    {isExecuting ? (
                      <StopIndicator />
                    ) : isSubmitting ? (
                      <RefreshCw size={16} strokeWidth={2.4} className="relative z-10 animate-spin" />
                    ) : (
                      <Send size={17} strokeWidth={input.trim() ? 2.5 : 1.5} className="relative z-10" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsSendMenuOpen((o) => !o)}
                    className={cn(
                      "flex h-10 w-7 items-center justify-center rounded-r-lg border-l transition-colors",
                      input.trim() ? "border-black/10 hover:bg-black/[0.05]" : "border-white/10 hover:bg-white/[0.06]"
                    )}
                    title={t('chat.send_mode')}
                  >
                    <ChevronDown size={13} strokeWidth={2.4} />
                  </button>
                </div>
                {isSendMenuOpen && (
                  <div className="absolute bottom-full right-0 z-50 mb-2 w-48 overflow-hidden rounded-xl border border-white/10 bg-[#101010] p-1 shadow-2xl">
                    {(['mod_enter', 'enter'] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => { setSendMode(mode); setIsSendMenuOpen(false); }}
                        className={cn(
                          "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs font-bold transition-colors",
                          sendMode === mode ? "bg-white text-[#080808]" : "text-white/60 hover:bg-white/[0.06] hover:text-white"
                        )}
                      >
                        <span>{mode === 'enter' ? t('chat.send_mode_enter') : t('chat.send_mode_mod_enter')}</span>
                        <span className="font-mono text-[10px] opacity-60">{mode === 'enter' ? '↵' : '⌘↵'}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {composerNotice && (
              <div className="px-4 pb-3 text-xs font-medium text-white/58">{composerNotice}</div>
            )}
          </div>
        ) : null}
        <div className="flex items-center justify-center gap-4 mt-4">
          <p className="text-[10px] text-white/10 font-bold uppercase tracking-[0.1em]">{t('app.byok_enabled')}</p>
          <div className="h-1 w-1 rounded-full bg-white/10" />
          <p className="text-[10px] text-white/10 font-bold uppercase tracking-[0.1em]">{t('app.deterministic_kernel')}</p>
        </div>
      </div>

      {/* Session insights */}
      <SessionInsightsDrawer
        open={isInsightsOpen}
        sessionId={currentSessionId ?? ''}
        isConnected={isConnected}
        call={call}
        onClose={() => setIsInsightsOpen(false)}
        t={t}
      />

      {/* Session search */}
      <SessionSearch
        isOpen={isSearchOpen}
        sessions={sessions.map((s) => ({ id: s.id, title: s.title }))}
        onSearch={async (sessionId: string, query: string) => {
          try {
            const res: any = await call('list_messages', { session_id: sessionId, limit: 100 });
            return res.messages || [];
          } catch { return []; }
        }}
        onSelectSession={(sessionId: string) => { switchSession(sessionId); }}
        onClose={() => setIsSearchOpen(false)}
      />
    </motion.div>
  );
}

// ---- Sub-components ----

function ThinkingIndicator({ compact = false }: { compact?: boolean }) {
  const size = compact ? 'w-2.5 h-2.5' : 'w-3 h-3';
  return (
    <div className={cn('flex items-center py-1', compact ? 'justify-center' : 'justify-start')}>
      <motion.div
        animate={{ scale: [0.9, 1.25, 0.9], opacity: [0.45, 1, 0.45] }}
        transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
        className={cn(size, 'rounded-full bg-white/85')}
      />
    </div>
  );
}

function StopIndicator() {
  return (
    <div className="relative flex h-4 w-4 items-center justify-center">
      <motion.span
        aria-hidden="true"
        className="absolute inset-[-4px] rounded-[8px] bg-current/18 blur-[6px]"
        animate={{ scale: [0.82, 1.22, 0.82], opacity: [0.16, 0.52, 0.16] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.span
        aria-hidden="true"
        className="absolute inset-[-1px] rounded-[5px] border border-current/30"
        animate={{ scale: [0.88, 1.16, 0.88], opacity: [0.28, 0.82, 0.28] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.span
        className="relative z-10 block h-[10px] w-[10px] rounded-[3px] bg-current"
        animate={{ scale: [0.86, 1.1, 0.86], opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
    </div>
  );
}

function EmptyState({ t, setInput }: { t: (k: string) => string; setInput: (v: string) => void }) {
  return (
    <>
      <div className="mb-8 flex items-end justify-between gap-8">
        <div className="space-y-3">
          <h2 className="display-title text-5xl leading-none text-white/90">{t('chat.welcome_title')}</h2>
        </div>
        <p className="hidden max-w-xs text-right text-sm font-medium leading-6 text-white/38 md:block">{t('chat.welcome_subtitle')}</p>
      </div>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-6">
        {[
          { i: '01', icon: '🔥', title: t('chat.quick_actions.hotspot_title'), prompt: t('chat.quick_actions.hotspot_prompt') },
          { i: '02', icon: '🛋️', title: t('chat.quick_actions.scout_title'), prompt: t('chat.quick_actions.scout_prompt') },
          { i: '03', icon: '🎯', title: t('chat.quick_actions.keyword_title'), prompt: t('chat.quick_actions.keyword_prompt') },
          { i: '04', icon: '🔗', title: t('chat.quick_actions.backlink_title'), prompt: t('chat.quick_actions.backlink_prompt') },
          { i: '05', icon: '📈', title: t('chat.quick_actions.stock_title'), prompt: t('chat.quick_actions.stock_prompt') },
          { i: '06', icon: '⏱️', title: t('chat.quick_actions.daily_dashboard_title'), prompt: t('chat.quick_actions.daily_dashboard_prompt') },
        ].map((qa) => (
          <button
            key={qa.i}
            onClick={() => setInput(qa.prompt)}
            className="group relative min-h-[92px] overflow-hidden rounded-lg border border-white/8 bg-white/[0.025] p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-white/22 hover:bg-white/[0.06] hover:shadow-[0_18px_45px_rgba(0,0,0,0.25)]"
          >
            <div className="absolute inset-x-3 top-0 h-px bg-gradient-to-r from-transparent via-white/18 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
            <div className="relative z-10 flex h-full flex-col justify-between gap-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-black/20 shadow-inner transition-transform group-hover:scale-105">
                  <span className="text-sm">{qa.icon}</span>
                </div>
                <span className="font-mono text-[10px] font-bold tabular-nums text-white/18 transition-colors group-hover:text-white/35">{qa.i}</span>
              </div>
              <div className="flex items-end justify-between gap-2">
                <h4 className="text-[13px] font-bold leading-5 tracking-tight text-white/72 transition-colors group-hover:text-white">{qa.title}</h4>
                <ChevronRight size={14} className="shrink-0 translate-x-0 text-white/12 transition-all group-hover:translate-x-0.5 group-hover:text-white/45" />
              </div>
            </div>
          </button>
        ))}
      </div>
    </>
  );
}

function ModelSetupGuide({ t, issue, onOpenSettings }: {
  t: (k: string) => string;
  issue?: any;
  onOpenSettings: () => void;
}) {
  const getDesc = () => {
    switch (issue?.code) {
      case 'missing_api_key': return t('settings.setup_missing_api_key');
      case 'missing_base_url': return t('settings.setup_missing_base_url');
      case 'active_model_invalid': return t('settings.setup_active_model_invalid');
      default: return t('settings.setup_no_runnable_model');
    }
  };
  return (
    <section className="relative overflow-hidden rounded-[2rem] border border-amber-200/12 bg-[linear-gradient(135deg,rgba(255,243,211,0.11),rgba(255,255,255,0.02))] px-8 py-9 shadow-[0_28px_90px_rgba(0,0,0,0.26)] backdrop-blur-xl">
      <div className="absolute inset-y-0 left-0 w-px bg-gradient-to-b from-transparent via-amber-100/35 to-transparent" />
      <div className="absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-amber-100/24 to-transparent" />
      <div className="relative z-10 flex flex-col gap-6">
        <div className="space-y-2">
          <h3 className="text-4xl font-black tracking-tight text-amber-50">{t('settings.setup_welcome_title')}</h3>
          <p className="max-w-3xl text-base font-medium leading-7 text-white/76">{getDesc()}</p>
        </div>
        <button
          onClick={onOpenSettings}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-4 py-3 text-[11px] font-black uppercase tracking-[0.16em] text-[#080808] transition-colors hover:bg-white/92"
        >
          {t('settings.open_model_settings')} <ChevronRight size={14} />
        </button>
      </div>
    </section>
  );
}
