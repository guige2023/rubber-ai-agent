import { invoke } from '@tauri-apps/api/core';

export const schedulesApi = {
  listSchedules: () => invoke<any[]>('list_schedules'),
  createSchedule: (params: any) => invoke<any>('create_schedule', params),
  updateSchedule: (scheduleId: string, params: any) =>
    invoke('update_schedule', { schedule_id: scheduleId, ...params }),
  deleteSchedule: (scheduleId: string) =>
    invoke('delete_schedule', { schedule_id: scheduleId }),
};
