import { useCallback, useState } from 'react';

export interface MemoryTierStats {
  count: number;
  description?: string;
  reliable_count?: number;
}

export interface MemoryTiers {
  l1_trace: MemoryTierStats;
  l2_policy: MemoryTierStats;
  l3_world_model: MemoryTierStats;
  crystallized_skills: MemoryTierStats & { reliable_count?: number };
}

export interface CrystallizedSkill {
  id: string;
  name: string;
  description: string;
  eta: number;
  usage_count: number;
  success_count: number;
  provenance: string;
  created_at: string;
  updated_at: string;
}

export interface MemoryStatus {
  initialized: boolean;
  neo4j_connected: boolean;
  embedding_provider: string | null;
  embedding_dimensions: number | null;
}

export interface MemoryState {
  tiers: MemoryTiers | null;
  skills: CrystallizedSkill[];
  status: MemoryStatus | null;
  selectedSkill: CrystallizedSkill | null;
}

export function useMemory(call: (method: string, params?: any) => Promise<any>) {
  const [tiers, setTiers] = useState<MemoryTiers | null>(null);
  const [skills, setSkills] = useState<CrystallizedSkill[]>([]);
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<CrystallizedSkill | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMemoryTiers = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result: any = await call('list_memory_tiers');
      if (result?.error) {
        throw new Error(result.error);
      }
      setTiers(result?.tiers || null);
      setStatus(result?.memory_status || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, [call]);

  const loadSkills = useCallback(async (minEta?: number) => {
    setIsLoadingSkills(true);
    setError(null);
    try {
      const result: any = await call('list_skill_crystals', minEta !== undefined ? { min_eta: minEta } : {});
      if (result?.error) {
        throw new Error(result.error);
      }
      setSkills(result?.skills || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoadingSkills(false);
    }
  }, [call]);

  const selectSkill = useCallback(async (skillId: string) => {
    setError(null);
    try {
      const result: any = await call('get_skill_crystal', { skill_id: skillId });
      if (result?.error) {
        throw new Error(result.error);
      }
      setSelectedSkill(result?.skill || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [call]);

  const triggerConsolidation = useCallback(async () => {
    setError(null);
    try {
      const result: any = await call('trigger_memory_consolidation');
      if (result?.status === 'error') {
        throw new Error(result.message);
      }
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, [call]);

  const recordSkillUsage = useCallback(async (skillId: string, success: boolean) => {
    const result: any = await call('record_skill_usage', { skill_id: skillId, success });
    if (result?.status === 'error') {
      throw new Error(result.message);
    }
    return result;
  }, [call]);

  return {
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
    recordSkillUsage,
  };
}
