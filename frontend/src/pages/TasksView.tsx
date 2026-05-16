import React from 'react';
import { TaskManager } from '../components/TaskManager';

interface TasksViewProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

export function TasksView({ call, isConnected, t }: TasksViewProps) {
  return (
    <div className="flex-1 overflow-hidden">
      <TaskManager call={call} isConnected={isConnected} t={t} />
    </div>
  );
}
