'use client';

import { useCallback, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type { RecommendedTrack, RequestStatus, SongRequest } from '@/lib/api/types';

interface EventQueueActionOptions {
  code: string;
  setAllRequests: React.Dispatch<React.SetStateAction<SongRequest[]>>;
  refetchRequests: () => void;
  setActionError: (message: string | null) => void;
}

export function useEventQueueActions({ code, setAllRequests, refetchRequests, setActionError }: EventQueueActionOptions) {
  const [updating, setUpdating] = useState<number | null>(null);
  const [acceptingAll, setAcceptingAll] = useState(false);
  const [deletingRequest, setDeletingRequest] = useState<number | null>(null);
  const [refreshingRequest, setRefreshingRequest] = useState<number | null>(null);
  const [rejectingAll, setRejectingAll] = useState(false);

  const updateStatus = async (requestId: number, status: RequestStatus) => {
    setUpdating(requestId);
    try {
      const updated = await api.updateRequestStatus(requestId, status);
      setAllRequests((previous) => previous.map((request) => request.id === requestId ? updated : request));
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to update status');
    } finally {
      setUpdating(null);
    }
  };

  const handleAcceptAll = async () => {
    setAcceptingAll(true);
    try {
      await api.acceptAllRequests(code);
      refetchRequests();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to accept all requests');
    } finally {
      setAcceptingAll(false);
    }
  };

  const handleDeleteRequest = async (requestId: number) => {
    setDeletingRequest(requestId);
    try {
      await api.deleteRequest(requestId);
      setAllRequests((previous) => previous.filter((request) => request.id !== requestId));
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to delete request');
    } finally {
      setDeletingRequest(null);
    }
  };

  const handleRefreshMetadata = async (requestId: number) => {
    setRefreshingRequest(requestId);
    try {
      const updated = await api.refreshRequestMetadata(requestId);
      setAllRequests((previous) => previous.map((request) => request.id === requestId ? updated : request));
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to refresh metadata');
    } finally {
      setRefreshingRequest(null);
    }
  };

  const handleEnrichAll = () => api.enrichAllRequests(code);

  const handleRejectAll = async () => {
    setRejectingAll(true);
    try {
      await api.rejectAllRequests(code);
      refetchRequests();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to reject all requests');
    } finally {
      setRejectingAll(false);
    }
  };

  const handleBulkDelete = async (status?: string) => {
    try {
      await api.bulkDeleteRequests(code, status);
      refetchRequests();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to bulk delete requests');
    }
  };

  const handleAcceptRecommendedTrack = async (track: RecommendedTrack) => {
    await api.submitRequest({
      eventCode: code,
      artist: track.artist,
      title: track.title,
      sourceUrl: track.url || undefined,
      artworkUrl: track.cover_url || undefined,
      metadata: {
        source: track.source,
        genre: track.genre || undefined,
        bpm: track.bpm || undefined,
        musical_key: track.key || undefined,
      },
    });
    refetchRequests();
  };

  const handleRefreshRequests = useCallback(() => refetchRequests(), [refetchRequests]);
  return {
    updating,
    acceptingAll,
    deletingRequest,
    refreshingRequest,
    rejectingAll,
    updateStatus,
    handleAcceptAll,
    handleDeleteRequest,
    handleRefreshMetadata,
    handleEnrichAll,
    handleRejectAll,
    handleBulkDelete,
    handleAcceptRecommendedTrack,
    handleRefreshRequests,
  };
}
