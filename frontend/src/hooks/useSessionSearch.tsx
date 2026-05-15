/**
 * Session Search Hook - Search through session history
 */

import { useState, useCallback, useMemo } from 'react';

export interface SearchableMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
}

export interface SearchResult {
  sessionId: string;
  sessionTitle: string;
  matches: SearchMatch[];
}

export interface SearchMatch {
  messageId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  highlighted: string;
  created_at?: string;
}

export function useSessionSearch() {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searchedSessionIds, setSearchedSessionIds] = useState<Set<string>>(new Set());

  const search = useCallback(
    async (
      searchFn: (sessionId: string, query: string) => Promise<SearchableMessage[]>,
      sessions: Array<{ id: string; title: string }>
    ) => {
      if (!query.trim()) {
        setResults([]);
        return;
      }

      setIsSearching(true);
      const lowerQuery = query.toLowerCase();
      const newResults: SearchResult[] = [];
      const searchedIds = new Set<string>();

      for (const session of sessions) {
        if (searchedSessionIds.has(session.id)) continue;

        try {
          const messages = await searchFn(session.id, query);

          const matches: SearchMatch[] = messages
            .filter((msg) => msg.content.toLowerCase().includes(lowerQuery))
            .map((msg) => {
              const content = msg.content;
              const index = content.toLowerCase().indexOf(lowerQuery);
              const start = Math.max(0, index - 40);
              const end = Math.min(content.length, index + query.length + 40);
              let highlighted = content.slice(start, end);

              if (start > 0) highlighted = '...' + highlighted;
              if (end < content.length) highlighted = highlighted + '...';

              // Highlight the match
              const hlStart = highlighted.toLowerCase().indexOf(lowerQuery);
              if (hlStart >= 0) {
                highlighted =
                  highlighted.slice(0, hlStart) +
                  '**' +
                  highlighted.slice(hlStart, hlStart + query.length) +
                  '**' +
                  highlighted.slice(hlStart + query.length);
              }

              return {
                messageId: msg.id,
                role: msg.role,
                content: msg.content,
                highlighted,
                created_at: msg.created_at,
              };
            });

          if (matches.length > 0) {
            newResults.push({
              sessionId: session.id,
              sessionTitle: session.title || 'Untitled',
              matches,
            });
          }

          searchedIds.add(session.id);
        } catch (error) {
          console.error(`Failed to search session ${session.id}:`, error);
        }
      }

      setResults(newResults);
      setSearchedSessionIds(searchedIds);
      setIsSearching(false);
    },
    [query, searchedSessionIds]
  );

  const clear = useCallback(() => {
    setQuery('');
    setResults([]);
    setSearchedSessionIds(new Set());
  }, []);

  const highlightMatches = useCallback(
    (text: string, highlight: string) => {
      if (!highlight.trim()) return text;

      const parts = text.split(new RegExp(`(${highlight})`, 'gi'));
      return parts.map((part, i) =>
        part.toLowerCase() === highlight.toLowerCase() ? (
          <mark key={i} className="bg-yellow-500/30 text-yellow-200 rounded px-0.5">
            {part}
          </mark>
        ) : (
          part
        )
      );
    },
    []
  );

  return {
    query,
    setQuery,
    isSearching,
    results,
    search,
    clear,
    highlightMatches,
  };
}
