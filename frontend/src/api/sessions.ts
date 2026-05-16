import { invoke } from '@tauri-apps/api/core';
import type { Session } from '../hooks/useSessions';

export interface ListMessagesParams {
  session_id: string;
  limit?: number;
  before?: string;
  [key: string]: unknown;
}

export interface ListMessagesResponse {
  messages: any[];
}

export const sessionsApi = {
  listSessions: () => invoke<Session[]>('list_sessions'),

  createSession: (title?: string) =>
    invoke<{ session_id: string }>('create_session', { title }).then((r) => r.session_id),

  renameSession: (sessionId: string, title: string) =>
    invoke('rename_session', { session_id: sessionId, title }),

  deleteSession: (sessionId: string) =>
    invoke('delete_session', { session_id: sessionId }),

  listMessages: (params: ListMessagesParams) =>
    invoke<ListMessagesResponse>('list_messages', params),

  sendMessage: (content: string, parent_message_id?: string) =>
    invoke<{ status: string; run_id?: string }>('send_message', {
      content,
      parent_message_id,
    }),

  cancelRun: (runId: string) =>
    invoke('cancel_run', { run_id: runId }),
};
