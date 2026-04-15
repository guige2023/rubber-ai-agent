import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { useBackendConnection, type ToolActivityPayload } from './hooks/useBackendConnection';
import { useSessions, type Message } from './hooks/useSessions';
import { useI18n } from './hooks/useI18n';

vi.mock('./hooks/useBackendConnection', () => ({
  useBackendConnection: vi.fn(),
}));

vi.mock('./hooks/useSessions', () => ({
  useSessions: vi.fn(),
}));

vi.mock('./hooks/useI18n', () => ({
  useI18n: vi.fn(),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));

vi.mock('@tauri-apps/plugin-opener', () => ({
  openUrl: vi.fn(),
}));

const mockedUseBackendConnection = vi.mocked(useBackendConnection);
const mockedUseSessions = vi.mocked(useSessions);
const mockedUseI18n = vi.mocked(useI18n);

let mockedMessages: Message[] = [];
let mockedToolActivities: ToolActivityPayload[] = [];
const clipboardWriteText = vi.fn();
const scrollIntoView = vi.fn();

describe('App chat interactions', () => {
  beforeEach(() => {
    mockedMessages = [];
    mockedToolActivities = [];
    clipboardWriteText.mockReset();
    scrollIntoView.mockReset();

    const storage = new Map<string, string>();
    const localStorageMock = {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        storage.set(key, String(value));
      }),
      removeItem: vi.fn((key: string) => {
        storage.delete(key);
      }),
      clear: vi.fn(() => {
        storage.clear();
      }),
    };

    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: clipboardWriteText.mockResolvedValue(undefined),
      },
    });

    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());

    mockedUseI18n.mockReturnValue({
      locale: 'en',
      changeLanguage: vi.fn(),
      t: (key: string) =>
        (
          {
            'app.title': 'Ferryman',
            'app.subtitle': 'Busywork, handled.',
            'chat.header_title': 'Chat',
            'chat.placeholder': 'Prompt',
            'chat.send_shortcut_enter_hint': 'Enter to send',
            'chat.send_shortcut_mod_enter_hint': 'Send with Cmd/Ctrl + Enter',
            'common.copy': 'Copy',
            'common.copied': 'Copied',
            'nav.recent_sessions': 'Recent Sessions',
            'nav.new_chat': 'New Chat',
            'nav.tasks': 'Tasks',
            'nav.schedules': 'Schedules',
            'nav.skills': 'Skills',
            'nav.settings': 'Settings',
            'tasks.tokens_unit': 'Tokens',
            'tasks.token_in': 'IN',
            'tasks.token_out': 'OUT',
            'tasks.token_total': 'TOT',
            'chat.send_mode': 'Send mode',
            'settings.no_models': 'No models',
            'app.byok_enabled': 'BYOK',
            'app.deterministic_kernel': 'Kernel',
          } as Record<string, string>
        )[key] ?? key,
    });

    mockedUseBackendConnection.mockImplementation(() => ({
      call: vi.fn(),
      execute: vi.fn(),
      isConnected: false,
      tasks: [],
      toolActivities: mockedToolActivities,
      lastEvent: null,
      refreshTasks: vi.fn(),
      clearToolActivities: vi.fn(),
    }));

    mockedUseSessions.mockImplementation(() => ({
      messages: mockedMessages,
      setMessages: vi.fn(),
      sessions: [
        {
          id: 'session-1',
          title: 'Session 1',
          updated_at: '2026-04-15T00:00:00Z',
          input_tokens: 0,
          output_tokens: 0,
        },
      ],
      currentSessionId: 'session-1',
      currentUsage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      refreshSessions: vi.fn(),
      switchSession: vi.fn(),
      createNewSession: vi.fn().mockResolvedValue('session-2'),
      deleteSession: vi.fn(),
      execute: vi.fn(),
      isExecuting: false,
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('copies both user and assistant bubbles', async () => {
    const now = new Date();
    const todayMessageAt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 19, 27, 0, 0);
    const olderMessageAt = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 8, 5, 0, 0);
    const expectedTodayLabel = '19:27';
    const expectedOlderLabel = `${olderMessageAt.getFullYear()}/${String(olderMessageAt.getMonth() + 1).padStart(2, '0')}/${String(olderMessageAt.getDate()).padStart(2, '0')} 08:05`;

    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Need a copy.', created_at: todayMessageAt.toISOString() },
      { id: 'assistant-1', role: 'assistant', content: 'Here is the copied result.', created_at: olderMessageAt.toISOString() },
    ];

    render(<App />);

    const copyButtons = await screen.findAllByRole('button', { name: 'Copy' });
    expect(copyButtons).toHaveLength(2);
    expect(screen.getByText(expectedTodayLabel)).toBeInTheDocument();
    expect(screen.getByText(expectedOlderLabel)).toBeInTheDocument();

    fireEvent.click(copyButtons[0]);
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenNthCalledWith(1, 'Need a copy.');
    });

    fireEvent.click(copyButtons[1]);
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenNthCalledWith(2, 'Here is the copied result.');
    });
  });

  it('auto-scrolls when message content or tool events update', async () => {
    const baseTime = new Date().toISOString();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: baseTime },
      { id: 'assistant-1', role: 'assistant', content: '', created_at: baseTime, metadata: { state: 'pending' } },
    ];

    const { rerender } = render(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalled();
    });

    scrollIntoView.mockClear();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: baseTime },
      { id: 'assistant-1', role: 'assistant', content: 'Partial output arrived.', created_at: baseTime, metadata: { state: 'pending' } },
    ];
    rerender(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
    });

    scrollIntoView.mockClear();
    mockedToolActivities = [
      {
        run_id: 'run-1',
        tool_name: 'reading_file',
        phase: 'running',
        input: { path: '/tmp/report.md' },
      },
    ];
    rerender(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
    });
  });
});
