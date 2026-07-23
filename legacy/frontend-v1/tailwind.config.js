/**
 * TailwindCSS Config · SkyMaster Design System
 * 与 skymasterDarkTheme.ts + globals.css 保持 Token 对齐
 */

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class', // 暗黑独占，但保留能力
  theme: {
    extend: {
      colors: {
        base:     '#0d1117',
        elev1:    '#161b22',
        elev2:    '#1c2128',
        glass:    'rgba(22, 27, 34, 0.6)',
        border: {
          primary: '#30363d',
          subtle:  '#21262d',
        },
        text: {
          primary:   '#e6edf3',
          secondary: '#8b949e',
          tertiary:  '#6e7681',
        },
        accent: {
          primary:    '#39ff14',
          primaryDim: '#26a806',
          cyan:       '#00ffff',
          amber:      '#ffb000',
          red:        '#ff3838',
          purple:     '#b967ff',
          blue:       '#4c9aff',
        },
      },
      fontFamily: {
        sans:    ['Inter', 'HarmonyOS Sans SC', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'Fira Code', 'SF Mono', 'monospace'],
        display: ['Rajdhani', 'Orbitron', 'HarmonyOS Sans SC', 'sans-serif'],
      },
      fontSize: {
        'display':  ['40px', { lineHeight: '1.2', letterSpacing: '0.02em' }],
        'h1':       ['28px', '1.3'],
        'h2':       ['22px', '1.4'],
        'h3':       ['18px', '1.4'],
        'body':     ['14px', '1.6'],
        'caption':  ['12px', '1.5'],
        'mono-lg':  ['32px', '1.0'],
        'mono-md':  ['18px', '1.2'],
        'mono-sm':  ['12px', '1.4'],
      },
      borderRadius: {
        DEFAULT: '4px',
        sm: '2px',
        lg: '6px',
      },
      backdropBlur: {
        glass: '20px',
      },
      transitionTimingFunction: {
        skymaster: 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      transitionDuration: {
        hover: '150ms',
        state: '300ms',
        page:  '500ms',
      },
      animation: {
        'data-flow':   'dataFlow 3s linear infinite',
        'pulse-drone': 'pulse 2s ease-out infinite',
        'pulse-alert': 'pulse 0.5s ease-out infinite',
        'blink':       'blink 1s step-end infinite',
      },
      keyframes: {
        dataFlow: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        pulse: {
          '0%':   { transform: 'scale(1)',   opacity: '0.6' },
          '100%': { transform: 'scale(2.5)', opacity: '0'   },
        },
        blink: {
          '0%, 50%':  { opacity: '1' },
          '51%, 100%': { opacity: '0' },
        },
      },
      boxShadow: {
        // 明确禁用外发光，保留极轻阴影
        DEFAULT: '0 1px 2px 0 rgba(0, 0, 0, 0.3)',
        sm:      '0 1px 2px 0 rgba(0, 0, 0, 0.2)',
        lg:      '0 4px 12px 0 rgba(0, 0, 0, 0.5)',
        // 禁用发光类：仅示例说明不要使用
        // 'neon': '0 0 20px #39ff14',  ❌ 禁用
      },
    },
  },
  plugins: [],
};
