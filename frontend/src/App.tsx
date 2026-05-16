import React, { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import {
  BrowserRouter, Routes, Route, useNavigate, useLocation,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useBackendConnection } from './hooks/useBackendConnection';
import { useSessions } from './hooks/useSessions';
import { useI18n } from './hooks/useI18n';
import { useCommands } from './hooks/useCommands';
import {
  Settings, Activity, CalendarClock, Cpu, Brain, Plus, Trash2, ChevronRight,
  Globe, BarChart3, RefreshCw, Check, Copy, X, ExternalLink, Search, Slash
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from './utils/cn';
import { ChatView } from './pages/ChatView';
import { TasksView } from './pages/TasksView';
import { SchedulesView } from './pages/SchedulesView';
import { SkillsView } from './pages/SkillsView';
import { MemoryView } from './pages/MemoryView';
import { SettingsView } from './pages/SettingsView';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

// ---- Helpers ----

const DEFAULT_FERRYMAN_WS_URL = 'ws://127.0.0.1:8000/ws';
const DEFAULT_FERRYMAN_BEARER_TOKEN = 'dev_token_12345';

function isTauriRuntime() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

function buildWebSocketUrl(baseUrl: string, token?: string) {
  if (!token) return baseUrl;
  const url = new URL(baseUrl);
  url.searchParams.set('access_token', token);
  return url.toString();
}

function getDefaultWebSocketUrl() {
  const baseUrl = import.meta.env.VITE_FERRYMAN_WS_URL || DEFAULT_FERRYMAN_WS_URL;
  const token = import.meta.env.VITE_FERRYMAN_BEARER_TOKEN || DEFAULT_FERRYMAN_BEARER_TOKEN;
  return buildWebSocketUrl(baseUrl, token);
}

// ---- Sidebar Nav ----

interface NavItemProps {
  icon: React.ReactNode;
  label: string;
  to: string;
  active: boolean;
}

function SidebarNav({ icon, label, to, active }: NavItemProps) {
  const navigate = useNavigate();
  return (
    <div
      onClick={() => navigate(to)}
      className={cn(
        "flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-200 cursor-pointer group",
        active
          ? "bg-white/[0.04] text-white ring-1 ring-white/10"
          : "text-white/40 hover:text-white hover:bg-white/5"
      )}
    >
      <div className={cn(
        "transition-transform duration-300 group-hover:scale-110",
        active ? "text-white" : "text-white/40 group-hover:text-white"
      )}>
        {icon}
      </div>
      <span className="text-sm font-semibold flex-1">{label}</span>
      {active && <ChevronRight size={14} className="opacity-50" />}
    </div>
  );
}

// ---- AppLayout ----

interface AppLayoutProps {
  wsUrl: string | null;
  connection: ReturnType<typeof useBackendConnection>;
}

function AppLayout({ wsUrl, connection }: AppLayoutProps) {
  const { call, execute: executeInstruction, cancelRun, isConnected, toolActivities, clearToolActivities, lastEvent } = connection;
  const { t, locale, changeLanguage } = useI18n();
  const {
    messages, execute, stopActiveRun,
    isSubmitting, isExecuting,
    sessions, currentSessionId, currentUsage,
    refreshSessions, switchSession, createNewSession,
    renameSession, deleteSession,
    loadOlderMessages, hasOlderMessages, isLoadingOlderMessages,
  } = useSessions({ call, executeInstruction, cancelRun, clearToolActivities, lastEvent, isConnected });

  const [modelReadiness, setModelReadiness] = useState<any>(null);
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});

  // Command palette
  const commandPalette = useCommands();
  const [isCommandMenuOpen, setIsCommandMenuOpen] = useState(false);

  const location = useLocation();
  const navigate = useNavigate();

  // Determine current view from path
  const currentView = location.pathname.replace('/', '') || 'chat';

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        commandPalette.open();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [commandPalette]);

  // Load model readiness
  useEffect(() => {
    if (isConnected) {
      call('get_model_readiness').then((r: any) => setModelReadiness(r)).catch(() => {});
      call('get_available_models').then((m: any) => setAvailableModels(m || {})).catch(() => {});
    }
  }, [isConnected, call]);

  // Fetch initial config
  useEffect(() => {
    if (isConnected) {
      if (isTauriRuntime()) {
        invoke('report_frontend_smoke_status', { status: 'backend_connected' }).catch(() => {});
      }
      refreshSessions();
    }
  }, [isConnected]);

  // Command palette handlers
  const handleCommandExecute = useCallback((commandId: string, args?: string) => {
    switch (commandId) {
      case 'new-session': createNewSession().then(() => navigate('/chat')); break;
      case 'settings': navigate('/settings'); break;
      case 'tasks': navigate('/tasks'); break;
      case 'schedules': navigate('/schedules'); break;
      case 'skills': navigate('/skills'); break;
      case 'memory': navigate('/memory'); break;
      case 'search': if (args) navigate('/chat'); break;
    }
  }, [createNewSession, navigate]);

  useEffect(() => { commandPalette.executeById = handleCommandExecute; }, [commandPalette, handleCommandExecute]);

  return (
    <div className="flex w-full h-full bg-transparent text-white selection:bg-white/20 selection:text-white font-sans">
      {/* Sidebar */}
      <aside className="w-72 border-r border-white/5 flex flex-col glass z-10 transition-all duration-300">
        {/* Logo */}
        <div className="p-6 pb-4">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="RabAiAgent Logo" className="w-10 h-10 rounded-xl shadow-xl ring-1 ring-white/10 object-cover" />
            <div>
              <h1 className="font-bold text-lg leading-tight tracking-tight">{t('app.title')}</h1>
              <p className="text-[10px] text-white/40 uppercase tracking-[0.2em] font-bold">{t('app.subtitle')}</p>
            </div>
          </div>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto px-4 space-y-1 custom-scrollbar">
          <div className="px-2 mb-4 mt-2 flex items-center justify-between group/header">
            <h3 className="text-[11px] font-black text-white/50 uppercase tracking-[0.2em]">{t('nav.recent_sessions')}</h3>
            <button
              onClick={() => { createNewSession().then(() => navigate('/chat')); }}
              className="w-6 h-6 rounded-md flex items-center justify-center text-white/60 bg-white/5 border border-white/10 hover:bg-white/15 hover:text-white transition-all shadow-sm shrink-0"
              title={t('nav.new_chat')}
            >
              <Plus size={14} strokeWidth={2} />
            </button>
          </div>

          {sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => { switchSession(s.id); navigate('/chat'); }}
              onDoubleClick={(e) => { e.stopPropagation(); /* TODO: rename */ }}
              className={cn(
                "group relative p-3.5 rounded-2xl transition-all cursor-pointer flex flex-col gap-1.5 border border-transparent",
                currentSessionId === s.id ? "bg-white/5 border-white/10 shadow-xl" : "hover:bg-white/[0.04]"
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn(
                  "text-sm font-bold truncate flex-1 tracking-tight",
                  currentSessionId === s.id ? "text-white" : "text-white/50 group-hover:text-white/80"
                )}>
                  {s.title || t('chat.untitled')}
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-500/20 hover:text-red-400 rounded-lg transition-all"
                >
                  <Trash2 size={13} />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <div className="text-[9px] font-black text-white/40 px-2 py-0.5 rounded-md bg-white/5 border border-white/5 group-hover:text-white/60 group-hover:border-white/10 transition-all uppercase tracking-wider">
                  {(s.input_tokens + s.output_tokens).toLocaleString()} {t('tasks.tokens_unit')}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Navigation */}
        <nav className="p-4 space-y-1 border-t border-white/5 mt-auto">
          <SidebarNav icon={<Activity size={18}/>} label={t('nav.tasks')} to="/tasks" active={currentView === 'tasks'} />
          <SidebarNav icon={<CalendarClock size={18}/>} label={t('nav.schedules')} to="/schedules" active={currentView === 'schedules'} />
          <SidebarNav icon={<Cpu size={18}/>} label={t('nav.skills')} to="/skills" active={currentView === 'skills'} />
          <SidebarNav icon={<Brain size={18}/>} label={t('nav.memory') || 'Memory'} to="/memory" active={currentView === 'memory'} />
          <SidebarNav icon={<Settings size={18}/>} label={t('nav.settings')} to="/settings" active={currentView === 'settings'} />

          <div className="flex items-center gap-2 pt-4 px-2">
            <button
              onClick={() => changeLanguage('zh')}
              className={cn("text-[9px] font-bold px-2 py-1 rounded transition-colors", locale === 'zh' ? "bg-white text-[#080808]" : "bg-white/5 text-white/40 hover:bg-white/10")}
            >ZH</button>
            <button
              onClick={() => changeLanguage('en')}
              className={cn("text-[9px] font-bold px-2 py-1 rounded transition-colors", locale === 'en' ? "bg-white text-[#080808]" : "bg-white/5 text-white/40 hover:bg-white/10")}
            >EN</button>
            <div className="ml-auto flex items-center gap-2">
              <div className={cn(
                "w-1.5 h-1.5 rounded-full",
                isConnected ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]" : "bg-red-500 animate-pulse"
              )} />
            </div>
          </div>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col relative overflow-hidden">
        {/* Animated Background Overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-white/[0.02] via-transparent to-transparent pointer-events-none" />

        {/* Header */}
        <header className="h-16 border-b border-white/5 flex items-center justify-between px-8 z-10 backdrop-blur-xl bg-[#0a0a0a]/55">
          <div className="flex items-center gap-4">
            {currentView === 'chat' && (
              <div className="flex items-center gap-2">
                <Cpu size={14} className="text-white/30" />
                {/* Model selector placeholder - delegated to ChatView header */}
              </div>
            )}
          </div>
          <div className="flex items-center">
            {currentView === 'chat' && (
              <div className="flex items-center gap-4 bg-white/[0.04] border border-white/10 rounded-full px-5 py-2 backdrop-blur-md shadow-sm">
                <div className="flex items-center gap-2">
                  <span className="text-[9px] font-black text-white/40 uppercase tracking-widest leading-none">{t('tasks.token_in')}</span>
                  <span className="text-white/80 font-mono text-[11px] font-medium leading-none">{currentUsage.input_tokens.toLocaleString()}</span>
                </div>
                <div className="w-[1px] h-3 bg-white/10" />
                <div className="flex items-center gap-2">
                  <span className="text-[9px] font-black text-white/40 uppercase tracking-widest leading-none">{t('tasks.token_out')}</span>
                  <span className="text-white/80 font-mono text-[11px] font-medium leading-none">{currentUsage.output_tokens.toLocaleString()}</span>
                </div>
                <div className="w-[1px] h-3 bg-white/20" />
                <div className="flex items-center gap-2">
                  <span className="text-[9px] font-black text-white/70 uppercase tracking-widest leading-none">{t('tasks.token_total')}</span>
                  <span className="text-white font-mono text-[11px] font-bold leading-none">{currentUsage.total_tokens.toLocaleString()}</span>
                </div>
              </div>
            )}
          </div>
        </header>

        {/* Routes */}
        <Routes>
          <Route
            path="/"
            element={
              <ChatView
                messages={messages}
                sessions={sessions}
                currentSessionId={currentSessionId}
                currentUsage={currentUsage}
                isSubmitting={isSubmitting}
                isExecuting={isExecuting}
                hasOlderMessages={hasOlderMessages}
                isLoadingOlderMessages={isLoadingOlderMessages}
                isConnected={isConnected}
                toolActivities={toolActivities}
                modelReadiness={modelReadiness}
                availableModels={availableModels}
                execute={execute}
                stopActiveRun={stopActiveRun}
                switchSession={switchSession}
                createNewSession={createNewSession}
                deleteSession={deleteSession}
                renameSession={renameSession}
                loadOlderMessages={loadOlderMessages}
                refreshSessions={refreshSessions}
                call={call}
                t={t}
                locale={locale}
                changeLanguage={changeLanguage}
              />
            }
          />
          <Route path="/chat" element={
            <ChatView
              messages={messages}
              sessions={sessions}
              currentSessionId={currentSessionId}
              currentUsage={currentUsage}
              isSubmitting={isSubmitting}
              isExecuting={isExecuting}
              hasOlderMessages={hasOlderMessages}
              isLoadingOlderMessages={isLoadingOlderMessages}
              isConnected={isConnected}
              toolActivities={toolActivities}
              modelReadiness={modelReadiness}
              availableModels={availableModels}
              execute={execute}
              stopActiveRun={stopActiveRun}
              switchSession={switchSession}
              createNewSession={createNewSession}
              deleteSession={deleteSession}
              renameSession={renameSession}
              loadOlderMessages={loadOlderMessages}
              refreshSessions={refreshSessions}
              call={call}
              t={t}
              locale={locale}
              changeLanguage={changeLanguage}
            />
          } />
          <Route path="/tasks" element={<TasksView call={call} isConnected={isConnected} t={t} />} />
          <Route path="/schedules" element={<SchedulesView call={call} isConnected={isConnected} t={t} />} />
          <Route path="/skills" element={<SkillsView call={call} isConnected={isConnected} t={t} />} />
          <Route path="/memory" element={<MemoryView call={call} isConnected={isConnected} t={t} />} />
          <Route path="/settings" element={<SettingsView call={call} isConnected={isConnected} t={t} />} />
        </Routes>
      </main>
    </div>
  );
}

// ---- Root App ----

export default function App() {
  const [wsUrl, setWsUrl] = useState<string | null>(null);
  const connection = useBackendConnection(wsUrl);

  useEffect(() => {
    let cancelled = false;
    const resolve = async () => {
      if (!isTauriRuntime() || import.meta.env.DEV) {
        if (!cancelled) setWsUrl(getDefaultWebSocketUrl());
        return;
      }
      try {
        const conn = await invoke<{ wsUrl: string; accessToken: string }>('get_backend_connection');
        if (!cancelled) setWsUrl(buildWebSocketUrl(conn.wsUrl, conn.accessToken));
      } catch {
        if (!cancelled) setWsUrl(getDefaultWebSocketUrl());
      }
    };
    resolve();
    return () => { cancelled = true; };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout wsUrl={wsUrl} connection={connection} />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
