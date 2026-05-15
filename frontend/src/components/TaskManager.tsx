import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Activity, Check, ChevronRight, Save, Search, Trash2, X, Filter, CheckSquare, Square, Clock, List } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import { RefreshIconButton } from './RefreshIconButton';
import { SideDrawer } from './SideDrawer';
import { ManagedTask, ManagedTaskStatus, useManagedTasks } from '../hooks/useManagedTasks';
import { cn } from '../utils/cn';

interface TaskManagerProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

const STATUS_OPTIONS: ManagedTaskStatus[] = ['pending', 'running', 'success', 'failed', 'canceled'];

function taskProgress(task: ManagedTask) {
  return typeof task.metadata?.progress_note === 'string' ? task.metadata.progress_note : '';
}

function taskInstruction(task: ManagedTask) {
  return typeof task.args?.instruction === 'string' ? task.args.instruction : '';
}

function taskPayload(task: ManagedTask) {
  return task.args?.payload && typeof task.args.payload === 'object' && !Array.isArray(task.args.payload)
    ? task.args.payload
    : {};
}

function formatDate(value?: string | null) {
  if (!value) return '-';
  return new Intl.DateTimeFormat(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

export function TaskManager({ call, isConnected, t }: TaskManagerProps) {
  const {
    tasks,
    selectedTask,
    setSelectedTask,
    summary,
    nextCursor,
    isLoading,
    isLoadingMore,
    error,
    loadTasks,
    selectTask,
    updateTask,
    deleteTask,
  } = useManagedTasks(call);
  const [draft, setDraft] = useState<ManagedTask | null>(null);
  const [payloadJson, setPayloadJson] = useState('{}');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ManagedTask | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Search and filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<ManagedTaskStatus | 'all'>('all');
  const [sessionFilter, setSessionFilter] = useState<string | 'all'>('all');
  const [viewMode, setViewMode] = useState<'list' | 'grouped'>('list');

  // Batch selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchActionTarget, setBatchActionTarget] = useState<ManagedTaskStatus | null>(null);

  useEffect(() => {
    if (isConnected) {
      loadTasks();
    }
  }, [isConnected, loadTasks]);

  useEffect(() => {
    setDraft(selectedTask);
    setPayloadJson(JSON.stringify(selectedTask ? taskPayload(selectedTask) : {}, null, 2));
    setFormError(null);
  }, [selectedTask]);

  const summaryItems = useMemo(() => [
    { key: 'pending', value: summary.pending, className: 'text-amber-300' },
    { key: 'running', value: summary.running, className: 'text-white' },
    { key: 'success', value: summary.success, className: 'text-green-300' },
    { key: 'failed', value: summary.failed, className: 'text-red-300' },
    { key: 'canceled', value: summary.canceled, className: 'text-white/45' },
    { key: 'total', value: summary.total, className: 'text-white' },
  ], [summary]);

  // Filter tasks based on search, status, and session
  const filteredTasks = useMemo(() => {
    let result = tasks;
    if (statusFilter !== 'all') {
      result = result.filter(task => task.status === statusFilter);
    }
    if (sessionFilter !== 'all') {
      result = result.filter(task => task.session_id === sessionFilter);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(task =>
        task.title.toLowerCase().includes(query) ||
        task.id.toLowerCase().includes(query) ||
        (task.args?.instruction?.toLowerCase() || '').includes(query)
      );
    }
    return result;
  }, [tasks, statusFilter, sessionFilter, searchQuery]);

  // Group tasks by session
  const groupedTasks = useMemo(() => {
    const groups: Record<string, ManagedTask[]> = {};
    for (const task of filteredTasks) {
      const sessionId = task.session_id || 'unknown';
      if (!groups[sessionId]) groups[sessionId] = [];
      groups[sessionId].push(task);
    }
    return groups;
  }, [filteredTasks]);

  // Get unique sessions for filter dropdown
  const uniqueSessions = useMemo(() => {
    const sessions = new Set<string>();
    tasks.forEach(task => {
      if (task.session_id) sessions.add(task.session_id);
    });
    return Array.from(sessions).sort();
  }, [tasks]);

  // Toggle task selection for batch operations
  const toggleTaskSelection = (taskId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  // Select all visible tasks
  const selectAllVisible = () => {
    if (selectedIds.size === filteredTasks.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredTasks.map(t => t.id)));
    }
  };

  // Batch delete
  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    setIsDeleting(true);
    setFormError(null);
    try {
      for (const id of selectedIds) {
        await deleteTask(id);
      }
      setSelectedIds(new Set());
      setBatchActionTarget(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsDeleting(false);
    }
  };

  // Batch update status
  const handleBatchStatusUpdate = async (newStatus: ManagedTaskStatus) => {
    if (selectedIds.size === 0) return;
    setIsSaving(true);
    setFormError(null);
    try {
      for (const id of selectedIds) {
        const task = tasks.find(t => t.id === id);
        if (task) {
          await updateTask({ ...task, status: newStatus });
        }
      }
      setSelectedIds(new Set());
      setBatchActionTarget(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  const handleSave = async () => {
    if (!draft) return;
    setIsSaving(true);
    setFormError(null);
    try {
      const payload = payloadJson.trim() ? JSON.parse(payloadJson) : {};
      await updateTask({
        ...draft,
        args: {
          ...draft.args,
          payload,
        },
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    setFormError(null);
    try {
      await deleteTask(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex-1 overflow-hidden p-8">
      <div className="mx-auto flex h-full max-w-6xl flex-col gap-6">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-4xl font-black tracking-tight">{t('tasks.title')}</h2>
            <p className="mt-2 text-sm font-medium text-white/32">{t('tasks.subtitle')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {summaryItems.map((item) => (
              <div key={item.key} className="rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2">
                <span className={cn('mr-2 text-sm font-black tabular-nums', item.className)}>{item.value}</span>
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-white/35">
                  {item.key === 'total' ? t('tasks.total_count') : t(`tasks.status.${item.key}`)}
                </span>
              </div>
            ))}
            <RefreshIconButton
              onClick={() => loadTasks()}
              disabled={!isConnected || isLoading}
              isLoading={isLoading}
              label={t('tasks.refresh')}
            />
          </div>
        </header>

        {/* Search and Filter Bar */}
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-white/8 bg-white/[0.02] p-3">
          {/* Search Input */}
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('tasks.search_placeholder') || 'Search tasks...'}
              className="w-full rounded-lg border border-white/10 bg-white/[0.03] py-2 pl-9 pr-3 text-xs text-white placeholder:text-white/25 focus:border-white/20 focus:outline-none"
            />
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-white/30" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ManagedTaskStatus | 'all')}
              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white focus:border-white/20 focus:outline-none"
            >
              <option value="all">{t('tasks.filter_all') || 'All Status'}</option>
              {STATUS_OPTIONS.map(status => (
                <option key={status} value={status}>{t(`tasks.status.${status}`)}</option>
              ))}
            </select>
          </div>

          {/* Session Filter */}
          {uniqueSessions.length > 0 && (
            <div className="flex items-center gap-2">
              <Clock size={14} className="text-white/30" />
              <select
                value={sessionFilter}
                onChange={(e) => setSessionFilter(e.target.value)}
                className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white focus:border-white/20 focus:outline-none"
              >
                <option value="all">{t('tasks.filter_all_sessions') || 'All Sessions'}</option>
                {uniqueSessions.map(session => (
                  <option key={session} value={session}>{session.slice(0, 8)}...</option>
                ))}
              </select>
            </div>
          )}

          {/* View Toggle */}
          <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-1">
            <button
              onClick={() => setViewMode('list')}
              className={cn(
                'rounded-md px-2 py-1 text-xs font-black transition-colors',
                viewMode === 'list' ? 'bg-white text-black' : 'text-white/50 hover:text-white'
              )}
            >
              <List size={14} />
            </button>
            <button
              onClick={() => setViewMode('grouped')}
              className={cn(
                'rounded-md px-2 py-1 text-xs font-black transition-colors',
                viewMode === 'grouped' ? 'bg-white text-black' : 'text-white/50 hover:text-white'
              )}
            >
              <Activity size={14} />
            </button>
          </div>

          {/* Batch Selection */}
          <button
            onClick={selectAllVisible}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white/70 hover:text-white transition-colors"
          >
            {selectedIds.size === filteredTasks.length && filteredTasks.length > 0 ? <CheckSquare size={14} /> : <Square size={14} />}
            {t('tasks.select_all') || 'Select All'}
          </button>

          {/* Batch Actions */}
          {selectedIds.size > 0 && (
            <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
              <span className="text-xs text-white/50">{selectedIds.size} selected</span>
              <select
                value={batchActionTarget || ''}
                onChange={(e) => {
                  if (e.target.value) {
                    handleBatchStatusUpdate(e.target.value as ManagedTaskStatus);
                  }
                }}
                className="rounded border border-white/10 bg-black/20 px-2 py-1 text-xs text-white focus:border-white/20 focus:outline-none"
              >
                <option value="">{t('tasks.batch_status') || 'Change Status'}</option>
                {STATUS_OPTIONS.filter(s => s !== 'running').map(status => (
                  <option key={status} value={status}>{t(`tasks.status.${status}`)}</option>
                ))}
              </select>
              <button
                onClick={handleBatchDelete}
                disabled={isDeleting}
                className="flex items-center gap-1 rounded border border-red-400/20 px-2 py-1 text-xs text-red-200 hover:bg-red-500/15 transition-colors disabled:opacity-50"
              >
                <Trash2 size={12} />
                {t('common.delete')}
              </button>
            </div>
          )}
        </div>

        <section className="min-h-0 flex-1 overflow-hidden rounded-xl border border-white/8 bg-white/[0.02]">
          <div className="flex h-full flex-col">
            <div className={cn(
              'grid items-center gap-3 border-b border-white/8 px-5 py-3 text-[10px] font-black uppercase tracking-[0.18em] text-white/28',
              viewMode === 'list'
                ? 'grid-cols-[32px_minmax(0,1fr)_120px_120px_32px]'
                : 'grid-cols-[minmax(0,1fr)_120px_120px_32px]'
            )}>
              {viewMode === 'list' && <span />}
              <span>{t('tasks.list_title')}</span>
              <span>{t('tasks.field_status')}</span>
              <span>{t('tasks.field_updated_at')}</span>
              <span />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
              {error && <div className="m-4 rounded-lg border border-red-400/20 bg-red-500/10 p-3 text-xs text-red-100">{error}</div>}
              {filteredTasks.length === 0 && !isLoading ? (
                <div className="flex h-full flex-col items-center justify-center p-10 text-center">
                  <Activity size={34} className="mb-4 text-white/8" />
                  <p className="text-sm font-bold text-white/25">{t('tasks.empty')}</p>
                </div>
              ) : viewMode === 'list' ? (
                filteredTasks.map((task) => (
                  <div
                    key={task.id}
                    className={cn(
                      'group grid min-h-[72px] w-full items-center gap-3 border-b border-white/6 px-5 py-3 text-left transition-colors hover:bg-white/[0.045]',
                      viewMode === 'list'
                        ? 'grid-cols-[32px_minmax(0,1fr)_120px_120px_32px]'
                        : 'grid-cols-[minmax(0,1fr)_120px_120px_32px]',
                      selectedTask?.id === task.id && 'bg-white/[0.055]'
                    )}
                  >
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleTaskSelection(task.id); }}
                      className="flex items-center justify-center text-white/30 hover:text-white/60 transition-colors"
                    >
                      {selectedIds.has(task.id) ? <CheckSquare size={16} /> : <Square size={16} />}
                    </button>
                    <button
                      onClick={() => selectTask(task.id)}
                      className="flex min-w-0 items-center gap-4 text-left"
                    >
                      <TaskStatusIcon status={task.status} />
                      <div className="min-w-0 flex-1">
                        <h3 className="truncate text-sm font-black tracking-tight text-white/84">{task.title}</h3>
                        <p className="mt-1 truncate text-xs font-medium text-white/32">{taskProgress(task) || t('tasks.no_progress')}</p>
                      </div>
                    </button>
                    <span className="w-fit rounded-md border border-white/10 px-2 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-white/42">
                      {t(`tasks.status.${task.status}`)}
                    </span>
                    <span className="font-mono text-[10px] text-white/28">{formatDate(task.updated_at)}</span>
                    <ChevronRight size={15} className="justify-self-end text-white/18 transition-transform group-hover:translate-x-0.5 group-hover:text-white/45" />
                  </div>
                ))
              ) : (
                // Grouped view
                Object.entries(groupedTasks).map(([sessionId, sessionTasks]) => (
                  <div key={sessionId} className="border-b border-white/6">
                    <div className="flex items-center gap-2 bg-white/[0.02] px-5 py-2 text-[10px] font-black uppercase tracking-[0.18em] text-white/40">
                      <Clock size={12} />
                      {sessionId.slice(0, 8)}... ({sessionTasks.length})
                    </div>
                    {sessionTasks.map((task) => (
                      <div
                        key={task.id}
                        className={cn(
                          'group grid min-h-[72px] w-full items-center gap-3 border-b border-white/4 px-5 py-3 text-left transition-colors hover:bg-white/[0.045]',
                          'grid-cols-[minmax(0,1fr)_120px_120px_32px]',
                          selectedTask?.id === task.id && 'bg-white/[0.055]'
                        )}
                      >
                        <button
                          onClick={() => selectTask(task.id)}
                          className="flex min-w-0 items-center gap-4 text-left"
                        >
                          <TaskStatusIcon status={task.status} />
                          <div className="min-w-0 flex-1">
                            <h3 className="truncate text-sm font-black tracking-tight text-white/84">{task.title}</h3>
                            <p className="mt-1 truncate text-xs font-medium text-white/32">{taskProgress(task) || t('tasks.no_progress')}</p>
                          </div>
                        </button>
                        <span className="w-fit rounded-md border border-white/10 px-2 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-white/42">
                          {t(`tasks.status.${task.status}`)}
                        </span>
                        <span className="font-mono text-[10px] text-white/28">{formatDate(task.updated_at)}</span>
                        <ChevronRight size={15} className="justify-self-end text-white/18 transition-transform group-hover:translate-x-0.5 group-hover:text-white/45" />
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
            {nextCursor && (
              <button
                onClick={() => loadTasks({ append: true, cursor: nextCursor })}
                disabled={isLoadingMore}
                className="border-t border-white/8 px-4 py-3 text-xs font-black uppercase tracking-[0.18em] text-white/45 transition-colors hover:bg-white/[0.04] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {isLoadingMore ? t('common.loading') : t('common.load_more')}
              </button>
            )}
          </div>
        </section>
      </div>

      <SideDrawer
        open={Boolean(draft)}
        title={t('tasks.detail_title')}
        subtitle={draft ? formatDate(draft.updated_at) : undefined}
        onClose={() => setSelectedTask(null)}
      >
        {draft && (
          <div className="space-y-5">
            <Field label={t('tasks.field_title')}>
              <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} className="field-input" />
            </Field>
            <Field label={t('tasks.field_status')}>
              <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ManagedTaskStatus })} className="field-input">
                {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{t(`tasks.status.${status}`)}</option>)}
              </select>
            </Field>
            <Field label={t('tasks.field_progress')}>
              <textarea
                value={taskProgress(draft)}
                onChange={(event) => setDraft({
                  ...draft,
                  metadata: { ...draft.metadata, progress_note: event.target.value },
                })}
                className="field-textarea min-h-[96px]"
              />
            </Field>
            <Field label={t('tasks.field_instruction')}>
              <textarea
                value={taskInstruction(draft)}
                onChange={(event) => setDraft({
                  ...draft,
                  args: { ...draft.args, instruction: event.target.value },
                })}
                className="field-textarea min-h-[120px]"
              />
            </Field>
            <Field label={t('tasks.field_payload')}>
              <textarea value={payloadJson} onChange={(event) => setPayloadJson(event.target.value)} className="field-textarea min-h-[140px] font-mono text-[11px]" />
            </Field>
            <div className="grid grid-cols-2 gap-3 text-xs text-white/35">
              <Meta label={t('tasks.field_created_at')} value={formatDate(draft.created_at)} />
              <Meta label={t('tasks.field_finished_at')} value={formatDate(draft.finished_at)} />
              <Meta label={t('tasks.identifier')} value={draft.id} wide />
            </div>
            {formError && <p className="rounded-lg border border-red-400/20 bg-red-500/10 p-3 text-xs text-red-100">{formError}</p>}
            <div className="flex items-center justify-between gap-3 border-t border-white/8 pt-5">
              <button onClick={() => setDeleteTarget(draft)} className="inline-flex items-center gap-2 rounded-lg border border-red-400/20 px-4 py-2 text-xs font-black text-red-200 transition-colors hover:bg-red-500/15">
                <Trash2 size={14} />
                {t('common.delete')}
              </button>
              <button onClick={handleSave} disabled={isSaving} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-xs font-black text-[#080808] transition-colors hover:bg-white/90 disabled:cursor-not-allowed disabled:opacity-50">
                <Save size={14} />
                {isSaving ? t('common.saving') : t('common.save')}
              </button>
            </div>
          </div>
        )}
      </SideDrawer>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={t('tasks.delete_title')}
        description={t('tasks.delete_description').replace('{name}', deleteTarget?.title || '')}
        confirmLabel={t('tasks.confirm_delete')}
        cancelLabel={t('common.cancel')}
        isBusy={isDeleting}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}

function TaskStatusIcon({ status }: { status: ManagedTaskStatus }) {
  const iconClass = status === 'success' ? 'text-green-300' : status === 'failed' ? 'text-red-300' : status === 'pending' ? 'text-amber-300' : 'text-white/65';
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-black/20">
      {status === 'success' ? <Check size={15} className={iconClass} /> : status === 'failed' ? <X size={15} className={iconClass} /> : <Activity size={15} className={cn(iconClass, status === 'running' && 'animate-spin-slow')} />}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-[10px] font-black uppercase tracking-[0.2em] text-white/30">{label}</span>
      {children}
    </label>
  );
}

function Meta({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn('rounded-lg border border-white/8 bg-black/15 p-3', wide && 'col-span-2')}>
      <div className="mb-1 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{label}</div>
      <div className="break-all font-mono text-[11px] text-white/55">{value}</div>
    </div>
  );
}
