import { invoke } from '@tauri-apps/api/core';

export const systemApi = {
  getBackendLogs: (source: 'app' | 'sidecar', lines = 160) =>
    invoke<{ content: string }>('read_backend_logs', { source, lines }),

  getBrowserRuntimeStatus: () => invoke<any>('get_browser_runtime_status'),

  reportSmokeStatus: (status: string) =>
    invoke('report_frontend_smoke_status', { status }),
};
