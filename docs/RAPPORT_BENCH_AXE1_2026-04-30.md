# Rapport benchmark Axe 1 — 30/04/2026

## Contexte

- Date: 30/04/2026
- Environnement: Docker compose local
- Endpoint runtime: `http://127.0.0.1:5050/api/runtime-info`
- Campagne: 3 passes par endpoint
- Outil: ApacheBench (`ab`)
- Paramètres: `-n 300 -c 20`

Runtime observé:

```json
{"default_viewer_port":5050,"project_root":"/app","viewer_port":5050}
```

---

## Résultats bruts

| Endpoint | Run | Failed | Non-2xx | p50 (ms) | p95 (ms) | Req/s |
|---|---:|---:|---:|---:|---:|---:|
| runtime_info | 1 | 0 | 0 | 4 | 15 | 3628.10 |
| runtime_info | 2 | 0 | 0 | 4 | 6 | 5185.92 |
| runtime_info | 3 | 0 | 0 | 3 | 6 | 5188.70 |
| files | 1 | 0 | 0 | 7 | 57 | 741.64 |
| files | 2 | 0 | 0 | 9 | 18 | 938.72 |
| files | 3 | 0 | 0 | 8 | 17 | 2198.11 |
| entities_compact | 1 | 0 | 0 | 4 | 267 | 545.99 |
| entities_compact | 2 | 0 | 0 | 5 | 12 | 1153.60 |
| entities_compact | 3 | 0 | 0 | 6 | 12 | 2906.84 |

---

## Synthèse (médiane des 3 runs)

| Endpoint | p50 médian (ms) | p95 médian (ms) | Failed total | Non-2xx total |
|---|---:|---:|---:|---:|
| runtime_info | 4 | 6 | 0 | 0 |
| files | 8 | 18 | 0 | 0 |
| entities_compact | 5 | 12 | 0 | 0 |

---

## Vérification des objectifs Axe 1

- Objectif `p95 /api/files < 400 ms`: OK (`18 ms` médian)
- Objectif `p95 /api/entities/articles compact < 500 ms`: OK (`12 ms` médian)
- Objectif `HTTP 5xx = 0`: OK (aucun échec)

Observation:

- Un pic isolé `p95=267 ms` est apparu sur le premier run `entities_compact`, puis retour à `12 ms` sur les 2 runs suivants (effet probable de warm-up cache/index).

---

## Ressources conteneurs (post-campagne courte)

| Conteneur | CPU | Mémoire | Mem % |
|---|---:|---:|---:|
| analyse-actualites-viewer | 0.11% | 565.4 MiB / 7.75 GiB | 7.12% |
| analyse-actualites-worker | 0.00% | 2.176 MiB / 7.75 GiB | 0.03% |

Conclusion:

- Pas de saturation visible CPU/RAM sur cette campagne courte.
- Le tuning actuel reste valide pour une charge interactive standard locale.
