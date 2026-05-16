import React from 'react';
import { ScheduleManager } from '../components/ScheduleManager';

interface SchedulesViewProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

export function SchedulesView({ call, isConnected, t }: SchedulesViewProps) {
  return (
    <div className="flex-1 overflow-hidden">
      <ScheduleManager call={call} isConnected={isConnected} t={t} />
    </div>
  );
}
