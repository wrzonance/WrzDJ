'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, SystemStats } from '@/lib/api';
import { useHelp } from '@/lib/help/HelpContext';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-overview';

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [error, setError] = useState('');
  const { hasSeenPage, startOnboarding, onboardingActive } = useHelp();

  useEffect(() => {
    api.getAdminStats()
      .then(setStats)
      .catch(() => setError('Failed to load stats'));
  }, []);

  useEffect(() => {
    if (stats && !onboardingActive && !hasSeenPage(PAGE_ID)) {
      const timer = setTimeout(() => startOnboarding(PAGE_ID), 500);
      return () => clearTimeout(timer);
    }
  }, [stats, onboardingActive, hasSeenPage, startOnboarding]);

  if (error) {
    return (
      <div className="container">
        <div className="card" style={{ color: 'var(--color-danger)' }}>{error}</div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="container">
        <div className="loading">Loading stats...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />
      <h1 style={{ marginBottom: '2rem' }}>Dashboard Overview</h1>

      <HelpSpot spotId="admin-stats" page={PAGE_ID} order={1} title="System Stats" description="At-a-glance metrics: users, events, requests, and pending approvals.">
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{stats.total_users}</div>
            <div className="stat-label">Total Users</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.active_users}</div>
            <div className="stat-label">Active Users</div>
          </div>
          <HelpSpot spotId="admin-pending" page={PAGE_ID} order={2} title="Pending Approval" description="Orange when users are waiting. Click Manage Users to review them.">
            <div className="stat-card">
              <div className="stat-value" style={{ color: stats.pending_users > 0 ? 'var(--color-warning)' : undefined }}>
                {stats.pending_users}
              </div>
              <div className="stat-label">Pending Approval</div>
            </div>
          </HelpSpot>
          <div className="stat-card">
            <div className="stat-value">{stats.total_events}</div>
            <div className="stat-label">Total Events</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.active_events}</div>
            <div className="stat-label">Active Events</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.total_requests}</div>
            <div className="stat-label">Total Requests</div>
          </div>
        </div>
      </HelpSpot>

      <HelpSpot spotId="admin-actions" page={PAGE_ID} order={3} title="Quick Actions" description="Jump to user or event management.">
        <div style={{ display: 'flex', gap: '1rem', marginTop: '2rem' }}>
          <Link href="/admin/users">
            <button className="btn btn-primary">
              Manage Users
              {stats.pending_users > 0 && (
                <span className="badge" style={{ background: 'var(--color-warning)', marginLeft: '0.5rem' }}>
                  {stats.pending_users}
                </span>
              )}
            </button>
          </Link>
          <Link href="/admin/events">
            <button className="btn btn-primary">Manage Events</button>
          </Link>
        </div>
      </HelpSpot>
    </div>
  );
}
