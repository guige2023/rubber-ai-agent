/**
 * SessionSearch - Search through session history
 */

import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, X, MessageSquare, Clock, ArrowRight } from 'lucide-react';
import { useSessionSearch } from '../hooks/useSessionSearch';

interface SessionSearchProps {
  isOpen: boolean;
  sessions: Array<{ id: string; title: string }>;
  onSearch: (
    sessionId: string,
    query: string
  ) => Promise<Array<{ id: string; role: 'user' | 'assistant' | 'system'; content: string; created_at?: string }>>;
  onSelectSession: (sessionId: string) => void;
  onClose: () => void;
}

export function SessionSearch({
  isOpen,
  sessions,
  onSearch,
  onSelectSession,
  onClose,
}: SessionSearchProps) {
  const {
    query,
    setQuery,
    isSearching,
    results,
    search,
    clear,
  } = useSessionSearch();

  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && query.trim().length >= 2) {
      const timer = setTimeout(() => {
        search(onSearch, sessions);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen, query, sessions, onSearch, search]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const handleSelectSession = (sessionId: string) => {
    onSelectSession(sessionId);
    onClose();
    clear();
  };

  const formatTime = (dateStr?: string) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 z-50"
            onClick={onClose}
          />

          {/* Search Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            className="fixed top-[15%] left-1/2 -translate-x-1/2 w-full max-w-2xl z-50"
          >
            <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">
              {/* Search Input */}
              <div className="flex items-center px-4 py-3 border-b border-gray-700">
                <Search size={18} className="text-gray-400 mr-3" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search all sessions..."
                  className="flex-1 bg-transparent text-white placeholder-gray-500 outline-none text-sm"
                />
                {query && (
                  <button
                    onClick={clear}
                    className="p-1 hover:bg-gray-800 rounded"
                  >
                    <X size={16} className="text-gray-400" />
                  </button>
                )}
                <kbd className="ml-2 text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">
                  ESC
                </kbd>
              </div>

              {/* Results */}
              <div className="max-h-96 overflow-y-auto">
                {isSearching ? (
                  <div className="px-4 py-8 text-center text-gray-500 text-sm">
                    Searching...
                  </div>
                ) : query.length < 2 ? (
                  <div className="px-4 py-8 text-center text-gray-500 text-sm">
                    Type at least 2 characters to search
                  </div>
                ) : results.length === 0 ? (
                  <div className="px-4 py-8 text-center text-gray-500 text-sm">
                    No results found for "{query}"
                  </div>
                ) : (
                  <div className="py-2">
                    {results.map((result) => (
                      <div key={result.sessionId} className="mb-4">
                        {/* Session Header */}
                        <button
                          onClick={() => handleSelectSession(result.sessionId)}
                          className="w-full px-4 py-2 flex items-center justify-between hover:bg-gray-800/50 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <MessageSquare size={14} className="text-blue-400" />
                            <span className="text-sm font-medium text-blue-300">
                              {result.sessionTitle}
                            </span>
                          </div>
                          <ArrowRight size={14} className="text-gray-500" />
                        </button>

                        {/* Matches */}
                        <div className="space-y-1 px-4 pb-2">
                          {result.matches.map((match) => (
                            <button
                              key={match.messageId}
                              onClick={() => handleSelectSession(result.sessionId)}
                              className="w-full text-left p-2 rounded bg-gray-800/30 hover:bg-gray-800/60 transition-colors"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span
                                  className={`text-xs px-1.5 py-0.5 rounded ${
                                    match.role === 'user'
                                      ? 'bg-blue-500/20 text-blue-300'
                                      : 'bg-green-500/20 text-green-300'
                                  }`}
                                >
                                  {match.role}
                                </span>
                                {match.created_at && (
                                  <span className="text-xs text-gray-500 flex items-center gap-1">
                                    <Clock size={10} />
                                    {formatTime(match.created_at)}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-gray-400 font-mono line-clamp-2">
                                {match.highlighted}
                              </p>
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="px-4 py-2 border-t border-gray-700 flex items-center justify-between text-xs text-gray-500">
                <span>
                  {results.length > 0
                    ? `Found in ${results.length} session${results.length > 1 ? 's' : ''}`
                    : 'Search all conversations'}
                </span>
                <div className="flex items-center gap-4">
                  <span>
                    <kbd className="bg-gray-800 px-1.5 py-0.5 rounded">↵</kbd> to select
                  </span>
                  <span>
                    <kbd className="bg-gray-800 px-1.5 py-0.5 rounded">ESC</kbd> to close
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
