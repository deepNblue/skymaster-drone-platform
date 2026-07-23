import React from 'react';
import { CopilotPage } from '../../../copilot/CopilotPage';

// 从全局状态或 auth 获取当前 orgId
// 在实际应用中，这里应该从 zustand store 或 context 获取
export default function CopilotRoute() {
  // TODO: 从用户的组织上下文获取实际 orgId
  const orgId = typeof window !== 'undefined'
    ? (localStorage.getItem('current_org_id') || 'default-org')
    : 'default-org';

  return <CopilotPage orgId={orgId} />;
}
