import { useState, useRef, useEffect } from 'react'
import { Lock, Eye, EyeOff, LogIn } from 'lucide-react'
import wuddLogo from '../assets/wudd-prism-floyd.svg'

export default function LoginPage({ onAuthenticated }) {
  const [password, setPassword]   = useState('')
  const [showPwd, setShowPwd]     = useState(false)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const inputRef                  = useRef(null)

  useEffect(() => {
    // Mettre le focus sur le champ mot de passe au montage
    inputRef.current?.focus()
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!password) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      const data = await res.json()
      if (data.ok) {
        onAuthenticated()
      } else {
        setError(data.error || 'Mot de passe incorrect')
        setPassword('')
        inputRef.current?.focus()
      }
    } catch {
      setError('Erreur de connexion au serveur')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900 px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8 gap-3">
          <img src={wuddLogo} alt="WUDD.ai" className="w-16 h-16" />
          <h1 className="text-2xl font-semibold text-slate-800 dark:text-slate-100 tracking-tight">
            WUDD.ai
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Accès protégé — identifiez-vous pour continuer
          </p>
        </div>

        {/* Formulaire */}
        <form
          onSubmit={handleSubmit}
          className="bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 p-6 flex flex-col gap-4"
        >
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="password"
              className="text-xs font-medium text-slate-600 dark:text-slate-400 uppercase tracking-wide"
            >
              Mot de passe
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
                <Lock size={15} />
              </span>
              <input
                ref={inputRef}
                id="password"
                type={showPwd ? 'text' : 'password'}
                value={password}
                onChange={e => { setPassword(e.target.value); setError('') }}
                placeholder="••••••••"
                autoComplete="current-password"
                className="w-full pl-9 pr-10 py-2.5 rounded-xl border border-slate-200 dark:border-slate-600
                           bg-slate-50 dark:bg-slate-700/50
                           text-slate-800 dark:text-slate-100 text-sm
                           placeholder-slate-400 dark:placeholder-slate-500
                           focus:outline-none focus:ring-2 focus:ring-[#0066CC] dark:focus:ring-[#0A84FF]
                           transition"
              />
              <button
                type="button"
                onClick={() => setShowPwd(v => !v)}
                tabIndex={-1}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600
                           dark:hover:text-slate-300 p-0.5 rounded transition"
                aria-label={showPwd ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
              >
                {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          {/* Message d'erreur */}
          {error && (
            <p className="text-xs text-red-500 dark:text-red-400 -mt-1">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl
                       bg-[#0066CC] hover:bg-[#0055B3] dark:bg-[#0A84FF] dark:hover:bg-[#0070D8]
                       text-white font-medium text-sm
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2
                       focus:ring-[#0066CC] dark:focus:ring-[#0A84FF]"
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            ) : (
              <LogIn size={15} />
            )}
            {loading ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      </div>
    </div>
  )
}
