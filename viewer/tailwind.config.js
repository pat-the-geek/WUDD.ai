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
        // Inter Variable pour tout l'UI et le contenu éditorial
        sans: ['"Inter Variable"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        // Monospace système pour JSON et code (SF Mono / Cascadia / Menlo selon la plateforme)
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
