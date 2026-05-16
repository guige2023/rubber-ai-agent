import React from 'react';
import { MemoryManager } from '../components/MemoryManager';

interface MemoryViewProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

export function MemoryView({ call, isConnected, t }: MemoryViewProps) {
  return (
    <div className="flex-1 overflow-hidden">
      <MemoryManager call={call} isConnected={isConnected} t={t} />
    </div>
  );
}
