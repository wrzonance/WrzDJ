'use client';

import { useEffect, useState } from 'react';
import { api, AdminUser } from '@/lib/api';
import { useAdminPage } from '@/lib/useAdminPage';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-users';

export default function AdminUsersPage() {
  const [page, setPage] = useState(1);
  const [roleFilter, setRoleFilter] = useState<string | undefined>();
  const [showCreate, setShowCreate] = useState(false);
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [formData, setFormData] = useState({ username: '', password: '', role: 'dj' });
  const [editData, setEditData] = useState({ role: '', is_active: true, password: '' });
  const [error, setError] = useState('');
  const limit = 20;

  const { data: paginated, error: loadError, loading, reload } = useAdminPage({
    pageId: PAGE_ID,
    loader: () => api.getAdminUsers(page, limit, roleFilter),
    onError: () => 'Failed to load users',
  });
  const users = paginated?.items ?? [];
  const total = paginated?.total ?? 0;

  useEffect(() => {
    reload();
  }, [page, roleFilter, reload]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await api.createAdminUser(formData);
      setShowCreate(false);
      setFormData({ username: '', password: '', role: 'dj' });
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    }
  };

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editUser) return;
    setError('');
    try {
      const update: Record<string, unknown> = {};
      if (editData.role !== editUser.role) update.role = editData.role;
      if (editData.is_active !== editUser.is_active) update.is_active = editData.is_active;
      if (editData.password) update.password = editData.password;
      await api.updateAdminUser(editUser.id, update);
      setEditUser(null);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update user');
    }
  };

  const handleDelete = async (user: AdminUser) => {
    if (!confirm(`Delete user "${user.username}"? This will also delete all their events.`)) return;
    try {
      await api.deleteAdminUser(user.id);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete user');
    }
  };

  const openEdit = (user: AdminUser) => {
    setEditUser(user);
    setEditData({ role: user.role, is_active: user.is_active, password: '' });
    setError('');
  };

  const totalPages = Math.ceil(total / limit);

  const roleFilters = [
    { label: 'All', value: undefined },
    { label: 'Admins', value: 'admin' },
    { label: 'DJs', value: 'dj' },
    { label: 'Pending', value: 'pending' },
  ];

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />

      <div className="header">
        <h1>User Management</h1>
        <HelpSpot spotId="admin-create-user" page={PAGE_ID} order={1} title="Create User" description="Add a new DJ or admin account. DJs can create events immediately.">
          <button className="btn btn-primary" onClick={() => { setShowCreate(true); setError(''); }}>
            Create User
          </button>
        </HelpSpot>
      </div>

      {(error || loadError) && (
        <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error || loadError}</div>
      )}

      <HelpSpot spotId="admin-role-filters" page={PAGE_ID} order={2} title="Role Filters" description="Filter by role: All, Admins, DJs, or Pending.">
        <div className="tabs" style={{ marginBottom: '1rem' }}>
          {roleFilters.map((f) => (
            <button
              key={f.label}
              className={`tab${roleFilter === f.value ? ' active' : ''}`}
              onClick={() => { setRoleFilter(f.value); setPage(1); }}
            >
              {f.label}
            </button>
          ))}
        </div>
      </HelpSpot>

      {/* Create Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2 style={{ marginBottom: '1rem' }}>Create User</h2>
            <form onSubmit={handleCreate}>
              <div className="form-group">
                <label htmlFor="new-username">Username</label>
                <input
                  id="new-username"
                  className="input"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  required
                  minLength={3}
                />
              </div>
              <div className="form-group">
                <label htmlFor="new-password">Password</label>
                <input
                  id="new-password"
                  type="password"
                  className="input"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  required
                  minLength={8}
                />
              </div>
              <div className="form-group">
                <label htmlFor="new-role">Role</label>
                <select
                  id="new-role"
                  className="input"
                  value={formData.role}
                  onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                >
                  <option value="dj">DJ</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <button type="submit" className="btn btn-primary">Create</button>
                <button type="button" className="btn" style={{ background: 'var(--surface-raised)' }} onClick={() => setShowCreate(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editUser && (
        <div className="modal-overlay" onClick={() => setEditUser(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2 style={{ marginBottom: '1rem' }}>Edit: {editUser.username}</h2>
            <form onSubmit={handleEdit}>
              <div className="form-group">
                <label htmlFor="edit-role">Role</label>
                <select
                  id="edit-role"
                  className="input"
                  value={editData.role}
                  onChange={(e) => setEditData({ ...editData, role: e.target.value })}
                >
                  <option value="admin">Admin</option>
                  <option value="dj">DJ</option>
                  <option value="pending">Pending</option>
                </select>
              </div>
              <div className="form-group">
                <label>
                  <input
                    type="checkbox"
                    checked={editData.is_active}
                    onChange={(e) => setEditData({ ...editData, is_active: e.target.checked })}
                  />{' '}
                  Active
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="edit-password">New Password (leave blank to keep)</label>
                <input
                  id="edit-password"
                  type="password"
                  className="input"
                  value={editData.password}
                  onChange={(e) => setEditData({ ...editData, password: e.target.value })}
                  minLength={8}
                />
              </div>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <button type="submit" className="btn btn-primary">Save</button>
                <button type="button" className="btn" style={{ background: 'var(--surface-raised)' }} onClick={() => setEditUser(null)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">Loading users...</div>
      ) : (
        <>
          <HelpSpot spotId="admin-user-table" page={PAGE_ID} order={3} title="User Table" description="All accounts with role, status, event count, and creation date.">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Events</th>
                  <th>Created</th>
                  <th>
                    <HelpSpot spotId="admin-user-actions" page={PAGE_ID} order={4} title="User Actions" description="Edit roles, toggle active status, reset passwords, or delete accounts.">
                      <span>Actions</span>
                    </HelpSpot>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td>
                      <span className={`badge badge-role-${user.role}`}>
                        {user.role}
                      </span>
                    </td>
                    <td>{user.is_active ? 'Active' : 'Inactive'}</td>
                    <td>{user.event_count}</td>
                    <td>{new Date(user.created_at).toLocaleDateString()}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button className="btn btn-sm btn-primary" onClick={() => openEdit(user)}>
                          Edit
                        </button>
                        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(user)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </HelpSpot>

          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <span style={{ color: 'var(--text-secondary)' }}>
                Page {page} of {totalPages}
              </span>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
