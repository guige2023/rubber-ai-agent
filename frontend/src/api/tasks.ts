import { invoke } from '@tauri-apps/api/core';

export const tasksApi = {
  listTasks: () => invoke<any[]>('list_tasks'),
  createTask: (params: any) => invoke<any>('create_task', params),
  updateTask: (taskId: string, params: any) =>
    invoke('update_task', { task_id: taskId, ...params }),
  deleteTask: (taskId: string) => invoke('delete_task', { task_id: taskId }),
};
