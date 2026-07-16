import React from 'react';
import ThemeProvider from '@/components/ThemeProvider';
import './globals.css';

export const metadata = {
  title: 'SkyMaster · 无人机统一管控平台',
  description: 'SkyMaster drone unified command & control platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
