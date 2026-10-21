'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, api } from '@/lib/api';

const SESSION_CHECK_INTERVAL = 10_000;
const SESSION_TOKEN_KEY = 'kiosk_session_token';
const PAIR_CODE_KEY = 'kiosk_pair_code';

export function useKioskSessionLifecycle() {
  const router = useRouter();

  useEffect(() => {
    const token = typeof window !== 'undefined'
      ? localStorage.getItem(SESSION_TOKEN_KEY)
      : null;
    api.setKioskSession(token);
    return () => api.setKioskSession(null);
  }, []);

  useEffect(() => {
    const token = typeof window !== 'undefined'
      ? localStorage.getItem(SESSION_TOKEN_KEY)
      : null;
    if (!token) return;

    const checkSession = async () => {
      try {
        const assignment = await api.getKioskAssignment(token);
        if (assignment.status === 'unassigned' || assignment.status === 'expired') {
          clearSessionAndPairing();
          router.push('/kiosk-pair');
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          clearSessionAndPairing();
          router.push('/kiosk-pair');
        }
        // Transient network/server errors leave the session available for retry.
      }
    };

    const intervalId = setInterval(checkSession, SESSION_CHECK_INTERVAL);
    return () => clearInterval(intervalId);
  }, [router]);

  useEffect(() => {
    const preventDefaults = (event: Event) => {
      event.preventDefault();
      return false;
    };
    const protectedEvents = ['contextmenu', 'selectstart', 'dragstart'] as const;
    protectedEvents.forEach((eventName) => document.addEventListener(eventName, preventDefaults));
    return () => {
      protectedEvents.forEach((eventName) => document.removeEventListener(eventName, preventDefaults));
    };
  }, []);
}

function clearSessionAndPairing() {
  localStorage.removeItem(SESSION_TOKEN_KEY);
  localStorage.removeItem(PAIR_CODE_KEY);
}
