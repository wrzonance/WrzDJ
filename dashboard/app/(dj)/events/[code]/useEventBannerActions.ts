'use client';

import { useState } from 'react';
import { api, ApiError, type ArchivedEvent, type Event } from '@/lib/api';

const MAX_BANNER_FILE_SIZE_BYTES = 5 * 1024 * 1024;

interface EventBannerOptions {
  code: string;
  setEvent: React.Dispatch<React.SetStateAction<Event | ArchivedEvent | null>>;
  setActionError: (message: string | null) => void;
}

export function useEventBannerActions({ code, setEvent, setActionError }: EventBannerOptions) {
  const [uploadingBanner, setUploadingBanner] = useState(false);

  const handleBannerSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_BANNER_FILE_SIZE_BYTES) {
      setActionError('File size must be under 5MB');
      event.target.value = '';
      return;
    }
    setUploadingBanner(true);
    try {
      setEvent(await api.uploadEventBanner(code, file));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to upload banner');
    } finally {
      setUploadingBanner(false);
      event.target.value = '';
    }
  };

  const handleDeleteBanner = async () => {
    try {
      setEvent(await api.deleteEventBanner(code));
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Failed to delete banner');
    }
  };

  return { uploadingBanner, handleBannerSelect, handleDeleteBanner };
}
