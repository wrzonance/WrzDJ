'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { QRCodeSVG } from 'qrcode.react';
import { api } from '@/lib/api';

type PairState = 'loading' | 'pairing' | 'expired' | 'error';

const POLL_INTERVAL_MS = 2000;
const SESSION_TOKEN_KEY = 'kiosk_session_token';
const PAIR_CODE_KEY = 'kiosk_pair_code';

function formatCode(code: string): string {
  if (code.length <= 3) return code;
  return `${code.slice(0, 3)}-${code.slice(3)}`;
}

export default function KioskPairPage() {
  const [pairCode, setPairCode] = useState('');
  const [state, setState] = useState<PairState>('loading');
  const [errorMsg, setErrorMsg] = useState('');
  const router = useRouter();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPairStatusPolling = useCallback((code: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.getKioskPairStatus(code);
        // /e/{code}/display resolves by event.join_code (post PR #324). Use
        // event_join_code from the pairing response, NOT event_code (which is
        // the internal collection code and would 404 the display endpoint).
        if (status.status === 'active' && status.event_join_code) {
          stopPolling();
          router.push(`/e/${status.event_join_code}/display`);
        } else if (status.status === 'expired') {
          stopPolling();
          setState('expired');
        }
      } catch {
        // Silently retry on network errors
      }
    }, POLL_INTERVAL_MS);
  }, [router, stopPolling]);

  const startAssignmentPolling = useCallback((token: string) => {
    stopPolling();
    // Check immediately first
    api.getKioskAssignment(token).then((status) => {
      if (status.status === 'active' && status.event_join_code) {
        router.push(`/e/${status.event_join_code}/display`);
        return;
      }
      if (status.status === 'expired') {
        localStorage.removeItem(SESSION_TOKEN_KEY);
        localStorage.removeItem(PAIR_CODE_KEY);
        createNewPairing();
        return;
      }
      // If not yet assigned, start interval polling
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.getKioskAssignment(token);
          if (s.status === 'active' && s.event_join_code) {
            stopPolling();
            router.push(`/e/${s.event_join_code}/display`);
          } else if (s.status === 'expired') {
            stopPolling();
            localStorage.removeItem(SESSION_TOKEN_KEY);
            localStorage.removeItem(PAIR_CODE_KEY);
            createNewPairing();
          }
        } catch {
          // Silently retry
        }
      }, POLL_INTERVAL_MS);
    }).catch(() => {
      // Token invalid, clear and create new pairing
      localStorage.removeItem(SESSION_TOKEN_KEY);
      localStorage.removeItem(PAIR_CODE_KEY);
      createNewPairing();
    });
  }, [router, stopPolling]);

  const createNewPairing = useCallback(async () => {
    setState('loading');
    setErrorMsg('');
    try {
      const challenge = await api.getKioskPairChallenge();
      const result = await api.createKioskPairing(challenge.nonce);
      setPairCode(result.pair_code);
      localStorage.setItem(SESSION_TOKEN_KEY, result.session_token);
      localStorage.setItem(PAIR_CODE_KEY, result.pair_code);
      setState('pairing');
      startPairStatusPolling(result.pair_code);
    } catch {
      setState('error');
      setErrorMsg('Failed to create pairing session');
    }
  }, [startPairStatusPolling]);

  useEffect(() => {
    // Check for existing session
    const existingToken = localStorage.getItem(SESSION_TOKEN_KEY);
    if (existingToken) {
      const savedCode = localStorage.getItem(PAIR_CODE_KEY);
      if (savedCode) setPairCode(savedCode);
      setState('pairing');
      startAssignmentPolling(existingToken);
    } else {
      createNewPairing();
    }
    return stopPolling;
  }, []);

  // Auto-regenerate when pairing code expires (no human present to press a button)
  useEffect(() => {
    if (state !== 'expired') return;
    const timer = setTimeout(() => {
      localStorage.removeItem(SESSION_TOKEN_KEY);
      localStorage.removeItem(PAIR_CODE_KEY);
      createNewPairing();
    }, 3000);
    return () => clearTimeout(timer);
  }, [state, createNewPairing]);

  const handleRegenerate = () => {
    localStorage.removeItem(SESSION_TOKEN_KEY);
    localStorage.removeItem(PAIR_CODE_KEY);
    createNewPairing();
  };

  const qrUrl = typeof window !== 'undefined'
    ? `${window.location.origin}/kiosk-link/${pairCode}`
    : `/kiosk-link/${pairCode}`;

  return (
    <>
    <style jsx global>{`
      * {
        user-select: none;
        -webkit-user-select: none;
        -webkit-touch-callout: none;
        cursor: none;
      }
      body {
        overflow: hidden;
      }
    `}</style>
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#0a0a0a',
      color: '#ededed',
      padding: '2rem',
    }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.5rem' }}>
        Kiosk Setup
      </h1>
      <p style={{ color: '#9ca3af', marginBottom: '2rem', textAlign: 'center', maxWidth: '400px' }}>
        Scan the QR code with your phone to pair this display with an event
      </p>

      {state === 'loading' && (
        <p style={{ color: '#9ca3af' }}>Generating pairing code...</p>
      )}

      {state === 'pairing' && pairCode && (
        <>
          <div style={{
            background: '#fff',
            padding: '1.5rem',
            borderRadius: '12px',
            marginBottom: '2rem',
          }}>
            <QRCodeSVG value={qrUrl} size={200} />
          </div>

          <div style={{
            fontSize: '3rem',
            fontWeight: 700,
            fontFamily: 'monospace',
            letterSpacing: '0.15em',
            marginBottom: '0.5rem',
          }}>
            {formatCode(pairCode)}
          </div>

          <p style={{ color: '#9ca3af', fontSize: '0.875rem' }}>
            Enter this code or scan the QR code above
          </p>

          <div style={{
            marginTop: '2rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            color: '#6b7280',
            fontSize: '0.875rem',
          }}>
            <span style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: '#3b82f6',
              animation: 'pulse 2s ease-in-out infinite',
              display: 'inline-block',
            }} />
            Waiting for pairing...
          </div>
        </>
      )}

      {state === 'expired' && (
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: '#f59e0b' }}>Pairing code expired</p>
          <p style={{ color: '#9ca3af', fontSize: '0.875rem', marginTop: '0.5rem' }}>
            Generating new code...
          </p>
        </div>
      )}

      {state === 'error' && (
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: '#ef4444', marginBottom: '1rem' }}>{errorMsg}</p>
          <button
            onClick={handleRegenerate}
            className="btn btn-primary"
          >
            Try Again
          </button>
        </div>
      )}
    </div>
    </>
  );
}
