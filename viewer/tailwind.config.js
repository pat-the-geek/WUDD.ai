/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  safelist: [
    // Couleurs des entités NER (EntityHighlighter / EntityHighlighterSegments)
    // Classes listées explicitement pour éviter tout purge
    'bg-violet-100','text-violet-800','ring-violet-300',
    'bg-blue-100','text-blue-800','ring-blue-300',
    'bg-emerald-100','text-emerald-800','ring-emerald-300',
    'bg-orange-100','text-orange-800','ring-orange-300',
    'bg-amber-100','text-amber-800','ring-amber-300',
    'bg-red-100','text-red-800','ring-red-300',
    'bg-teal-100','text-teal-800','ring-teal-300',
    'bg-fuchsia-100','text-fuchsia-800','ring-fuchsia-300',
    'bg-cyan-100','text-cyan-800','ring-cyan-300',
    'bg-rose-100','text-rose-800','ring-rose-300',
    'bg-yellow-100','text-yellow-800','ring-yellow-300',
    'bg-lime-100','text-lime-800','ring-lime-300',
    'bg-indigo-100','text-indigo-800','ring-indigo-300',
    'bg-slate-100','text-slate-700','ring-slate-300',
    'bg-stone-100','text-stone-700','ring-stone-300',
    'bg-zinc-100','text-zinc-700','ring-zinc-300',
    'bg-gray-100','text-gray-700','ring-gray-300',
    // Variants dark
    'dark:bg-violet-900/50','dark:text-violet-200','dark:ring-violet-700',
    'dark:bg-blue-900/50','dark:text-blue-200','dark:ring-blue-700',
    'dark:bg-emerald-900/50','dark:text-emerald-200','dark:ring-emerald-700',
    'dark:bg-orange-900/50','dark:text-orange-200','dark:ring-orange-700',
    'dark:bg-amber-900/50','dark:text-amber-200','dark:ring-amber-700',
    'dark:bg-red-900/50','dark:text-red-200','dark:ring-red-700',
    'dark:bg-teal-900/50','dark:text-teal-200','dark:ring-teal-700',
    'dark:bg-fuchsia-900/50','dark:text-fuchsia-200','dark:ring-fuchsia-700',
    'dark:bg-cyan-900/50','dark:text-cyan-200','dark:ring-cyan-700',
    'dark:bg-rose-900/50','dark:text-rose-200','dark:ring-rose-700',
    'dark:bg-yellow-900/50','dark:text-yellow-200','dark:ring-yellow-700',
    'dark:bg-lime-900/50','dark:text-lime-200','dark:ring-lime-700',
    'dark:bg-indigo-900/50','dark:text-indigo-200','dark:ring-indigo-700',
    'dark:bg-slate-700','dark:text-slate-300','dark:ring-slate-600',
    'dark:bg-stone-700/60','dark:text-stone-300','dark:ring-stone-600',
    'dark:bg-zinc-700/60','dark:text-zinc-300','dark:ring-zinc-600',
    'dark:bg-gray-700/60','dark:text-gray-300','dark:ring-gray-600',
  ],
  theme: {
    extend: {
      fontFamily: {
        // Priorité à SF Pro sur les plateformes Apple, Inter Variable sur les autres
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Inter Variable"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
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
          DEFAULT: '#007AFF',          // iOS/macOS System Blue — light
          dark:    '#0A84FF',          // iOS/macOS System Blue — dark
          hover:   '#0071EB',          // légèrement plus sombre pour hover
          'dark-hover': '#1E8FFF',
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
    },
  },
  plugins: [],
}
