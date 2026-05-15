import { useEffect, useState, useMemo, type ReactNode } from 'react';
import { CalendarClock, Check, ChevronRight, Power, Save, Trash2, Calendar, List, AlertTriangle, Timer } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import { RefreshIconButton } from './RefreshIconButton';
import { SideDrawer } from './SideDrawer';
import { Schedule, useSchedules } from '../hooks/useSchedules';
import { cn } from '../utils/cn';

interface ScheduleManagerProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

function formatDate(value?: string | null, timezone?: string) {
  if (!value) return '-';
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: timezone || undefined,
    }).format(new Date(value));
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value));
  }
}

// Calculate countdown to next run
function getCountdown(nextRunAt?: string | null): string {
  if (!nextRunAt) return '-';
  try {
    const now = Date.now();
    const next = new Date(nextRunAt).getTime();
    const diff = next - now;
    if (diff < 0) return 'Overdue';
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    if (hours > 24) {
      const days = Math.floor(hours / 24);
      return `${days}d ${hours % 24}h`;
    }
    return `${hours}h ${minutes}m`;
  } catch {
    return '-';
  }
}

function getLastRunHeadline(schedule: Schedule, t: (key: string) => string) {
  const lastRun = schedule.last_run_result;
  if (!lastRun) return null;
  return lastRun.status === 'failed' ? t('schedules.last_run_failed') : t('schedules.last_run_succeeded');
}

function scheduleInstruction(schedule: Schedule) {
  return typeof schedule.args?.instruction === 'string' ? schedule.args.instruction : '';
}

export function ScheduleManager({ call, isConnected, t }: ScheduleManagerProps) {
  const {
    schedules,
    selectedSchedule,
    setSelectedSchedule,
    nextCursor,
    isLoading,
    isLoadingMore,
    error,
    loadSchedules,
    selectSchedule,
    updateSchedule,
    deleteSchedule,
  } = useSchedules(call);
  const [draft, setDraft] = useState<Schedule | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Schedule | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [viewMode, setViewMode] = useState<'list' | 'calendar'>('list');
  const [highlightFailuresOnly, setHighlightFailuresOnly] = useState(false);
  const [currentMonth, setCurrentMonth] = useState(() => new Date());

  // Countdown ticker
  const [countdownTick, setCountdownTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setCountdownTick(t => t + 1), 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  // Filter schedules
  const filteredSchedules = useMemo(() => {
    if (!highlightFailuresOnly) return schedules;
    return schedules.filter(s => s.last_run_result?.status === 'failed');
  }, [schedules, highlightFailuresOnly]);

  // Group schedules by day for calendar view
  const calendarDays = useMemo(() => {
    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const days: { date: Date; schedules: Schedule[] }[] = [];

    // Add days from previous month to fill the first week
    const startPadding = firstDay.getDay();
    for (let i = startPadding - 1; i >= 0; i--) {
      const date = new Date(year, month, -i);
      days.push({ date, schedules: [] });
    }

    // Add days of current month
    for (let d = 1; d <= lastDay.getDate(); d++) {
      const date = new Date(year, month, d);
      const daySchedules = filteredSchedules.filter(s => {
        if (!s.next_run_at) return false;
        const nextRun = new Date(s.next_run_at);
        return nextRun.getFullYear() === year && nextRun.getMonth() === month && nextRun.getDate() === d;
      });
      days.push({ date, schedules: daySchedules });
    }

    // Add days from next month to fill the last week
    const endPadding = 6 - lastDay.getDay();
    for (let i = 1; i <= endPadding; i++) {
      const date = new Date(year, month + 1, i);
      days.push({ date, schedules: [] });
    }

    return days;
  }, [filteredSchedules, currentMonth, countdownTick]);

  // Get recent failures (last 24 hours)
  const recentFailures = useMemo(() => {
    const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
    return schedules.filter(s =>
      s.last_run_result?.status === 'failed' &&
      s.last_run_at &&
      new Date(s.last_run_at).getTime() > dayAgo
    );
  }, [schedules]);

  useEffect(() => {
    if (isConnected) {
      loadSchedules();
    }
  }, [isConnected, loadSchedules]);

  useEffect(() => {
    setDraft(selectedSchedule);
    setFormError(null);
  }, [selectedSchedule]);

  const handleSave = async () => {
    if (!draft) return;
    setIsSaving(true);
    setFormError(null);
    try {
      await updateSchedule(draft);
      setSelectedSchedule(null);
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
      await deleteSchedule(deleteTarget.id);
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
            <h2 className="text-4xl font-black tracking-tight">{t('schedules.title')}</h2>
            <p className="mt-2 text-sm font-medium text-white/32">{t('schedules.subtitle')}</p>
          </div>
          <div className="flex items-center gap-3">
            {/* Recent Failures Alert */}
            {recentFailures.length > 0 && (
              <button
                onClick={() => setHighlightFailuresOnly(!highlightFailuresOnly)}
                className={cn(
                  'flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-black transition-colors',
                  highlightFailuresOnly
                    ? 'border-red-400/40 bg-red-500/20 text-red-200'
                    : 'border-red-400/20 bg-red-500/10 text-red-300 hover:bg-red-500/20'
                )}
              >
                <AlertTriangle size={14} />
                {recentFailures.length} {t('schedules.recent_failures') || 'Recent Failures'}
              </button>
            )}
            <RefreshIconButton
              onClick={() => loadSchedules()}
              disabled={!isConnected || isLoading}
              isLoading={isLoading}
              label={t('schedules.refresh')}
            />

            {/* View Toggle */}
            <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-1">
              <button
                onClick={() => setViewMode('list')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-black transition-colors',
                  viewMode === 'list' ? 'bg-white text-black' : 'text-white/50 hover:text-white'
                )}
              >
                <List size={14} className="inline mr-1" />
                {t('schedules.view_list') || 'List'}
              </button>
              <button
                onClick={() => setViewMode('calendar')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-black transition-colors',
                  viewMode === 'calendar' ? 'bg-white text-black' : 'text-white/50 hover:text-white'
                )}
              >
                <Calendar size={14} className="inline mr-1" />
                {t('schedules.view_calendar') || 'Calendar'}
              </button>
            </div>
          </div>
        </header>

        {/* Calendar Navigation (only in calendar view) */}
        {viewMode === 'calendar' && (
          <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <button
              onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1))}
              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white/70 hover:bg-white/[0.06] transition-colors"
            >
              ←
            </button>
            <div className="text-sm font-black text-white/70">
              {currentMonth.toLocaleDateString(undefined, { year: 'numeric', month: 'long' })}
            </div>
            <button
              onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1))}
              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white/70 hover:bg-white/[0.06] transition-colors"
            >
              →
            </button>
          </div>
        )}

        <section className="min-h-0 flex-1 overflow-hidden rounded-xl border border-white/8 bg-white/[0.02]">
          <div className="flex h-full flex-col">
            <div className="grid grid-cols-[minmax(0,1fr)_120px_140px_140px_32px] items-center gap-3 border-b border-white/8 px-5 py-3 text-[10px] font-black uppercase tracking-[0.18em] text-white/28">
              <span>{t('schedules.list_title')}</span>
              <span>{t('schedules.field_cron')}</span>
              <span>{t('schedules.field_next_run')}</span>
              <span>{t('schedules.field_last_run')}</span>
              <span />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
              {error && <div className="m-4 rounded-lg border border-red-400/20 bg-red-500/10 p-3 text-xs text-red-100">{error}</div>}
              {filteredSchedules.length === 0 && !isLoading ? (
                <div className="flex h-full flex-col items-center justify-center p-10 text-center">
                  <CalendarClock size={34} className="mb-4 text-white/8" />
                  <p className="text-sm font-bold text-white/25">{t('schedules.empty')}</p>
                </div>
              ) : viewMode === 'list' ? (
                filteredSchedules.map((schedule) => {
                  const hasRecentFailure = schedule.last_run_result?.status === 'failed' &&
                    schedule.last_run_at &&
                    new Date(schedule.last_run_at).getTime() > Date.now() - 24 * 60 * 60 * 1000;
                  return (
                    <button
                      key={schedule.id}
                      onClick={() => selectSchedule(schedule.id)}
                      className={cn(
                        'group grid min-h-[72px] w-full grid-cols-[minmax(0,1fr)_120px_140px_100px_140px_32px] items-center gap-3 border-b border-white/6 px-5 py-3 text-left transition-colors hover:bg-white/[0.045]',
                        selectedSchedule?.id === schedule.id && 'bg-white/[0.055]',
                        hasRecentFailure && 'border-l-2 border-l-red-400/50'
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-4">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-black/20">
                          <Power size={15} className={schedule.enabled ? 'text-green-300' : 'text-white/28'} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <h3 className={cn('truncate text-sm font-black tracking-tight', hasRecentFailure ? 'text-red-200' : 'text-white/84')}>
                              {schedule.name}
                            </h3>
                            <span className={cn(
                              'shrink-0 rounded-md border px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.14em]',
                              schedule.enabled ? 'border-green-400/20 text-green-300' : 'border-white/10 text-white/35'
                            )}>
                              {schedule.enabled ? t('schedules.enabled') : t('schedules.disabled')}
                            </span>
                            {hasRecentFailure && (
                              <span className="shrink-0 rounded-md border border-red-400/30 bg-red-500/10 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-[0.1em] text-red-300">
                                <AlertTriangle size={10} className="inline mr-1" />
                                Failed
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <span className="truncate font-mono text-[11px] text-white/38">{schedule.cron_expression}</span>
                      <div className="flex flex-col">
                        <span className="font-mono text-[10px] text-white/28">{formatDate(schedule.next_run_at, schedule.timezone)}</span>
                        <span className="flex items-center gap-1 font-mono text-[9px] text-white/20">
                          <Timer size={9} />
                          {getCountdown(schedule.next_run_at)}
                        </span>
                      </div>
                      <span className="font-mono text-[10px] text-white/28">{formatDate(schedule.last_run_at, schedule.timezone)}</span>
                      <ChevronRight size={15} className="justify-self-end text-white/18 transition-transform group-hover:translate-x-0.5 group-hover:text-white/45" />
                    </button>
                  );
                })
              ) : (
                // Calendar view
                <div className="p-4">
                  {/* Calendar header */}
                  <div className="grid grid-cols-7 gap-2 mb-4">
                    {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
                      <div key={day} className="text-center text-[10px] font-black uppercase tracking-[0.1em] text-white/30">{day}</div>
                    ))}
                  </div>
                  {/* Calendar grid */}
                  <div className="grid grid-cols-7 gap-2">
                    {calendarDays.map(({ date, schedules: daySchedules }, idx) => {
                      const isToday = date.toDateString() === new Date().toDateString();
                      const isCurrentMonth = date.getMonth() === currentMonth.getMonth();
                      return (
                        <div
                          key={idx}
                          className={cn(
                            'min-h-[80px] rounded-lg border p-2 transition-colors',
                            isToday ? 'border-white/30 bg-white/[0.05]' : 'border-white/5',
                            !isCurrentMonth && 'opacity-30'
                          )}
                        >
                          <div className={cn(
                            'mb-1 text-xs font-black',
                            isToday ? 'text-white' : 'text-white/40'
                          )}>
                            {date.getDate()}
                          </div>
                          {daySchedules.slice(0, 3).map(schedule => (
                            <button
                              key={schedule.id}
                              onClick={() => selectSchedule(schedule.id)}
                              className={cn(
                                'mb-1 w-full truncate rounded px-1.5 py-0.5 text-[9px] font-black text-left transition-colors hover:brightness-125',
                                schedule.enabled
                                  ? schedule.last_run_result?.status === 'failed'
                                    ? 'bg-red-500/30 text-red-200'
                                    : 'bg-green-500/20 text-green-200'
                                  : 'bg-white/5 text-white/40'
                              )}
                            >
                              {schedule.name}
                            </button>
                          ))}
                          {daySchedules.length > 3 && (
                            <div className="text-[9px] text-white/30">+{daySchedules.length - 3} more</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            {nextCursor && (
              <button
                onClick={() => loadSchedules({ append: true, cursor: nextCursor })}
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
        title={t('schedules.detail_title')}
        subtitle={draft ? formatDate(draft.updated_at, draft.timezone) : undefined}
        onClose={() => setSelectedSchedule(null)}
      >
        {draft && (
          <div className="space-y-5">
            <div className="flex items-center justify-between gap-3 border-b border-white/8 pb-5">
              <button
                onClick={() => setDeleteTarget(draft)}
                className="inline-flex items-center gap-2 rounded-lg border border-red-400/20 px-4 py-2 text-xs font-black text-red-200 transition-colors hover:bg-red-500/15"
              >
                <Trash2 size={14} />
                {t('common.delete')}
              </button>
              <button
                onClick={handleSave}
                disabled={isSaving}
                className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-xs font-black text-[#080808] transition-colors hover:bg-white/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Save size={14} />
                {isSaving ? t('common.saving') : t('common.save')}
              </button>
            </div>
            <Field label={t('schedules.field_name')}>
              <input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className="field-input" />
            </Field>
            <Field label={t('schedules.field_cron')}>
              <input value={draft.cron_expression} onChange={(event) => setDraft({ ...draft, cron_expression: event.target.value })} className="field-input font-mono" />
              <p className="mt-2 text-[11px] font-medium text-white/28">{t('schedules.cron_hint')}</p>
            </Field>
            <Field label={t('schedules.field_instruction')}>
              <textarea
                value={scheduleInstruction(draft)}
                onChange={(event) => setDraft({
                  ...draft,
                  args: { ...draft.args, instruction: event.target.value },
                })}
                className="field-textarea min-h-[180px]"
              />
            </Field>
            <Field label={t('schedules.field_enabled')}>
              <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.05]">
                <div>
                  <div className="text-sm font-bold text-white/84">
                    {t('schedules.enabled')}
                  </div>
                </div>
                <span
                  className={cn(
                    'flex h-6 w-6 items-center justify-center rounded-md border transition-colors',
                    draft.enabled
                      ? 'border-green-400/30 bg-green-500/15 text-green-200'
                      : 'border-white/14 bg-black/20 text-transparent'
                  )}
                >
                  <Check size={14} />
                </span>
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
                  className="sr-only"
                  aria-label={t('schedules.field_enabled')}
                />
              </label>
            </Field>
            <Field label={t('schedules.field_timezone')}>
              <input value={draft.timezone} onChange={(event) => setDraft({ ...draft, timezone: event.target.value })} className="field-input font-mono" />
              <p className="mt-2 text-[11px] font-medium text-white/28">{t('schedules.timezone_hint')}</p>
            </Field>
            <div className="grid grid-cols-2 gap-3 text-xs text-white/35">
              <Meta label={t('schedules.field_last_run')} value={formatDate(draft.last_run_at, draft.timezone)} />
              <Meta label={t('schedules.field_next_run')} value={formatDate(draft.next_run_at, draft.timezone)} />
              <Meta label={t('schedules.field_timezone')} value={draft.timezone} />
              <Meta label={t('schedules.field_total_runs')} value={String(draft.total_run_count)} />
              <Meta label={t('schedules.field_created_at')} value={formatDate(draft.created_at, draft.timezone)} />
              <Meta label={t('schedules.field_updated_at')} value={formatDate(draft.updated_at, draft.timezone)} />
              <Meta label={t('tasks.identifier')} value={draft.id} wide />
            </div>
            {draft.last_run_result && (
              <div className={cn(
                'space-y-3 rounded-lg border p-4',
                draft.last_run_result.status === 'failed'
                  ? 'border-red-400/20 bg-red-500/10'
                  : 'border-emerald-400/20 bg-emerald-500/10'
              )}>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.2em] text-white/35">
                    {t('schedules.field_last_run_result')}
                  </div>
                  <div className="mt-2 text-sm font-bold text-white">
                    {getLastRunHeadline(draft, t)}
                  </div>
                  {draft.last_run_result.finished_at && (
                    <div className="mt-1 text-xs font-medium text-white/45">
                      {formatDate(draft.last_run_result.finished_at, draft.timezone)}
                    </div>
                  )}
                </div>
                {draft.last_run_result.summary && (
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-white/30">
                      {t('schedules.field_last_run_summary')}
                    </div>
                    <p className="mt-1 text-sm leading-6 text-white/70">{draft.last_run_result.summary}</p>
                  </div>
                )}
                {draft.last_run_result.error && (
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-white/30">
                      {t('schedules.field_last_run_error')}
                    </div>
                    <p className="mt-1 break-words text-sm leading-6 text-red-100">{draft.last_run_result.error}</p>
                  </div>
                )}
                {draft.last_run_result.run_id && (
                  <Meta label={t('schedules.field_last_run_id')} value={draft.last_run_result.run_id} wide />
                )}
              </div>
            )}
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
        title={t('schedules.delete_title')}
        description={t('schedules.delete_description').replace('{name}', deleteTarget?.name || '')}
        confirmLabel={t('schedules.confirm_delete')}
        cancelLabel={t('common.cancel')}
        isBusy={isDeleting}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
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
