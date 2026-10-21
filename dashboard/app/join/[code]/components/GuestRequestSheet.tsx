'use client';

import { useMemo, useState } from 'react';
import { api, ApiError, PublicEvent, SearchResult } from '@/lib/api';
import type { GuestNowPlaying } from '@/lib/api';
import { RequestSheetDisplay } from './RequestSheetDisplay';

interface GuestRequestSheetProps {
  code: string;
  nickname: string;
  nowPlaying: GuestNowPlaying | null;
  setEvent: React.Dispatch<React.SetStateAction<PublicEvent | null>>;
  reverify: () => Promise<void>;
  onClose: () => void;
  onSubmitted: (requestId: number) => void;
  theme: {
    accent: string;
    accent2: string;
    surface: string;
    border: string;
    subFg: string;
    subFg2: string;
  };
}

export default function GuestRequestSheet({
  code, nickname, nowPlaying, setEvent, reverify, onClose,
  onSubmitted, theme,
}: GuestRequestSheetProps) {
  const { accent, accent2 } = theme;
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [selectedSong, setSelectedSong] = useState<SearchResult | null>(null);
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submitIsDuplicate, setSubmitIsDuplicate] = useState(false);
  const [submitVoteCount, setSubmitVoteCount] = useState(0);
  const [sortByVibes, setSortByVibes] = useState(false);


  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchError(null);
    setSearchResults([]);
    try {
      const results = await api.eventSearch(code, searchQuery, reverify);
      setSearchResults(results);
    } catch {
      setSearchError('Song search is unavailable. Please try again.');
    } finally {
      setSearching(false);
    }
  };

  const handleSubmit = async () => {
    if (!selectedSong) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      const result = await api.submitRequest({
        eventCode: code,
        artist: selectedSong.artist,
        title: selectedSong.title,
        note: note || undefined,
        sourceUrl: selectedSong.url || undefined,
        artworkUrl: selectedSong.album_art || undefined,
        rawSearchQuery: searchQuery || undefined,
        metadata: {
          source: selectedSong.source,
          genre: selectedSong.genre ?? undefined,
          bpm: selectedSong.bpm ?? undefined,
          musical_key: selectedSong.key ?? undefined,
          isrc: selectedSong.isrc ?? undefined,
        },
        nickname: nickname || undefined,
        reverify,
      });
      onSubmitted(result.id);
      setSubmitted(true);
      setSubmitIsDuplicate(result.is_duplicate);
      setSubmitVoteCount(result.vote_count);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setEvent((prev) => prev ? { ...prev, requests_open: false } : prev);
        setSelectedSong(null);
        return;
      }
      setSubmitError('Failed to submit request. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const vibeScored = useMemo(() => {
    if (!searchResults.length) return searchResults;
    const withBpm = searchResults.filter((result) => result.bpm != null);
    const avgBpm = withBpm.length
      ? withBpm.reduce((sum, result) => sum + (result.bpm ?? 0), 0) / withBpm.length
      : 120;
    return searchResults.map((result) => {
      const dBpm = Math.abs((result.bpm ?? avgBpm) - avgBpm);
      // GuestNowPlaying has no musical key field. Treat the playing track's key as
      // unknown (the same neutral penalty used for a result without key metadata).
      const dKey = result.key ? (nowPlaying ? 2 : 0) : 2;
      const score = (dBpm / 8) + dKey;
      const tier = score <= 1 ? 'perfect' : score <= 2.5 ? 'good' : score <= 4 ? 'ok' : 'far';
      return { ...result, _score: score, _tier: tier };
    }).sort((a, b) => sortByVibes ? a._score - b._score : 0);
  }, [searchResults, sortByVibes, nowPlaying]);

  const tierInfo = {
    perfect: { rail: accent, label: 'IN THE POCKET' },
    good: { rail: accent2, label: 'BLENDS WELL' },
    ok: { rail: 'rgba(255,255,255,0.4)', label: 'SLIGHT SHIFT' },
    far: { rail: 'rgba(255,255,255,0.2)', label: 'KEY/TEMPO JUMP' },
  };

  return (
    <RequestSheetDisplay
      search={{
        selectedSong,
        setSelectedSong,
        query: searchQuery,
        setQuery: setSearchQuery,
        results: vibeScored,
        searchError,
        searching,
        sortByVibes,
        setSortByVibes,
        tierInfo,
        onSearch: handleSearch,
      }}
      submission={{
        submitted,
        submitIsDuplicate,
        submitVoteCount,
        note,
        setNote,
        submitting,
        submitError,
        setSubmitError,
        onSubmit: handleSubmit,
      }}
      theme={theme}
      onClose={onClose}
    />
  );
}
