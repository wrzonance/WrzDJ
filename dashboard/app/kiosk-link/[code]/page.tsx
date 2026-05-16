'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { Event } from '@/lib/api-types';

type PageState = 'loading' | 'picking' | 'pairing' | 'success' | 'error';

export default function KioskLinkPage() {
  const { code } = useParams<{ code: string }>();
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const [events, setEvents] = useState<Event[]>([]);
  const [state, setState] = useState<PageState>('loading');
  const [errorMsg, setErrorMsg] = useState('');
  const [pairedEventName, setPairedEventName] = useState('');

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.push(`/login?redirect=/kiosk-link/${code}`);
      return;
    }
    api.getEvents().then((evts) => {
      setEvents(evts.filter(e => e.is_active));
      setState('picking');
    }).catch(() => {
      setState('error');
      setErrorMsg('Failed to load events');
    });
  }, [isAuthenticated, isLoading, router, code]);

  const handleSelectEvent = useCallback(async (eventCode: string, eventName: string) => {
    setState('pairing');
    setErrorMsg('');
    try {
      await api.completeKioskPairing(code, eventCode);
      setPairedEventName(eventName);
      setState('success');
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 410) {
        setErrorMsg('Pairing code has expired. Please generate a new code on the kiosk.');
      } else if (status === 409) {
        setErrorMsg('This kiosk is already paired.');
      } else {
        setErrorMsg('Failed to pair kiosk. Please try again.');
      }
      setState('error');
    }
  }, [code]);

  if (isLoading || state === 'loading') {
    return (
      <div className="container" style={{ maxWidth: '500px', marginTop: '80px', textAlign: 'center' }}>
        <p style={{ color: '#9ca3af' }}>Loading...</p>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: '500px', marginTop: '80px' }}>
      <div className="card" style={{ padding: '1.5rem' }}>
        <h1 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.5rem' }}>
          Pair Kiosk Display
        </h1>
        <p style={{ color: '#9ca3af', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
          Code: <strong style={{ fontFamily: 'monospace', color: '#ededed' }}>
            {code.length > 3 ? `${code.slice(0, 3)}-${code.slice(3)}` : code}
          </strong>
        </p>

        {state === 'picking' && (
          <>
            {events.length === 0 ? (
              <p style={{ color: '#9ca3af', textAlign: 'center' }}>
                No active events. Create an event first.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <p style={{ color: '#9ca3af', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
                  Select an event to display on this kiosk:
                </p>
                {events.map((event) => (
                  <button
                    key={event.code}
                    onClick={() => handleSelectEvent(event.code, event.name)}
                    className="btn"
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '0.75rem 1rem',
                      background: '#1a1a1a',
                      border: '1px solid #333',
                      borderRadius: '8px',
                      color: '#ededed',
                      cursor: 'pointer',
                    }}
                  >
                    <span style={{ fontWeight: 500 }}>{event.name}</span>
                    <span style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      color: '#6b7280',
                      marginTop: '0.25rem',
                    }}>
                      Code: {event.code}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {state === 'pairing' && (
          <p style={{ color: '#9ca3af', textAlign: 'center' }}>Pairing...</p>
        )}

        {state === 'success' && (
          <div style={{ textAlign: 'center' }}>
            <p style={{ color: '#10b981', marginBottom: '1rem', fontSize: '1.125rem' }}>
              Kiosk paired to &quot;{pairedEventName}&quot;
            </p>
            <p style={{ color: '#9ca3af', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
              The kiosk will automatically show the event display.
            </p>
            <a
              href="/dashboard"
              className="btn btn-primary"
              style={{ textDecoration: 'none' }}
            >
              Go to Dashboard
            </a>
          </div>
        )}

        {state === 'error' && (
          <div style={{ textAlign: 'center' }}>
            <p style={{ color: '#ef4444', marginBottom: '1rem' }}>{errorMsg}</p>
            <button
              onClick={() => setState('picking')}
              className="btn"
              style={{ background: '#333' }}
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
