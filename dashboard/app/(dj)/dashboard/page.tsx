'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useDjAccess } from '@/lib/use-dj-access';
import { api } from '@/lib/api';
import type { Event, TidalStatus, BeatportStatus, ActivityLogEntry } from '@/lib/api/types';
import { useAutoOnboarding } from '@/lib/help/useAutoOnboarding';
import { useLocale } from '@/lib/locale';
import { HelpSpot } from '@/components/help/HelpSpot';
import { PageControls } from '@/components/PageControls';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';
import { ActivityLogPanel } from './components/ActivityLogPanel';
import { CreateEventWorkflow } from './components/CreateEventWorkflow';
import { DashboardEventList } from './components/DashboardEventList';

const PAGE_ID = 'dashboard';

export default function DashboardPage() {
  const { locale, messages } = useLocale();
  const { isAuthenticated, isLoading, role, logout, canAccess } = useDjAccess();
  const [events, setEvents] = useState<Event[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [tidalStatus, setTidalStatus] = useState<TidalStatus | null>(null);
  const [beatportStatus, setBeatportStatus] = useState<BeatportStatus | null>(null);
  const [activityLog, setActivityLog] = useState<ActivityLogEntry[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);


  useEffect(() => {
    if (canAccess) {
      loadData();
    }
  }, [canAccess]);

  useAutoOnboarding(PAGE_ID, canAccess && !loadingEvents);

  const loadData = async () => {
    try {
      const [eventsData, tidalData, beatportData, logData] = await Promise.allSettled([
        api.getEvents(),
        api.getTidalStatus(),
        api.getBeatportStatus(),
        api.getActivityLog(),
      ]);

      if (eventsData.status === 'fulfilled') {
        setEvents(eventsData.value);
      } else {
        setErrorMsg('Failed to load dashboard data');
      }
      if (tidalData.status === 'fulfilled') setTidalStatus(tidalData.value);
      if (beatportData.status === 'fulfilled') setBeatportStatus(beatportData.value);
      if (logData.status === 'fulfilled') setActivityLog(logData.value);
    } finally {
      setLoadingEvents(false);
    }
  };

  if (isLoading || !isAuthenticated) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <PageControls helpPage={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />

      {errorMsg && (
        <div style={{ background: 'var(--color-danger-subtle)', color: 'var(--color-danger)', padding: '0.75rem 1rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.875rem' }}>
          {errorMsg}
        </div>
      )}

      <HelpSpot spotId="events-header" page={PAGE_ID} order={1} title="Your Events" description="This is your events dashboard. All your DJ events appear here.">
        <div className="header">
          <h1 lang={locale}>{messages.dashboard.title}</h1>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            {role === 'admin' && (
              <HelpSpot spotId="events-admin" page={PAGE_ID} order={3} title="Admin Panel" description="Access the admin panel to manage users, view all events, and configure integrations.">
                <Link href="/admin">
                  <button className="btn" style={{ background: 'var(--color-admin)', color: 'white' }}>Admin</button>
                </Link>
              </HelpSpot>
            )}
            <CreateEventWorkflow
              onCreated={(event) => setEvents((current) => [event, ...current])}
              onError={setErrorMsg}
            />
            <Link
              href="/setbuilder"
              lang={locale}
              className="btn"
              style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
            >
              {messages.dashboard.setBuilder}
            </Link>
            <a
              href="https://github.com/thewrz/WrzDJ/releases/latest"
              lang={locale}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-sm"
              style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
            >
              {messages.dashboard.bridgeApp}
            </a>
            <Link href="/account" lang={locale} className="btn" style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}>
              {messages.dashboard.account}
            </Link>
            <button className="btn" lang={locale} style={{ background: 'var(--surface-raised)' }} onClick={logout}>
              {messages.dashboard.logout}
            </button>
          </div>
        </div>
      </HelpSpot>

      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <h3 style={{ marginBottom: '1rem' }}>Cloud Providers</h3>
        <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: tidalStatus?.linked ? '#22c55e' : '#6b7280', display: 'inline-block' }} />
            <span style={{ fontWeight: 500 }}>Tidal</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              {tidalStatus?.linked ? 'Connected' : 'Not connected'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: beatportStatus?.linked ? '#22c55e' : '#6b7280', display: 'inline-block' }} />
            <span style={{ fontWeight: 500 }}>Beatport</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              {beatportStatus?.linked ? 'Connected' : 'Not connected'}
            </span>
          </div>
        </div>
      </div>

      <ActivityLogPanel entries={activityLog} />

      <DashboardEventList
        events={events}
        loading={loadingEvents}
        onEventsChange={setEvents}
        onError={setErrorMsg}
      />
    </div>
  );
}
