/**
 * CommandPalette - Slash command palette like OpenCLAW
 */

import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Plus, Image, Code, FileText, Download, HelpCircle, Trash2, Activity, Bot } from 'lucide-react';
import type { SlashCommand } from '../hooks/useCommands';

interface CommandPaletteProps {
  isOpen: boolean;
  query: string;
  commands: SlashCommand[];
  selectedIndex: number;
  onQueryChange: (query: string) => void;
  onSelect: (index: number) => void;
  onExecute: () => void;
  onClose: () => void;
}

const iconMap: Record<string, React.ReactNode> = {
  '➕': <Plus size={16} />,
  '🔍': <Search size={16} />,
  '🖼️': <Image size={16} />,
  '💻': <Code size={16} />,
  '📝': <FileText size={16} />,
  '📤': <Download size={16} />,
  '❓': <HelpCircle size={16} />,
  '🗑️': <Trash2 size={16} />,
  '📊': <Activity size={16} />,
  '🤖': <Bot size={16} />,
};

const categoryColors: Record<string, string> = {
  action: 'text-blue-400',
  search: 'text-purple-400',
  media: 'text-pink-400',
  session: 'text-green-400',
  system: 'text-yellow-400',
};

export function CommandPalette({
  isOpen,
  query,
  commands,
  selectedIndex,
  onQueryChange,
  onSelect,
  onExecute,
  onClose,
}: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    // Scroll selected item into view
    if (listRef.current) {
      const selectedEl = listRef.current.children[selectedIndex] as HTMLElement;
      if (selectedEl) {
        selectedEl.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          onSelect(selectedIndex + 1 >= commands.length ? 0 : selectedIndex + 1);
          break;
        case 'ArrowUp':
          e.preventDefault();
          onSelect(selectedIndex - 1 < 0 ? commands.length - 1 : selectedIndex - 1);
          break;
        case 'Enter':
          e.preventDefault();
          onExecute();
          break;
        case 'Escape':
          e.preventDefault();
          onClose();
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, commands.length, selectedIndex, onSelect, onExecute, onClose]);

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

          {/* Palette */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            transition={{ duration: 0.15 }}
            className="fixed top-[20%] left-1/2 -translate-x-1/2 w-full max-w-lg z-50"
          >
            <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">
              {/* Search Input */}
              <div className="flex items-center px-4 py-3 border-b border-gray-700">
                <Search size={18} className="text-gray-400 mr-3" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => onQueryChange(e.target.value)}
                  placeholder="Type a command or search..."
                  className="flex-1 bg-transparent text-white placeholder-gray-500 outline-none text-sm"
                />
                <kbd className="text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">
                  ESC
                </kbd>
              </div>

              {/* Commands List */}
              <div ref={listRef} className="max-h-80 overflow-y-auto py-2">
                {commands.length === 0 ? (
                  <div className="px-4 py-8 text-center text-gray-500 text-sm">
                    No commands found
                  </div>
                ) : (
                  commands.map((cmd, index) => (
                    <button
                      key={cmd.id}
                      onClick={() => {
                        onSelect(index);
                        onExecute();
                      }}
                      onMouseEnter={() => onSelect(index)}
                      className={`w-full flex items-center px-4 py-2.5 text-left transition-colors ${
                        index === selectedIndex
                          ? 'bg-blue-600/20 text-blue-300'
                          : 'text-gray-300 hover:bg-gray-800'
                      }`}
                    >
                      <span className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-800 mr-3 text-lg">
                        {iconMap[cmd.icon || '➕'] || <Plus size={16} />}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">
                            /{cmd.name}
                          </span>
                          {cmd.aliases && cmd.aliases.length > 1 && (
                            <span className="text-xs text-gray-500">
                              ({cmd.aliases.slice(1).join(', ')})
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-gray-500 truncate">
                          {cmd.description}
                        </p>
                      </div>
                      <span className={`text-xs ${categoryColors[cmd.category]}`}>
                        {cmd.category}
                      </span>
                    </button>
                  ))
                )}
              </div>

              {/* Footer */}
              <div className="px-4 py-2 border-t border-gray-700 flex items-center justify-between text-xs text-gray-500">
                <div className="flex items-center gap-4">
                  <span>
                    <kbd className="bg-gray-800 px-1.5 py-0.5 rounded">↑↓</kbd> Navigate
                  </span>
                  <span>
                    <kbd className="bg-gray-800 px-1.5 py-0.5 rounded">↵</kbd> Execute
                  </span>
                </div>
                <span>{commands.length} commands</span>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
