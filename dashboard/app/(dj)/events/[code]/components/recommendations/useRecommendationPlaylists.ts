import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type { PlaylistInfo } from '@/lib/api/types';

interface RecommendationPlaylists {
  playlists: PlaylistInfo[];
  selectedPlaylist: string | null;
  setSelectedPlaylist: (playlist: string | null) => void;
  loadingPlaylists: boolean;
  playlistsLoaded: boolean;
  loadPlaylists: () => Promise<void>;
}

export function useRecommendationPlaylists(
  code: string,
  onError: (message: string) => void,
): RecommendationPlaylists {
  const [playlists, setPlaylists] = useState<PlaylistInfo[]>([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState<string | null>(null);
  const [loadingPlaylists, setLoadingPlaylists] = useState(false);
  const [playlistsLoaded, setPlaylistsLoaded] = useState(false);
  const mountedRef = useRef(false);
  const loadingRef = useRef(false);
  const requestGenerationRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    requestGenerationRef.current += 1;
    loadingRef.current = false;
    setPlaylists([]);
    setSelectedPlaylist(null);
    setLoadingPlaylists(false);
    setPlaylistsLoaded(false);
  }, [code]);

  const loadPlaylists = useCallback(async () => {
    if (playlistsLoaded || loadingRef.current) return;

    const requestGeneration = ++requestGenerationRef.current;
    loadingRef.current = true;
    setLoadingPlaylists(true);
    try {
      const result = await api.getEventPlaylists(code);
      if (!mountedRef.current || requestGenerationRef.current !== requestGeneration) return;
      setPlaylists(result.playlists);
      setPlaylistsLoaded(true);
    } catch (err) {
      if (!mountedRef.current || requestGenerationRef.current !== requestGeneration) return;
      onError(err instanceof ApiError ? err.message : 'Failed to load playlists');
    } finally {
      if (mountedRef.current && requestGenerationRef.current === requestGeneration) {
        loadingRef.current = false;
        setLoadingPlaylists(false);
      }
    }
  }, [code, onError, playlistsLoaded]);

  return {
    playlists,
    selectedPlaylist,
    setSelectedPlaylist,
    loadingPlaylists,
    playlistsLoaded,
    loadPlaylists,
  };
}
