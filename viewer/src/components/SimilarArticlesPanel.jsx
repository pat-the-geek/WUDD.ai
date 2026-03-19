import { useState, useEffect, useCallback } from 'react'
import {
  X, GitMerge, Loader2, ExternalLink,
  AlertTriangle, ChevronDown, ChevronUp, Check, Square, Sparkles,
} from 'lucide-react'

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreColor(s) {
  if (s >= 0.65) return 'text-emerald-600 dark:text-emerald-400'
  if (s >= 0.45) return 'text-amber-600 dark:text-amber-400'
  return 'text-slate-500 dark:text-slate-400'
}
function scoreBg(s) {
  if (s >= 0.65) return 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800'
  if (s >= 0.45) return 'bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800'
  return 'bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700'
}

// ── Composant principal ───────────────────────────────────────────────────────

/**
 * Panneau de recherche et fusion d'articles similaires.
 *
 * Props :
 *   article   — objet article source (format JSON WUDD.ai)
 *   filePath  — chemin relatif du fichier source (ex. "data/articles-from-rss/ia.json")
 *   onClose   — callback de fermeture
 *   onMerged  — callback appelé après une fusion réussie (ex. pour rafraîchir la liste)
 */
export default function SimilarArticlesPanel({ article, filePath, onClose, onMerged }) {
  const [loading, setLoading]       = useState(true)
  const [candidates, setCandidates] = useState([])
  const [selected, setSelected]     = useState({})   // url → candidate
  const [expandedUrl, setExpandedUrl] = useState(null)
  const [synthesis, setSynthesis]         = useState(null)  // null = pas encore générée
  const [synthesizing, setSynthesizing]   = useState(false)
  const [synthMode, setSynthMode]         = useState(null)   // 'ia' | 'structure'
  const [error, setError]                 = useState(null)
  const [merging, setMerging]             = useState(false)
  const [mergeResult, setMergeResult]     = useState(null)

  const articleUrl = article['URL'] ?? ''
  const articleTitle = article['Titre'] || article['Sources'] || articleUrl

  // ── Recherche des similaires au montage ──────────────────────────────────
  useEffect(() => {
    if (!articleUrl || !filePath) { setLoading(false); return }
    setLoading(true)
    fetch('/api/articles/merge/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ article_url: articleUrl, file_path: filePath }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => { setCandidates(d.candidates ?? []); setLoading(false) })
      .catch(e => { setError(`Erreur lors de la recherche : ${e}`); setLoading(false) })
  }, [articleUrl, filePath])

  // ── Sélection / déselection ───────────────────────────────────────────────
  const toggleSelect = useCallback((c) => {
    setSelected(prev => {
      const next = { ...prev }
      if (next[c.url]) delete next[c.url]
      else next[c.url] = c
      return next
    })
  }, [])

  const selectedList = Object.values(selected)
  const hasSynthesis = synthesis !== null && synthesis.trim().length > 0
  const canMerge     = selectedList.length > 0 && hasSynthesis && !merging

  // ── Génération de la synthèse IA ─────────────────────────────────────────
  const generateSynthesis = useCallback(async () => {
    setSynthesizing(true)
    setError(null)
    try {
      const r = await fetch('/api/articles/merge/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_article: article,
          candidates: selectedList.map(c => ({
            Sources:              c.source,
            'Date de publication': c.date,
            Résumé:               c.resume_extrait,  // extrait 300 car. — suffisant pour le prompt
          })),
        }),
      })
      const d = await r.json()
      setSynthesis(d.synthesis ?? '')
      setSynthMode(d.mode ?? null)
    } catch (e) {
      setError(`Erreur génération synthèse : ${e.message}`)
    } finally {
      setSynthesizing(false)
    }
  }, [article, selectedList])

  // ── Exécution de la fusion ────────────────────────────────────────────────
  const handleMerge = useCallback(async () => {
    if (!canMerge) return
    setMerging(true)
    setError(null)
    try {
      const r = await fetch('/api/articles/merge/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_url:       articleUrl,
          source_file_path: filePath,
          selected: selectedList.map(c => ({
            url:       c.url,
            file_path: c.file_path,
            score:     c.score,
          })),
          synthesis: synthesis?.trim() || undefined,
        }),
      })
      const d = await r.json()
      if (d.ok) {
        setMergeResult(d)
        onMerged?.()
      } else {
        setError(d.error ?? 'Erreur inconnue lors de la fusion')
      }
    } catch (e) {
      setError(`Erreur réseau : ${e.message}`)
    } finally {
      setMerging(false)
    }
  }, [canMerge, articleUrl, filePath, selectedList, synthesis, onMerged])

  // ── Rendu ─────────────────────────────────────────────────────────────────
  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-start justify-center overflow-y-auto p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div
        className="bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-white/50 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col my-2"
        style={{ height: 'calc(100dvh - 2rem)', maxHeight: '860px' }}
        onClick={e => e.stopPropagation()}
      >

        {/* ── En-tête ────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <div className="flex items-center gap-2">
            <GitMerge size={16} className="text-violet-500 dark:text-violet-400" />
            <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Articles similaires
            </span>
            {!loading && candidates.length > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800">
                {candidates.length} trouvé{candidates.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* ── Article source ─────────────────────────────────────────────── */}
        <div className="px-5 py-3 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-0.5">
            Article source
          </p>
          <p className="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">{articleTitle}</p>
          <p className="text-[10px] text-slate-400 dark:text-slate-500">
            {article['Sources']} · {article['Date de publication']}
          </p>
        </div>

        {/* ── Corps scrollable ───────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto min-h-0">

          {/* Chargement */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Loader2 size={22} className="text-violet-400 animate-spin" />
              <p className="text-sm text-slate-500 dark:text-slate-400">Recherche en cours…</p>
            </div>
          )}

          {/* Erreur (hors succès) */}
          {!loading && error && !mergeResult && (
            <div className="p-5">
              <div className="flex items-start gap-2 p-3 rounded-xl bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800">
                <AlertTriangle size={14} className="text-rose-500 shrink-0 mt-0.5" />
                <p className="text-xs text-rose-700 dark:text-rose-300">{error}</p>
              </div>
            </div>
          )}

          {/* Aucun résultat */}
          {!loading && !error && !mergeResult && candidates.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-center px-6">
              <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
                Aucun article similaire trouvé
              </p>
              <p className="text-xs text-slate-400 dark:text-slate-500">
                dans une fenêtre de 7 jours, score ≥ 35%
              </p>
            </div>
          )}

          {/* Liste des candidats */}
          {!loading && !mergeResult && candidates.length > 0 && (
            <div className="p-4 space-y-2">
              {candidates.map(c => {
                const isSelected = !!selected[c.url]
                const isExpanded = expandedUrl === c.url
                return (
                  <div
                    key={c.url}
                    className={`rounded-xl border transition-all ${
                      isSelected
                        ? 'border-violet-300 dark:border-violet-700 bg-violet-50/60 dark:bg-violet-900/20'
                        : 'border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-800/40'
                    }`}
                  >
                    <div className="p-3 flex items-start gap-3">
                      {/* Checkbox */}
                      <button
                        onClick={() => toggleSelect(c)}
                        className="mt-0.5 shrink-0 transition-colors"
                        title={isSelected ? 'Désélectionner' : 'Sélectionner pour fusion'}
                      >
                        {isSelected
                          ? <Check size={16} className="text-violet-500 dark:text-violet-400" />
                          : <Square size={16} className="text-slate-300 dark:text-slate-600" />
                        }
                      </button>

                      {/* Infos article */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                              {c.source}
                            </span>
                            {c.has_obsidian && (
                              <span className="text-[9px] px-1 py-0.5 rounded bg-violet-100 dark:bg-violet-900/40 text-violet-600 dark:text-violet-400 border border-violet-200 dark:border-violet-800">
                                Obsidian
                              </span>
                            )}
                          </div>
                          {/* Score composite */}
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border shrink-0 ${scoreBg(c.score)} ${scoreColor(c.score)}`}>
                            {Math.round(c.score * 100)}%
                          </span>
                        </div>

                        <p className="text-xs font-medium text-slate-700 dark:text-slate-200 mt-0.5 leading-tight line-clamp-2">
                          {c.titre || c.url}
                        </p>
                        <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">{c.date}</p>

                        {/* Scores détaillés + bouton extrait */}
                        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                          <span className="text-[9px] text-slate-400 dark:text-slate-500">
                            Entités {Math.round(c.score_entites * 100)}%
                          </span>
                          <span className="text-[9px] text-slate-300 dark:text-slate-600">·</span>
                          <span className="text-[9px] text-slate-400 dark:text-slate-500">
                            Texte {Math.round(c.score_bigrammes * 100)}%
                          </span>
                          {c.resume_extrait && (
                            <button
                              onClick={() => setExpandedUrl(v => v === c.url ? null : c.url)}
                              className="text-[9px] text-violet-400 hover:text-violet-600 dark:hover:text-violet-300 flex items-center gap-0.5 transition-colors ml-auto"
                            >
                              {isExpanded ? <><ChevronUp size={9} /> Moins</> : <><ChevronDown size={9} /> Extrait</>}
                            </button>
                          )}
                        </div>

                        {isExpanded && c.resume_extrait && (
                          <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed border-t border-slate-100 dark:border-slate-700 pt-2">
                            {c.resume_extrait}{c.resume_extrait.length >= 300 ? '…' : ''}
                          </p>
                        )}
                      </div>

                      {/* Lien externe */}
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        className="shrink-0 p-1 rounded-lg text-slate-300 hover:text-blue-500 dark:hover:text-blue-400 transition-colors"
                        title="Ouvrir l'article"
                      >
                        <ExternalLink size={12} />
                      </a>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* Résultat de fusion */}
          {mergeResult && (
            <div className="p-5 space-y-4">
              <div className="flex items-start gap-3 p-4 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800">
                <GitMerge size={16} className="text-emerald-500 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
                    Fusion réalisée
                  </p>
                  <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5">
                    {mergeResult.secondaries_count} article{mergeResult.secondaries_count > 1 ? 's' : ''} fusionné{mergeResult.secondaries_count > 1 ? 's' : ''} dans{' '}
                    <strong>{mergeResult.primary_source}</strong>
                  </p>
                  {mergeResult.obsidian_updated?.length > 0 && (
                    <p className="text-[11px] text-violet-600 dark:text-violet-400 mt-1">
                      {mergeResult.obsidian_updated.length} note{mergeResult.obsidian_updated.length > 1 ? 's' : ''} Obsidian mise{mergeResult.obsidian_updated.length > 1 ? 's' : ''} à jour
                    </p>
                  )}
                  <p className="text-[10px] text-emerald-500/70 dark:text-emerald-500/60 mt-1 font-mono break-all">
                    Archive : {mergeResult.archive_path}
                  </p>
                </div>
              </div>
              <p className="text-xs text-slate-400 dark:text-slate-500 text-center">
                Rafraîchissez la page pour voir la liste mise à jour.
              </p>
            </div>
          )}
        </div>

        {/* ── Pied de page ───────────────────────────────────────────────── */}
        {!mergeResult ? (
          <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-700 shrink-0 space-y-3">

            {/* Étape 1 : sélection en cours — bouton "Générer la synthèse" */}
            {selectedList.length > 0 && synthesis === null && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-[11px] text-slate-400 dark:text-slate-500">
                  {selectedList.length} article{selectedList.length > 1 ? 's' : ''} sélectionné{selectedList.length > 1 ? 's' : ''}
                  {' '}— générez la synthèse avant de fusionner
                </span>
                <button
                  onClick={generateSynthesis}
                  disabled={synthesizing}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-500 disabled:bg-violet-300 dark:disabled:bg-violet-800 text-white transition-colors shrink-0"
                >
                  {synthesizing
                    ? <><Loader2 size={12} className="animate-spin" /> Génération…</>
                    : <><Sparkles size={12} /> Générer la synthèse</>
                  }
                </button>
              </div>
            )}

            {/* Étape 2 : synthèse générée — éditable + bouton Fusionner */}
            {synthesis !== null && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                    Synthèse{' '}
                    {synthMode === 'ia'
                      ? <span className="normal-case font-normal text-violet-500 dark:text-violet-400">générée par l'IA</span>
                      : <span className="normal-case font-normal text-slate-400">structurée (IA indisponible)</span>
                    }
                  </label>
                  <button
                    onClick={generateSynthesis}
                    disabled={synthesizing}
                    title="Regénérer"
                    className="text-[10px] text-violet-400 hover:text-violet-600 dark:hover:text-violet-300 flex items-center gap-0.5 transition-colors"
                  >
                    {synthesizing ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                    {synthesizing ? 'Génération…' : 'Regénérer'}
                  </button>
                </div>
                <textarea
                  value={synthesis}
                  onChange={e => setSynthesis(e.target.value)}
                  rows={5}
                  className="w-full text-xs px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-1 focus:ring-violet-400 resize-none"
                />
              </div>
            )}

            {/* Barre d'actions basse */}
            <div className="flex items-center justify-between gap-3">
              <button
                onClick={onClose}
                className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
              >
                Annuler
              </button>
              {synthesis !== null && (
                <button
                  onClick={handleMerge}
                  disabled={!canMerge}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-violet-600 hover:bg-violet-500 disabled:bg-slate-200 dark:disabled:bg-slate-700 text-white disabled:text-slate-400 dark:disabled:text-slate-500 transition-colors"
                >
                  {merging
                    ? <><Loader2 size={12} className="animate-spin" /> Fusion en cours…</>
                    : <><GitMerge size={12} /> Fusionner ({selectedList.length})</>
                  }
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-700 shrink-0 flex justify-end">
            <button
              onClick={onClose}
              className="text-xs px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
            >
              Fermer
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
