/**
 * Slash Commands Hook - Provides slash command functionality like OpenCLAW
 */

import { useState, useCallback, useMemo } from 'react';

export interface SlashCommand {
  id: string;
  name: string;
  description: string;
  icon?: string;
  category: 'action' | 'search' | 'media' | 'session' | 'system';
  aliases?: string[];
  action: (args: string) => void | Promise<void>;
}

const DEFAULT_COMMANDS: SlashCommand[] = [
  {
    id: 'new-session',
    name: 'new',
    description: 'Create a new chat session',
    icon: '➕',
    category: 'session',
    aliases: ['/new', '/n'],
    action: () => {},
  },
  {
    id: 'search',
    name: 'search',
    description: 'Search the web',
    icon: '🔍',
    category: 'search',
    aliases: ['/search', '/s'],
    action: (args) => {},
  },
  {
    id: 'image',
    name: 'image',
    description: 'Generate an image',
    icon: '🖼️',
    category: 'media',
    aliases: ['/image', '/img'],
    action: (args) => {},
  },
  {
    id: 'code',
    name: 'code',
    description: 'Write or explain code',
    icon: '💻',
    category: 'action',
    aliases: ['/code', '/c'],
    action: (args) => {},
  },
  {
    id: 'summarize',
    name: 'summarize',
    description: 'Summarize the conversation',
    icon: '📝',
    category: 'action',
    aliases: ['/summarize', '/sum'],
    action: () => {},
  },
  {
    id: 'export',
    name: 'export',
    description: 'Export conversation',
    icon: '📤',
    category: 'action',
    aliases: ['/export', '/exp'],
    action: () => {},
  },
  {
    id: 'help',
    name: 'help',
    description: 'Show help information',
    icon: '❓',
    category: 'system',
    aliases: ['/help', '/h', '/?'],
    action: () => {},
  },
  {
    id: 'clear',
    name: 'clear',
    description: 'Clear current conversation',
    icon: '🗑️',
    category: 'session',
    aliases: ['/clear', '/cl'],
    action: () => {},
  },
  {
    id: 'status',
    name: 'status',
    description: 'Show system status',
    icon: '📊',
    category: 'system',
    aliases: ['/status', '/st'],
    action: () => {},
  },
  {
    id: 'model',
    name: 'model',
    description: 'Switch AI model',
    icon: '🤖',
    category: 'system',
    aliases: ['/model', '/m'],
    action: (args) => {},
  },
];

export function useCommands(customCommands?: SlashCommand[]) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  const allCommands = useMemo(
    () => [...DEFAULT_COMMANDS, ...(customCommands || [])],
    [customCommands]
  );

  const filteredCommands = useMemo(() => {
    if (!query.trim()) {
      return allCommands;
    }

    const lowerQuery = query.toLowerCase();
    return allCommands.filter((cmd) => {
      const nameMatch = cmd.name.toLowerCase().includes(lowerQuery);
      const aliasMatch = cmd.aliases?.some((alias) =>
        alias.toLowerCase().includes(lowerQuery)
      );
      const descMatch = cmd.description.toLowerCase().includes(lowerQuery);
      return nameMatch || aliasMatch || descMatch;
    });
  }, [query, allCommands]);

  const open = useCallback(() => {
    setIsOpen(true);
    setQuery('');
    setSelectedIndex(0);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    setQuery('');
    setSelectedIndex(0);
  }, []);

  const selectNext = useCallback(() => {
    setSelectedIndex((prev) =>
      prev < filteredCommands.length - 1 ? prev + 1 : 0
    );
  }, [filteredCommands.length]);

  const selectPrev = useCallback(() => {
    setSelectedIndex((prev) =>
      prev > 0 ? prev - 1 : filteredCommands.length - 1
    );
  }, [filteredCommands.length]);

  const executeSelected = useCallback(() => {
    const cmd = filteredCommands[selectedIndex];
    if (cmd) {
      const args = query.replace(/^\/\w*/, '').trim();
      cmd.action(args);
      close();
    }
  }, [filteredCommands, selectedIndex, query, close]);

  const executeById = useCallback(
    (id: string, args?: string) => {
      const cmd = allCommands.find((c) => c.id === id || c.aliases?.includes(`/${id}`));
      if (cmd) {
        cmd.action(args || '');
      }
    },
    [allCommands]
  );

  const parseInput = useCallback(
    (input: string): { isCommand: boolean; command?: SlashCommand; args: string } => {
      const trimmed = input.trim();
      if (!trimmed.startsWith('/')) {
        return { isCommand: false, args: trimmed };
      }

      const parts = trimmed.split(/\s+/);
      const cmdText = parts[0].toLowerCase();
      const args = parts.slice(1).join(' ');

      const cmd = allCommands.find(
        (c) =>
          c.name.toLowerCase() === cmdText.slice(1) ||
          c.aliases?.some((alias) => alias.toLowerCase() === cmdText)
      );

      return {
        isCommand: !!cmd,
        command: cmd,
        args,
      };
    },
    [allCommands]
  );

  return {
    isOpen,
    query,
    setQuery,
    selectedIndex,
    filteredCommands,
    open,
    close,
    selectNext,
    selectPrev,
    executeSelected,
    executeById,
    parseInput,
  };
}
