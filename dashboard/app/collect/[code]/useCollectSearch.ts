import { useRef, useState } from 'react';
import { api, type SearchResult } from '../../../lib/api';

interface UseCollectSearchOptions {
  code: string;
}

export function useCollectSearch({
  code,
}: UseCollectSearchOptions) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQueryState] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [sortByVibes, setSortByVibes] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichedResults, setEnrichedResults] = useState<SearchResult[]>([]);
  const searchRequestRef = useRef(0);
  const enrichmentRequestRef = useRef(0);

  const setSearchQuery = (query: string) => {
    searchRequestRef.current += 1;
    enrichmentRequestRef.current += 1;
    setSearchQueryState(query);
    setSearchError(null);
    setSearching(false);
    setEnriching(false);
  };

  const openSearch = () => {
    searchRequestRef.current += 1;
    enrichmentRequestRef.current += 1;
    setSearchOpen(true);
    setSearchQueryState('');
    setSearchResults([]);
    setSearchError(null);
  };

  const closeSearch = () => {
    searchRequestRef.current += 1;
    enrichmentRequestRef.current += 1;
    setSearchOpen(false);
    setSearchQueryState('');
    setSearchResults([]);
    setSearchError(null);
    setSortByVibes(false);
    setEnrichedResults([]);
    setSearching(false);
    setEnriching(false);
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    const requestId = ++searchRequestRef.current;
    enrichmentRequestRef.current += 1;
    const query = searchQuery;
    setSearching(true);
    setSearchError(null);
    setSearchResults([]);
    setEnrichedResults([]);
    try {
      const results = await api.eventSearch(code, query);
      if (requestId === searchRequestRef.current) setSearchResults(results);
    } catch {
      if (requestId === searchRequestRef.current) {
        setSearchError('Song search is unavailable. Please try again.');
      }
    } finally {
      if (requestId === searchRequestRef.current) setSearching(false);
    }
  };

  const handleVibesToggle = async () => {
    if (sortByVibes) {
      enrichmentRequestRef.current += 1;
      setSortByVibes(false);
      setEnrichedResults([]);
      setEnriching(false);
      return;
    }
    setSearchError(null);
    setSortByVibes(true);
    const resultsToEnrich = searchResults;
    const requestId = ++enrichmentRequestRef.current;
    const needsEnrich = resultsToEnrich.slice(0, 10).filter((result) => result.bpm == null);
    if (needsEnrich.length === 0) return;
    setEnriching(true);
    try {
      const results = await api.enrichPreview(code, resultsToEnrich.slice(0, 10).map((result) => ({
        title: result.title,
        artist: result.artist,
        source_url: result.url ?? undefined,
      })));
      if (requestId !== enrichmentRequestRef.current) return;
      setEnrichedResults(resultsToEnrich.map((result, index) => {
        const enriched = results[index];
        if (!enriched) return result;
        return {
          ...result,
          bpm: result.bpm ?? enriched.bpm ?? null,
          key: result.key ?? enriched.key ?? null,
          genre: result.genre ?? enriched.genre ?? null,
        };
      }));
    } catch {
      if (requestId === enrichmentRequestRef.current) {
        setSortByVibes(false);
        setEnrichedResults([]);
        setSearchError('Could not apply vibe metadata. Please try again.');
      }
    } finally {
      if (requestId === enrichmentRequestRef.current) setEnriching(false);
    }
  };

  return {
    searchOpen,
    searchQuery,
    setSearchQuery,
    searchResults,
    searchError,
    searching,
    sortByVibes,
    enriching,
    enrichedResults,
    openSearch,
    closeSearch,
    handleSearch,
    handleVibesToggle,
  };
}
