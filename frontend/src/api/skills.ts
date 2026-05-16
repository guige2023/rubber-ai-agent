import { invoke } from '@tauri-apps/api/core';

export type SkillSummary = {
  name: string;
  description: string;
  version: string;
  author: string;
  created?: string | null;
  updated?: string | null;
};

export const skillsApi = {
  listSkills: () => invoke<{ skills?: SkillSummary[] } | SkillSummary[]>('list_skills'),
};
