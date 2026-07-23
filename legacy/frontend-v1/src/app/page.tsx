'use client';

import { redirect } from 'next/navigation';

export default function HomePage() {
  // 默认重定向到仪表盘
  redirect('/dashboard');
}
