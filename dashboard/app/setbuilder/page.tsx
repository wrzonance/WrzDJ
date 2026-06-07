'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { SetSummary } from '@/lib/api-types';

export default function SetbuilderPage() {
  const { isAuthenticated, isLoading, role } = useAuth();
  const router = useRouter();
  const [sets, setSets] = useState<SetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role === 'pending') {
      router.push('/pending');
    }
  }, [isAuthenticated, isLoading, role, router]);

  useEffect(() => {
    if (isAuthenticated) {
      api
        .listSets()
        .then(setSets)
        .catch(() => setError('Failed to load sets'))
        .finally(() => setLoading(false));
    }
  }, [isAuthenticated]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await api.createSet(newName.trim());
      setSets((prev) => [created, ...prev]);
      setNewName('');
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create set');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this set? This cannot be undone.')) return;
    try {
      await api.deleteSet(id);
      setSets((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete set');
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
      {error && (
        <div
          style={{
            background: 'var(--color-danger-subtle)',
            color: 'var(--color-danger)',
            padding: '0.75rem 1rem',
            borderRadius: '0.5rem',
            marginBottom: '1rem',
            fontSize: '0.875rem',
          }}
        >
          {error}
        </div>
      )}

      <div className="header">
        <h1>Sets</h1>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <Link
            href="/dashboard"
            className="btn"
            style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
          >
            Dashboard
          </Link>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            New Set
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: '2rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Create New Set</h2>
          <form onSubmit={handleCreate}>
            <div className="form-group">
              <label htmlFor="setName">Set Name</label>
              <input
                id="setName"
                type="text"
                className="input"
                placeholder="Friday Wedding"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                maxLength={120}
                required
              />
            </div>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <button type="submit" className="btn btn-primary" disabled={creating}>
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                type="button"
                className="btn"
                style={{ background: 'var(--surface-raised)' }}
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="loading">Loading sets...</div>
      ) : sets.length === 0 ? (
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)' }}>No sets yet. Create your first set!</p>
        </div>
      ) : (
        <div className="event-grid">
          {sets.map((s) => (
            <div key={s.id} className="event-card" style={{ position: 'relative' }}>
              <Link href={`/setbuilder/${s.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                <h3>{s.name}</h3>
                <div className="code">{s.status}</div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Updated: {new Date(s.updated_at).toLocaleString()}
                </p>
              </Link>
              <button
                className="btn btn-sm btn-danger"
                style={{ marginTop: '0.75rem' }}
                onClick={() => handleDelete(s.id)}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
