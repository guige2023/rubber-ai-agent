/**
 * InlineToolPreview - Shows tool execution inline like OpenCLAW
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronRight, Loader2, CheckCircle2, XCircle, Clock, ExternalLink } from 'lucide-react';
import type { ToolActivityPayload } from '../hooks/useBackendConnection';

interface InlineToolPreviewProps {
  toolActivities: ToolActivityPayload[];
  sessionId: string;
}

interface ToolCall {
  id: string;
  tool: string;
  phase: 'start' | 'running' | 'complete' | 'error';
  input?: Record<string, unknown>;
  output?: string;
  duration_ms?: number;
  startedAt: number;
}

export function InlineToolPreview({ toolActivities, sessionId }: InlineToolPreviewProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [isExpanded, setIsExpanded] = useState(true);

  // Group tool activities by run
  const toolCalls = toolActivities
    .filter((a) => a.session_id === sessionId)
    .reduce<Record<string, ToolCall>>((acc, activity) => {
      const key = `${activity.run_id}-${activity.tool_name}-${activity.seq || 0}`;
      if (activity.phase === 'start') {
        acc[key] = {
          id: key,
          tool: activity.tool_name,
          phase: 'start',
          input: activity.input,
          startedAt: Date.now(),
        };
      } else if (acc[key]) {
        acc[key] = {
          ...acc[key],
          phase: activity.phase,
          output: activity.output,
          duration_ms: activity.duration_ms,
        };
      }
      return acc;
    }, {});

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleAll = () => setIsExpanded((prev) => !prev);

  const runningTools = Object.values(toolCalls).filter((t) => t.phase === 'start' || t.phase === 'running');
  const completedTools = Object.values(toolCalls).filter((t) => t.phase === 'complete');
  const errorTools = Object.values(toolCalls).filter((t) => t.phase === 'error');

  const formatDuration = (ms?: number) => {
    if (!ms) return '';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const getToolIcon = (tool: string) => {
    if (tool.includes('search') || tool.includes('web')) return '🔍';
    if (tool.includes('browser') || tool.includes('navigate')) return '🌐';
    if (tool.includes('code') || tool.includes('python')) return '💻';
    if (tool.includes('file') || tool.includes('read') || tool.includes('write')) return '📄';
    if (tool.includes('image') || tool.includes('generate')) return '🖼️';
    return '⚙️';
  };

  if (Object.keys(toolCalls).length === 0) {
    return null;
  }

  return (
    <div className="border border-gray-700 rounded-lg bg-gray-900/50 overflow-hidden">
      {/* Header */}
      <button
        onClick={toggleAll}
        className="w-full px-4 py-2 flex items-center justify-between bg-gray-800/50 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="text-sm font-medium text-gray-300">Tools</span>
          <span className="text-xs text-gray-500">
            ({runningTools.length} running, {completedTools.length} done
            {errorTools.length > 0 && `, ${errorTools.length} failed`})
          </span>
        </div>
        {runningTools.length > 0 && (
          <Loader2 size={14} className="animate-spin text-blue-400" />
        )}
      </button>

      {/* Tool List */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="max-h-64 overflow-y-auto">
              {Object.values(toolCalls).map((tool) => (
                <div
                  key={tool.id}
                  className={`border-t border-gray-800 first:border-t-0 ${
                    tool.phase === 'error' ? 'bg-red-900/10' : ''
                  }`}
                >
                  {/* Tool Header */}
                  <button
                    onClick={() => toggleExpand(tool.id)}
                    className="w-full px-4 py-2 flex items-center gap-3 hover:bg-gray-800/50 transition-colors"
                  >
                    <span className="text-base">{getToolIcon(tool.tool)}</span>
                    <span className="flex-1 text-left text-sm text-gray-300">
                      {tool.tool}
                    </span>

                    {/* Status Icon */}
                    {tool.phase === 'start' && (
                      <Loader2 size={14} className="animate-spin text-blue-400" />
                    )}
                    {tool.phase === 'running' && (
                      <Loader2 size={14} className="animate-spin text-yellow-400" />
                    )}
                    {tool.phase === 'complete' && (
                      <CheckCircle2 size={14} className="text-green-400" />
                    )}
                    {tool.phase === 'error' && (
                      <XCircle size={14} className="text-red-400" />
                    )}

                    {/* Duration */}
                    {tool.duration_ms && (
                      <span className="text-xs text-gray-500">
                        {formatDuration(tool.duration_ms)}
                      </span>
                    )}

                    {/* Expand Icon */}
                    {(expandedIds.has(tool.id) || tool.phase === 'running') &&
                      (expandedIds.has(tool.id) ? (
                        <ChevronDown size={14} className="text-gray-500" />
                      ) : (
                        <ChevronRight size={14} className="text-gray-500" />
                      ))}
                  </button>

                  {/* Expanded Content */}
                  <AnimatePresence>
                    {expandedIds.has(tool.id) && (
                      <motion.div
                        initial={{ height: 0 }}
                        animate={{ height: 'auto' }}
                        exit={{ height: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="px-4 pb-3 space-y-2 text-xs">
                          {/* Input */}
                          {tool.input && Object.keys(tool.input).length > 0 && (
                            <div>
                              <div className="text-gray-500 mb-1">Input:</div>
                              <pre className="bg-gray-800 rounded p-2 overflow-x-auto text-gray-400 font-mono">
                                {JSON.stringify(tool.input, null, 2)}
                              </pre>
                            </div>
                          )}

                          {/* Output */}
                          {tool.output && (
                            <div>
                              <div className="text-gray-500 mb-1">Output:</div>
                              <pre className="bg-gray-800 rounded p-2 overflow-x-auto text-gray-400 font-mono max-h-32">
                                {tool.output.length > 500
                                  ? tool.output.slice(0, 500) + '...'
                                  : tool.output}
                              </pre>
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
