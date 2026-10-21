'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';

export function useDjAccess() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.isLoading) return;
    if (!auth.isAuthenticated) {
      router.push('/login');
    } else if (auth.role === 'pending') {
      router.push('/pending');
    }
  }, [auth.isAuthenticated, auth.isLoading, auth.role, router]);

  return {
    ...auth,
    canAccess: !auth.isLoading && auth.isAuthenticated && auth.role !== 'pending',
  };
}
