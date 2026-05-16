import React, { useState, useEffect } from 'react';
import { Cpu, RefreshCw } from 'lucide-react';
import { RefreshIconButton } from '../components/RefreshIconButton';
import { skillsApi, type SkillSummary } from '../api/skills';

interface SkillsViewProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

export function SkillsView({ call, isConnected, t }: SkillsViewProps) {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);

  const normalizeSkillsPayload = (payload: any): SkillSummary[] => {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.skills)) return payload.skills;
    return [];
  };

  const refreshSkills = async () => {
    if (!isConnected) return;
    setIsLoadingSkills(true);
    try {
      const result = await call('list_skills');
      setSkills(normalizeSkillsPayload(result));
    } catch (error) {
      console.error('Failed to load skills:', error);
      setSkills([]);
    } finally {
      setIsLoadingSkills(false);
    }
  };

  useEffect(() => {
    if (isConnected) refreshSkills();
  }, [isConnected]);

  return (
    <div className="flex-1 overflow-y-auto p-12 custom-scrollbar">
      <div className="max-w-5xl mx-auto space-y-12 pb-20">
        <header className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-4xl font-black tracking-tight mb-2">{t('skills.title')}</h2>
            <p className="text-sm text-white/30 font-medium">{t('skills.subtitle')}</p>
          </div>
          <RefreshIconButton
            onClick={() => refreshSkills()}
            isLoading={isLoadingSkills}
            label={t('skills.refresh')}
          />
        </header>

        <div className="space-y-4">
          {isLoadingSkills && skills.length === 0 ? (
            <div className="p-20 text-center glass rounded-[3rem] border border-white/5">
              <RefreshCw size={48} className="mx-auto text-white/10 mb-6 animate-spin" />
              <p className="text-white/30 font-bold uppercase tracking-widest text-sm">{t('skills.loading')}</p>
            </div>
          ) : skills.length === 0 ? (
            <div className="p-20 text-center glass rounded-[3rem] border border-white/5">
              <Cpu size={48} className="mx-auto text-white/5 mb-6" />
              <p className="text-white/20 font-bold uppercase tracking-widest text-sm">{t('skills.empty')}</p>
            </div>
          ) : (
            skills.map((skill) => (
              <div key={skill.name} className="glass rounded-[2rem] p-8 border border-white/10 space-y-4">
                <div className="flex items-start justify-between gap-6">
                  <div className="space-y-2">
                    <h3 className="text-xl font-bold tracking-tight">{skill.name}</h3>
                    <p className="text-sm text-white/60 leading-relaxed">{skill.description}</p>
                  </div>
                  <div className="shrink-0 text-right text-xs text-white/35 space-y-1 font-medium">
                    <div>{t('skills.version')}: {skill.version || '0.1.0'}</div>
                    <div>{t('skills.author')}: {skill.author || t('skills.unknown_author')}</div>
                    <div>{t('skills.created')}: {skill.created || t('skills.unknown_date')}</div>
                    <div>{t('skills.updated')}: {skill.updated || t('skills.unknown_date')}</div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
