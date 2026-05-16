import { invoke } from '@tauri-apps/api/core';

export const memoryApi = {
  listMemories: () => invoke<any[]>('list_memories'),
  createMemory: (params: any) => invoke<any>('create_memory', params),
  updateMemory: (memoryId: string, params: any) =>
    invoke('update_memory', { memory_id: memoryId, ...params }),
  deleteMemory: (memoryId: string) => invoke('delete_memory', { memory_id: memoryId }),
  searchMemories: (query: string) => invoke<any[]>('search_memories', { query }),
};
