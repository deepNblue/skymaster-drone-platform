/**
 * SkyMaster Design System · Ant Design 5 Theme Token
 * @see docs/UI_DESIGN.md
 * @see docs/UI_FIGMA_MOCKUP.md
 *
 * 主题定位：军工黑客风 · 暗黑独占
 * 底色 #0d1117 · 主色 #39ff14 · 无浅色模式
 */

import { theme, type ThemeConfig } from 'antd';

// ═══════════════════════════════════════════════════════════
// Design Tokens (与 CSS Variables 保持 1:1 对齐)
// ═══════════════════════════════════════════════════════════

export const SKYMASTER_COLORS = {
  // Base
  bgBase:        '#0d1117',
  bgElevated1:   '#161b22',
  bgElevated2:   '#1c2128',
  bgGlass:       'rgba(22, 27, 34, 0.6)',
  borderPrimary: '#30363d',
  borderSubtle:  '#21262d',

  // Text
  textPrimary:   '#e6edf3',
  textSecondary: '#8b949e',
  textTertiary:  '#6e7681',

  // Brand / Accent
  accentPrimary:    '#39ff14',
  accentPrimaryDim: '#26a806',
  accentCyan:       '#00ffff',
  accentAmber:      '#ffb000',
  accentRed:        '#ff3838',
  accentPurple:     '#b967ff',
  accentBlue:       '#4c9aff',

  // Status
  success:  '#39ff14',
  warning:  '#ffb000',
  danger:   '#ff3838',
  info:     '#4c9aff',
  disabled: '#484f58',
} as const;

export const SKYMASTER_TYPOGRAPHY = {
  fontSans:    "'Inter', 'HarmonyOS Sans SC', system-ui, sans-serif",
  fontMono:    "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
  fontDisplay: "'Rajdhani', 'Orbitron', 'HarmonyOS Sans SC', sans-serif",

  fsDisplay:  40,
  fsH1:       28,
  fsH2:       22,
  fsH3:       18,
  fsBody:     14,
  fsCaption:  12,
  fsMonoLg:   32,
  fsMonoMd:   18,
  fsMonoSm:   12,
} as const;

export const SKYMASTER_MOTION = {
  hover:       '150ms cubic-bezier(0.4, 0, 0.2, 1)',
  state:       '300ms cubic-bezier(0.4, 0, 0.2, 1)',
  page:        '500ms cubic-bezier(0.4, 0, 0.2, 1)',
} as const;

export const CHART_COLORS = [
  '#39ff14',
  '#00ffff',
  '#ffb000',
  '#ff3838',
  '#b967ff',
  '#4c9aff',
  '#ff6b9d',
  '#00e5a1',
] as const;

// ═══════════════════════════════════════════════════════════
// Ant Design 5 Theme Config
// ═══════════════════════════════════════════════════════════

export const skymasterDarkTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    // Colors
    colorPrimary:      SKYMASTER_COLORS.accentPrimary,
    colorSuccess:      SKYMASTER_COLORS.success,
    colorWarning:      SKYMASTER_COLORS.warning,
    colorError:        SKYMASTER_COLORS.danger,
    colorInfo:         SKYMASTER_COLORS.info,

    // Backgrounds
    colorBgBase:       SKYMASTER_COLORS.bgBase,
    colorBgLayout:     SKYMASTER_COLORS.bgBase,
    colorBgContainer:  SKYMASTER_COLORS.bgElevated2,
    colorBgElevated:   SKYMASTER_COLORS.bgElevated1,

    // Text
    colorTextBase:     SKYMASTER_COLORS.textPrimary,
    colorText:         SKYMASTER_COLORS.textPrimary,
    colorTextSecondary:SKYMASTER_COLORS.textSecondary,
    colorTextTertiary: SKYMASTER_COLORS.textTertiary,
    colorTextDisabled: SKYMASTER_COLORS.disabled,

    // Borders
    colorBorder:          SKYMASTER_COLORS.borderPrimary,
    colorBorderSecondary: SKYMASTER_COLORS.borderSubtle,
    borderRadius:         4,
    borderRadiusLG:       6,
    borderRadiusSM:       2,

    // Typography
    fontFamily:     SKYMASTER_TYPOGRAPHY.fontSans,
    fontFamilyCode: SKYMASTER_TYPOGRAPHY.fontMono,
    fontSize:       SKYMASTER_TYPOGRAPHY.fsBody,
    fontSizeSM:     SKYMASTER_TYPOGRAPHY.fsCaption,
    fontSizeLG:     SKYMASTER_TYPOGRAPHY.fsH3,
    fontSizeXL:     SKYMASTER_TYPOGRAPHY.fsH2,
    fontSizeHeading1: SKYMASTER_TYPOGRAPHY.fsDisplay,
    fontSizeHeading2: SKYMASTER_TYPOGRAPHY.fsH1,
    fontSizeHeading3: SKYMASTER_TYPOGRAPHY.fsH2,
    fontSizeHeading4: SKYMASTER_TYPOGRAPHY.fsH3,

    // Shadows (禁用发光，仅保留极轻的层次阴影)
    boxShadow:       '0 1px 2px 0 rgba(0, 0, 0, 0.3)',
    boxShadowSecondary: '0 1px 2px 0 rgba(0, 0, 0, 0.2)',
    boxShadowTertiary:  '0 1px 2px 0 rgba(0, 0, 0, 0.1)',

    // Layout
    wireframe: false,
    motion: true,
    motionDurationFast: SKYMASTER_MOTION.hover,
    motionDurationMid:  SKYMASTER_MOTION.state,
    motionDurationSlow: SKYMASTER_MOTION.page,
  },
  components: {
    Layout: {
      headerBg:       SKYMASTER_COLORS.bgElevated1,
      siderBg:        SKYMASTER_COLORS.bgElevated1,
      bodyBg:         SKYMASTER_COLORS.bgBase,
      footerBg:       SKYMASTER_COLORS.bgElevated1,
      headerHeight:   48,
      headerPadding:  '0 24px',
    },
    Menu: {
      darkItemBg:            'transparent',
      darkItemHoverBg:       'rgba(57, 255, 20, 0.05)',
      darkItemSelectedBg:    'rgba(57, 255, 20, 0.1)',
      darkItemSelectedColor: SKYMASTER_COLORS.accentPrimary,
      darkItemColor:         SKYMASTER_COLORS.textSecondary,
      darkItemHoverColor:    SKYMASTER_COLORS.textPrimary,
      itemHeight:            44,
      iconSize:              16,
    },
    Button: {
      primaryShadow:          'none',
      defaultShadow:          'none',
      dangerShadow:           'none',
      defaultBorderColor:     SKYMASTER_COLORS.borderPrimary,
      defaultBg:              'transparent',
      defaultColor:           SKYMASTER_COLORS.textPrimary,
      defaultHoverBorderColor:SKYMASTER_COLORS.accentPrimary,
      defaultHoverColor:      SKYMASTER_COLORS.accentPrimary,
      colorTextLightSolid:    '#000000',  // 主按钮黑字
    },
    Card: {
      colorBgContainer:     SKYMASTER_COLORS.bgGlass,
      colorBorderSecondary: SKYMASTER_COLORS.borderPrimary,
      headerBg:             'transparent',
      headerFontSize:       SKYMASTER_TYPOGRAPHY.fsH3,
      headerHeight:         44,
    },
    Table: {
      headerBg:            SKYMASTER_COLORS.bgElevated1,
      headerColor:         SKYMASTER_COLORS.textSecondary,
      rowHoverBg:          'rgba(57, 255, 20, 0.05)',
      borderColor:         SKYMASTER_COLORS.borderSubtle,
      headerBorderRadius:  0,
    },
    Input: {
      colorBgContainer:    SKYMASTER_COLORS.bgBase,
      activeBorderColor:   SKYMASTER_COLORS.accentPrimary,
      hoverBorderColor:    SKYMASTER_COLORS.accentPrimaryDim,
      activeShadow:        'none',
      errorActiveShadow:   'none',
      warningActiveShadow: 'none',
    },
    Select: {
      colorBgContainer:  SKYMASTER_COLORS.bgBase,
      optionActiveBg:    'rgba(57, 255, 20, 0.1)',
      optionSelectedBg:  'rgba(57, 255, 20, 0.15)',
    },
    Modal: {
      contentBg:  SKYMASTER_COLORS.bgGlass,
      headerBg:   'transparent',
      titleColor: SKYMASTER_COLORS.textPrimary,
      footerBg:   'transparent',
    },
    Drawer: {
      colorBgElevated: SKYMASTER_COLORS.bgGlass,
    },
    Notification: {
      colorBgElevated: SKYMASTER_COLORS.bgElevated2,
      colorBorder:     SKYMASTER_COLORS.borderPrimary,
    },
    Progress: {
      defaultColor:     SKYMASTER_COLORS.accentPrimary,
      remainingColor:   SKYMASTER_COLORS.borderSubtle,
      circleTextColor:  SKYMASTER_COLORS.textPrimary,
    },
    Tag: {
      defaultBg:  'transparent',
      defaultColor: SKYMASTER_COLORS.textPrimary,
    },
    Tabs: {
      inkBarColor:            SKYMASTER_COLORS.accentPrimary,
      itemActiveColor:        SKYMASTER_COLORS.accentPrimary,
      itemHoverColor:         SKYMASTER_COLORS.textPrimary,
      itemSelectedColor:      SKYMASTER_COLORS.accentPrimary,
      titleFontSize:          SKYMASTER_TYPOGRAPHY.fsBody,
    },
    Switch: {
      colorPrimary:      SKYMASTER_COLORS.accentPrimary,
      colorPrimaryHover: SKYMASTER_COLORS.accentPrimaryDim,
    },
    Radio: {
      dotSize:               8,
      radioSize:             16,
      colorPrimary:          SKYMASTER_COLORS.accentPrimary,
      buttonSolidCheckedBg:  SKYMASTER_COLORS.accentPrimary,
      buttonSolidCheckedColor: '#000000',
    },
    Checkbox: {
      colorPrimary: SKYMASTER_COLORS.accentPrimary,
    },
    Slider: {
      trackBg:       SKYMASTER_COLORS.accentPrimary,
      trackHoverBg:  SKYMASTER_COLORS.accentPrimary,
      railBg:        SKYMASTER_COLORS.borderPrimary,
      handleColor:   SKYMASTER_COLORS.accentPrimary,
    },
    Tooltip: {
      colorBgSpotlight: SKYMASTER_COLORS.bgElevated2,
      colorTextLightSolid: SKYMASTER_COLORS.textPrimary,
    },
  },
};

export default skymasterDarkTheme;
