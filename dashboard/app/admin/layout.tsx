'use client';

import { useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { ThemeToggle } from '@/components/ThemeToggle';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, role, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role !== 'admin') {
      router.push('/events');
    }
  }, [isAuthenticated, isLoading, role, router]);

  if (isLoading || !isAuthenticated || role !== 'admin') {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  const navItems = [
    { href: '/admin', label: 'Overview' },
    { href: '/admin/users', label: 'Users' },
    { href: '/admin/events', label: 'Events' },
    { href: '/admin/integrations', label: 'Integrations' },
    { href: '/admin/ai', label: 'AI / LLM' },
    { href: '/admin/settings', label: 'Settings' },
  ];

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-header">
          <h2>Admin</h2>
        </div>
        <nav className="admin-sidebar-nav">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`admin-sidebar-link${pathname === item.href ? ' active' : ''}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="admin-sidebar-footer">
          <Link href="/dashboard" className="admin-sidebar-link">
            DJ View
          </Link>
          <button
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)', width: '100%' }}
            onClick={logout}
          >
            Logout
          </button>
          <ThemeToggle />
        </div>
      </aside>
      <main className="admin-main">{children}</main>
    </div>
  );
}
