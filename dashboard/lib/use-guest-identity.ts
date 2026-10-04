"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface GuestIdentity {
  guestId: number | null;
  isReturning: boolean;
  reconcileHint: boolean;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

let cachedIdentity: { guestId: number; isReturning: boolean; reconcileHint: boolean } | null = null;

export function useGuestIdentity(): GuestIdentity {
  const [state, setState] = useState<Omit<GuestIdentity, "refresh">>({
    guestId: cachedIdentity?.guestId ?? null,
    isReturning: cachedIdentity?.isReturning ?? false,
    reconcileHint: cachedIdentity?.reconcileHint ?? false,
    isLoading: !cachedIdentity,
    error: null,
  });
  const calledRef = useRef(false);

  const doIdentify = useCallback(async () => {
    try {
      const { getThumbmark } = await import("@thumbmarkjs/thumbmarkjs");

      // Fingerprints are reconciled by WrzDJ; never send upstream telemetry.
      const fp = await getThumbmark({ logging: false, collect_beacon: false });

      const resp = await fetch(`${API_URL}/api/public/guest/identify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          fingerprint_hash: fp.thumbmark,
          fingerprint_components: fp.components,
        }),
      });

      if (!resp.ok) {
        throw new Error(`Identify failed: ${resp.status}`);
      }

      const data = (await resp.json()) as {
        guest_id: number;
        action: "create" | "cookie_hit" | "reconcile";
        reconcile_hint?: boolean;
      };
      const identity = {
        guestId: data.guest_id,
        isReturning: data.action !== "create",
        reconcileHint: data.reconcile_hint ?? false,
      };
      cachedIdentity = identity;
      setState({ ...identity, isLoading: false, error: null });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : "Identity check failed",
      }));
    }
  }, []);

  const identify = useCallback(async () => {
    if (cachedIdentity || calledRef.current) {
      return;
    }
    calledRef.current = true;
    await doIdentify();
  }, [doIdentify]);

  const refreshInFlightRef = useRef<Promise<void> | null>(null);

  const refresh = useCallback(async () => {
    if (refreshInFlightRef.current) {
      return refreshInFlightRef.current;
    }
    cachedIdentity = null;
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    const promise = doIdentify().finally(() => {
      refreshInFlightRef.current = null;
    });
    refreshInFlightRef.current = promise;
    return promise;
  }, [doIdentify]);

  useEffect(() => {
    identify();
  }, [identify]);

  return { ...state, refresh };
}
