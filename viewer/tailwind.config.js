/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Priorité à SF Pro sur les plateformes Apple, Inter Variable sur les autres
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Inter Variable"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        // Literata Variable : police optimisée pour la lecture longue (Google Play Books)
        reading: ['"Literata Variable"', 'Literata', 'Georgia', 'ui-serif', 'serif'],
        // SF Mono sur Apple, puis chaîne monospace système
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
      },
      // ── Échelle typographique HIG (Apple Human Interface Guidelines) ──────
      // Source : developer.apple.com/design/human-interface-guidelines/typography
      // Valeurs adaptées web (px) depuis les points iOS/macOS
      fontSize: {
        'hig-large-title':    ['34px', { lineHeight: '41px', fontWeight: '400' }],
        'hig-title1':         ['28px', { lineHeight: '34px', fontWeight: '400' }],
        'hig-title2':         ['22px', { lineHeight: '28px', fontWeight: '400' }],
        'hig-title3':         ['20px', { lineHeight: '25px', fontWeight: '600' }],
        'hig-headline':       ['17px', { lineHeight: '22px', fontWeight: '600' }],
        'hig-body':           ['17px', { lineHeight: '22px', fontWeight: '400' }],
        'hig-callout':        ['16px', { lineHeight: '21px', fontWeight: '400' }],
        'hig-subheadline':    ['15px', { lineHeight: '20px', fontWeight: '400' }],
        'hig-footnote':       ['13px', { lineHeight: '18px', fontWeight: '400' }],
        'hig-caption1':       ['12px', { lineHeight: '16px', fontWeight: '400' }],
        'hig-caption2':       ['11px', { lineHeight: '13px', fontWeight: '400' }],
      },
      // ── Couleurs système Apple (HIG System Colors) ───────────────────────
      // Utiliser 'accent' au lieu de 'blue-600' pour les CTA et états actifs
      colors: {
        accent: {
          DEFAULT: 'var(--color-accent)',
          hover: 'var(--color-accent-hover)',
          subtle: 'var(--color-accent-subtle)',
        },
        'hig-green':  { DEFAULT: '#34C759', dark: '#30D158' },
        'hig-red':    { DEFAULT: '#FF3B30', dark: '#FF453A' },
        'hig-orange': { DEFAULT: '#FF9500', dark: '#FF9F0A' },
        'hig-yellow': { DEFAULT: '#FFCC00', dark: '#FFD60A' },
        'hig-teal':   { DEFAULT: '#5AC8FA', dark: '#64D2FF' },
        'hig-indigo': { DEFAULT: '#5856D6', dark: '#5E5CE6' },
        'hig-purple': { DEFAULT: '#AF52DE', dark: '#BF5AF2' },
        'hig-pink':   { DEFAULT: '#FF2D55', dark: '#FF375F' },
      },
      spacing: {
        'hig-xs': '4px',
        'hig-sm': '8px',
        'hig-md': '16px',
        'hig-lg': '24px',
        'hig-xl': '32px',
        'hig-2xl': '48px',
      },
    },
  },
  plugins: [],
}
