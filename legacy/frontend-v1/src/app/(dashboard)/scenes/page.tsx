'use client';

import React from 'react';
import { ScenesPage } from '../../../copilot/ScenesPage';

// 从全局状态获取当前 orgId
export default function ScenesRoute() {
  const orgId = typeof window !== 'undefined'
    ? (localStorage.getItem('current_org_id') || 'default-org')
    : 'default-org';

  return <ScenesPage orgId={orgId} />;
}
