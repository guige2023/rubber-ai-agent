import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { ScheduleManager } from './ScheduleManager';
import { useSchedules, type Schedule } from '../hooks/useSchedules';

vi.mock('../hooks/useSchedules', () => ({
  useSchedules: vi.fn(),
}));

const mockedUseSchedules = vi.mocked(useSchedules);

function buildSchedule(): Schedule {
  return {
    id: 'schedule-1',
    name: 'Morning sync',
    cron: '0 8 * * *',
    timezone: 'Asia/Shanghai',
    enabled: true,
    instruction: 'Run the morning sync.',
    last_run_at: '2026-04-15T00:00:00+00:00',
    next_run_at: '2026-04-16T00:00:00+00:00',
    total_run_count: 7,
    last_run_result: {
      status: 'failed',
      summary: null,
      error: 'OpenAI API timeout',
      run_id: 'run-xyz',
      finished_at: '2026-04-15T00:03:00+00:00',
    },
    created_at: '2026-04-14T00:00:00+00:00',
    updated_at: '2026-04-15T00:00:00+00:00',
  };
}

describe('ScheduleManager', () => {
  it('shows timezone and total run count in schedule details', () => {
    const schedule = buildSchedule();
    mockedUseSchedules.mockReturnValue({
      schedules: [schedule],
      selectedSchedule: schedule,
      setSelectedSchedule: vi.fn(),
      nextCursor: null,
      isLoading: false,
      isLoadingMore: false,
      error: null,
      loadSchedules: vi.fn(),
      selectSchedule: vi.fn(),
      updateSchedule: vi.fn(),
      deleteSchedule: vi.fn(),
    });

    render(
      <ScheduleManager
        call={vi.fn()}
        isConnected
        t={(key) =>
          ({
            'schedules.title': 'Schedules',
            'schedules.subtitle': 'Subtitle',
            'schedules.refresh': 'Refresh Schedules',
            'schedules.list_title': 'Schedule List',
            'schedules.field_cron': 'Cron Expression',
            'schedules.field_next_run': 'Next Run',
            'schedules.field_last_run': 'Last Run',
            'schedules.empty': 'Empty',
            'schedules.enabled': 'Enabled',
            'schedules.disabled': 'Paused',
            'schedules.no_instruction': 'No instruction',
            'schedules.detail_title': 'Schedule Details',
            'schedules.field_name': 'Name',
            'schedules.timezone_hint': 'Timezone hint',
            'schedules.field_timezone': 'Timezone',
            'schedules.field_instruction': 'Instruction',
            'schedules.field_total_runs': 'Total Runs',
            'schedules.field_last_run_result': 'Last Run Result',
            'schedules.field_last_run_summary': 'Summary',
            'schedules.field_last_run_error': 'Error',
            'schedules.field_last_run_id': 'Run ID',
            'schedules.field_created_at': 'Created',
            'schedules.field_updated_at': 'Updated',
            'schedules.last_run_succeeded': 'The last run completed successfully',
            'schedules.last_run_failed': 'The last run failed',
            'tasks.identifier': 'Identifier',
            'common.delete': 'Delete',
            'common.saving': 'Saving',
            'common.save': 'Save',
            'schedules.delete_title': 'Delete Schedule?',
            'schedules.delete_description': '{name}',
            'schedules.confirm_delete': 'Delete Schedule',
            'common.cancel': 'Cancel',
            'schedules.cron_hint': 'Cron hint',
            'common.loading': 'Loading',
            'common.load_more': 'Load more',
          } as Record<string, string>)[key] ?? key
        }
      />
    );

    expect(screen.getByDisplayValue('Asia/Shanghai')).toBeInTheDocument();
    expect(screen.getByText('Total Runs')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('The last run failed')).toBeInTheDocument();
    expect(screen.getByText('OpenAI API timeout')).toBeInTheDocument();
    expect(screen.getByText('run-xyz')).toBeInTheDocument();
  });

  it('formats schedule timestamps with the schedule timezone', () => {
    const schedule = buildSchedule();
    mockedUseSchedules.mockReturnValue({
      schedules: [schedule],
      selectedSchedule: schedule,
      setSelectedSchedule: vi.fn(),
      nextCursor: null,
      isLoading: false,
      isLoadingMore: false,
      error: null,
      loadSchedules: vi.fn(),
      selectSchedule: vi.fn(),
      updateSchedule: vi.fn(),
      deleteSchedule: vi.fn(),
    });

    const dateTimeFormatSpy = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation((_locale, options) => ({
      format: () => `formatted:${String(options?.timeZone ?? 'local')}`,
    }) as Intl.DateTimeFormat);

    render(
      <ScheduleManager
        call={vi.fn()}
        isConnected
        t={(key) =>
          ({
            'schedules.title': 'Schedules',
            'schedules.subtitle': 'Subtitle',
            'schedules.refresh': 'Refresh Schedules',
            'schedules.list_title': 'Schedule List',
            'schedules.field_cron': 'Cron Expression',
            'schedules.field_next_run': 'Next Run',
            'schedules.field_last_run': 'Last Run',
            'schedules.empty': 'Empty',
            'schedules.enabled': 'Enabled',
            'schedules.disabled': 'Paused',
            'schedules.no_instruction': 'No instruction',
            'schedules.detail_title': 'Schedule Details',
            'schedules.field_name': 'Name',
            'schedules.timezone_hint': 'Timezone hint',
            'schedules.field_timezone': 'Timezone',
            'schedules.field_instruction': 'Instruction',
            'schedules.field_total_runs': 'Total Runs',
            'schedules.field_last_run_result': 'Last Run Result',
            'schedules.field_last_run_summary': 'Summary',
            'schedules.field_last_run_error': 'Error',
            'schedules.field_last_run_id': 'Run ID',
            'schedules.field_created_at': 'Created',
            'schedules.field_updated_at': 'Updated',
            'schedules.last_run_succeeded': 'The last run completed successfully',
            'schedules.last_run_failed': 'The last run failed',
            'tasks.identifier': 'Identifier',
            'common.delete': 'Delete',
            'common.saving': 'Saving',
            'common.save': 'Save',
            'schedules.delete_title': 'Delete Schedule?',
            'schedules.delete_description': '{name}',
            'schedules.confirm_delete': 'Delete Schedule',
            'common.cancel': 'Cancel',
            'schedules.cron_hint': 'Cron hint',
            'common.loading': 'Loading',
            'common.load_more': 'Load more',
          } as Record<string, string>)[key] ?? key
        }
      />
    );

    expect(screen.getAllByText('formatted:Asia/Shanghai').length).toBeGreaterThan(0);
    expect(dateTimeFormatSpy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ timeZone: 'Asia/Shanghai' })
    );
  });
});
