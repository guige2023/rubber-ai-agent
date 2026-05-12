import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { invoke } from '@tauri-apps/api/core';

import { SessionInsightsDrawer } from './SessionInsightsDrawer';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));

const t = (key: string) =>
  (
    {
      'common.loading': 'Loading',
      'insights.title': 'Session Insights',
      'insights.subtitle': 'Review token trends and memory state.',
      'insights.session_id': 'Session ID',
      'insights.session_workspace': 'Session Workspace',
      'insights.open_workspace': 'Open session workspace',
      'insights.usage_title': 'Token Usage',
      'insights.no_usage': 'No token records',
      'insights.memory_title': 'Session Memory',
      'insights.memory_subtitle': 'Memory snapshot',
      'insights.no_memory': 'No memory',
      'insights.ranges.today': 'Today',
      'insights.ranges.yesterday': 'Yesterday',
      'insights.ranges.last_7_days': 'Last 7d',
      'insights.ranges.last_30_days': 'Last 30d',
      'insights.ranges.last_90_days': 'Last 90d',
      'tasks.input_tokens': 'Input',
      'tasks.output_tokens': 'Output',
      'tasks.total_tokens': 'Total',
      'tasks.token_in': 'IN',
      'tasks.token_out': 'OUT',
      'tasks.token_total': 'TOTAL',
    } as Record<string, string>
  )[key] ?? key;

describe('SessionInsightsDrawer', () => {
  it('shows session metadata and opens the session workspace', async () => {
    const call = vi.fn().mockResolvedValue({
      session_id: 'session-123',
      session_workspace: '/Users/example/.ferryman/workspaces/session-123',
      range: {
        key: 'last_30_days',
        timezone: 'Asia/Shanghai',
        start_date: '2026-04-13',
        end_date: '2026-05-12',
        start_utc: '2026-04-12T16:00:00Z',
        end_utc: '2026-05-12T08:00:00Z',
      },
      usage: {
        daily: [],
        range_totals: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        session_totals: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        archived_totals: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        unattributed_system_usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      },
      memory: null,
    });

    render(
      <SessionInsightsDrawer
        open
        sessionId="session-123"
        isConnected
        call={call}
        onClose={vi.fn()}
        t={t}
      />
    );

    expect(await screen.findByText('session-123')).toBeInTheDocument();
    expect(screen.getByText('/Users/example/.ferryman/workspaces/session-123')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Open session workspace' }));

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_local_file', {
        path: '/Users/example/.ferryman/workspaces/session-123',
      });
    });
  });
});
