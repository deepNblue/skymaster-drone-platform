'use client';

import React from 'react';
import { ConfigProvider, theme } from 'antd';

const skymasterDarkTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#1890ff',
    colorSuccess: '#52c41a',
    colorError: '#ff4d4f',
    colorBgBase: '#0a0e14',
    colorTextBase: '#e6edf3',
    borderRadius: 4,
    fontFamily:
      'Inter, "HarmonyOS Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  components: {
    Layout: {
      headerBg: '#12171d',
      siderBg: '#12171d',
      bodyBg: '#0a0e14',
    },
    Menu: {
      darkItemBg: 'transparent',
      darkItemSelectedBg: 'rgba(24,144,255,0.15)',
      darkItemSelectedColor: '#1890ff',
    },
    Card: {
      colorBgContainer: '#12171d',
    },
    Table: {
      headerBg: '#12171d',
    },
  },
};

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={skymasterDarkTheme}>{children}</ConfigProvider>;
}
