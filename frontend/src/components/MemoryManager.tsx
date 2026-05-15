import { useEffect, useMemo, useState } from 'react';
import { Brain, ChevronRight, Database, RefreshCw, Sparkles, Zap } from 'lucide-react';
import { RefreshIconButton } from './RefreshIconButton';
import { SideDrawer } from './SideDrawer';
import { useMemory } from '../hooks/useMemory';
import { cn } from '../utils/cn';

interface MemoryManagerProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
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

function formatReliability(eta: number) {
  return `${(eta * 100).toFixed(0)}%`;
}

export function MemoryManager({ call, isConnected, t }: MemoryManagerProps) {
  const {
    tiers,
    skills,
    status,
    selectedSkill,
    setSelectedSkill,
    isLoading,
    isLoadingSkills,
    error,
    loadMemoryTiers,
    loadSkills,
    selectSkill,
    triggerConsolidation,
  } = useMemory(call);

  const [isConsolidating, setIsConsolidating] = useState(false);
  const [consolidationResult, setConsolidationResult] = useState<string | null>(null);

  useEffect(() => {
    if (isConnected) {
      loadMemoryTiers();
      loadSkills();
    }
  }, [isConnected, loadMemoryTiers, loadSkills]);

  const tierItems = useMemo(() => {
    if (!tiers) return [];
    return [
      {
        key: 'l1_trace',
        icon: Database,
        label: t('memory.tier_l1') || 'L1 Trace',
        count: tiers.l1_trace?.count || 0,
        description: tiers.l1_trace?.description || 'Session traces',
        color: 'text-blue-300',
        bgColor: 'bg-blue-500/10 border-blue-500/20',
      },
      {
        key: 'l2_policy',
        icon: Brain,
        label: t('memory.tier_l2') || 'L2 Policy',
        count: tiers.l2_policy?.count || 0,
        description: tiers.l2_policy?.description || 'Induced policies',
        color: 'text-purple-300',
        bgColor: 'bg-purple-500/10 border-purple-500/20',
      },
      {
        key: 'l3_world_model',
        icon: Sparkles,
        label: t('memory.tier_l3') || 'L3 World',
        count: tiers.l3_world_model?.count || 0,
        description: tiers.l3_world_model?.description || 'World models',
        color: 'text-amber-300',
        bgColor: 'bg-amber-500/10 border-amber-500/20',
      },
      {
        key: 'crystallized_skills',
        icon: Zap,
        label: t('memory.tier_skill') || 'Skills',
        count: tiers.crystallized_skills?.count || 0,
        description: `${tiers.crystallized_skills?.reliable_count || 0} ${t('memory.reliable') || 'reliable'}`,
        color: 'text-emerald-300',
        bgColor: 'bg-emerald-500/10 border-emerald-500/20',
      },
    ];
  }, [tiers, t]);

  const handleConsolidation = async () => {
    setIsConsolidating(true);
    setConsolidationResult(null);
    try {
      const result = await triggerConsolidation();
      setConsolidationResult(result?.status || 'success');
      await loadMemoryTiers();
    } catch (err) {
      setConsolidationResult(err instanceof Error ? err.message : String(err));
    } finally {
      setIsConsolidating(false);
    }
  };

  return (
    <div className="flex-1 overflow-hidden p-8">
      <div className="mx-auto flex h-full max-w-6xl flex-col gap-6">
        <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-4xl font-black tracking-tight">{t('memory.title') || 'Memory'}</h2>
            <p className="mt-2 text-sm font-medium text-white/32">{t('memory.subtitle') || 'Layered memory system'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleConsolidation}
              disabled={!isConnected || isConsolidating}
              className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-black transition-colors hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={14} className={cn(isConsolidating && 'animate-spin')} />
              {isConsolidating ? (t('memory.consolidating') || 'Consolidating...') : (t('memory.consolidate') || 'Consolidate')}
            </button>
            <RefreshIconButton
              onClick={() => { loadMemoryTiers(); loadSkills(); }}
              disabled={!isConnected || isLoading}
              isLoading={isLoading}
              label={t('memory.refresh') || 'Refresh'}
            />
          </div>
        </header>

        {consolidationResult && (
          <div className={cn(
            'rounded-lg border p-3 text-xs',
            consolidationResult === 'success'
              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
              : 'border-red-500/20 bg-red-500/10 text-red-200'
          )}>
            {consolidationResult === 'success' ? (t('memory.consolidation_success') || 'Consolidation completed') : consolidationResult}
          </div>
        )}

        {/* Memory Tiers Grid */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {tierItems.map((item) => (
            <div key={item.key} className={cn('rounded-xl border p-5', item.bgColor)}>
              <div className="mb-3 flex items-center gap-3">
                <item.icon size={20} className={item.color} />
                <span className="text-xs font-black uppercase tracking-wider text-white/50">{item.label}</span>
              </div>
              <div className="mb-1 text-4xl font-black tabular-nums {item.color}">{item.count.toLocaleString()}</div>
              <div className="text-xs text-white/35">{item.description}</div>
            </div>
          ))}
        </section>

        {/* Status Bar */}
        {status && (
          <div className="rounded-lg border border-white/8 bg-white/[0.02] px-4 py-3 text-xs text-white/35">
            <span className="font-black uppercase tracking-wider">{t('memory.status') || 'Status'}:</span>
            <span className="ml-2">
              {status.neo4j_connected ? (
                <span className="text-emerald-300">{t('memory.neo4j_connected') || 'Neo4j Connected'}</span>
              ) : (
                <span className="text-red-300">{t('memory.neo4j_disconnected') || 'Neo4j Disconnected'}</span>
              )}
              {status.embedding_provider && (
                <span className="ml-3">
                  | {status.embedding_provider} ({status.embedding_dimensions}d)
                </span>
              )}
            </span>
          </div>
        )}

        {/* Skills List */}
        <section className="min-h-0 flex-1 overflow-hidden rounded-xl border border-white/8 bg-white/[0.02]">
          <div className="flex h-full flex-col">
            <div className="grid grid-cols-[minmax(0,1fr)_100px_100px_100px_32px] items-center gap-3 border-b border-white/8 px-5 py-3 text-[10px] font-black uppercase tracking-[0.18em] text-white/28">
              <span>{t('memory.skill_name') || 'Skill'}</span>
              <span>{t('memory.skill_reliability') || 'Reliability'}</span>
              <span>{t('memory.skill_usage') || 'Usage'}</span>
              <span>{t('memory.skill_updated') || 'Updated'}</span>
              <span />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
              {error && <div className="m-4 rounded-lg border border-red-400/20 bg-red-500/10 p-3 text-xs text-red-100">{error}</div>}
              {skills.length === 0 && !isLoadingSkills ? (
                <div className="flex h-full flex-col items-center justify-center p-10 text-center">
                  <Sparkles size={34} className="mb-4 text-white/8" />
                  <p className="text-sm font-bold text-white/25">{t('memory.no_skills') || 'No crystallized skills yet'}</p>
                </div>
              ) : (
                skills.map((skill) => (
                  <button
                    key={skill.id}
                    onClick={() => selectSkill(skill.id)}
                    className={cn(
                      'group grid w-full grid-cols-[minmax(0,1fr)_100px_100px_100px_32px] items-center gap-3 border-b border-white/6 px-5 py-3 text-left transition-colors hover:bg-white/[0.045]',
                      selectedSkill?.id === skill.id && 'bg-white/[0.055]'
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-4">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-black/20">
                        <Sparkles size={15} className="text-amber-300" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="truncate text-sm font-black tracking-tight text-white/84">{skill.name}</h3>
                        <p className="mt-1 truncate text-xs font-medium text-white/32">{skill.description || t('memory.no_description') || 'No description'}</p>
                      </div>
                    </div>
                    <span className={cn(
                      'w-fit rounded-md border px-2 py-1 text-[9px] font-black uppercase tracking-[0.14em]',
                      skill.eta >= 0.7
                        ? 'border-emerald-500/30 text-emerald-300'
                        : skill.eta >= 0.4
                        ? 'border-amber-500/30 text-amber-300'
                        : 'border-red-500/30 text-red-300'
                    )}>
                      {formatReliability(skill.eta)}
                    </span>
                    <span className="font-mono text-[10px] text-white/28">{skill.usage_count}</span>
                    <span className="font-mono text-[10px] text-white/28">{formatDate(skill.updated_at)}</span>
                    <ChevronRight size={15} className="justify-self-end text-white/18 transition-transform group-hover:translate-x-0.5 group-hover:text-white/45" />
                  </button>
                ))
              )}
            </div>
          </div>
        </section>
      </div>

      <SideDrawer
        open={Boolean(selectedSkill)}
        title={selectedSkill?.name || t('memory.skill_detail') || 'Skill Detail'}
        subtitle={selectedSkill ? formatDate(selectedSkill.updated_at) : undefined}
        onClose={() => setSelectedSkill(null)}
      >
        {selectedSkill && (
          <div className="space-y-5">
            <div className="rounded-lg border border-white/8 bg-black/15 p-4">
              <div className="mb-2 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{t('memory.skill_reliability') || 'Reliability'}</div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-black tabular-nums text-white">{formatReliability(selectedSkill.eta)}</span>
                <span className="text-xs text-white/35">
                  ({selectedSkill.success_count}/{selectedSkill.usage_count} {t('memory.successful') || 'successful'})
                </span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-amber-500 to-emerald-500"
                  style={{ width: `${selectedSkill.eta * 100}%` }}
                />
              </div>
            </div>

            <div>
              <div className="mb-2 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{t('memory.skill_description') || 'Description'}</div>
              <p className="text-sm text-white/65">{selectedSkill.description || t('memory.no_description') || 'No description'}</p>
            </div>

            <div>
              <div className="mb-2 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{t('memory.skill_provenance') || 'Provenance'}</div>
              <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-xs text-white/55">
                {selectedSkill.provenance}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs text-white/35">
              <div className="rounded-lg border border-white/8 bg-black/15 p-3">
                <div className="mb-1 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{t('memory.skill_created') || 'Created'}</div>
                <div className="font-mono text-[11px] text-white/55">{formatDate(selectedSkill.created_at)}</div>
              </div>
              <div className="rounded-lg border border-white/8 bg-black/15 p-3">
                <div className="mb-1 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{t('memory.skill_usage_count') || 'Usage Count'}</div>
                <div className="font-mono text-[11px] text-white/55">{selectedSkill.usage_count}</div>
              </div>
            </div>

            <div className="rounded-lg border border-white/8 bg-black/15 p-3">
              <div className="mb-1 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{t('memory.skill_id') || 'ID'}</div>
              <div className="break-all font-mono text-[10px] text-white/35">{selectedSkill.id}</div>
            </div>
          </div>
        )}
      </SideDrawer>
    </div>
  );
}
