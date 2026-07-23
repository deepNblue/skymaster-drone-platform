'use client';

/**
 * RoleGate — v2.0 client-side role guard.
 *
 * Wrap any admin-only UI to enforce role at render time. The backend
 * remains the source of truth (it returns 403 on unauthorized calls),
 * but this component hides the UI to avoid dead-ends and confusion.
 *
 * Note: for a stricter guard use the middleware.ts pattern.
 */
import React from 'react';
import { Alert } from 'antd';
import { useAuthStore } from '@/lib/store';

interface Props {
  required: 'viewer' | 'operator' | 'admin';
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export default function RoleGate({ required, fallback, children }: Props) {
  const hasRole = useAuthStore((s) => s.hasRole);
  const user = useAuthStore((s) => s.user);

  if (!user) {
    // Not logged in — reveal children so the login redirect / API 401
    // takes over. Silent hide would confuse dev.
    return <>{children}</>;
  }

  if (!hasRole(required)) {
    return (
      fallback ?? (
        <Alert
          type="warning"
          showIcon
          message="权限不足"
          description={`当前角色 ${user.role} 无权访问此页面，需要 ${required} 或更高。`}
          style={{ margin: 24 }}
        />
      )
    );
  }

  return <>{children}</>;
}
