# Cron & Docker — AnalyseActualités

> Document de référence · Version 2.1 · 3 mars 2026

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture d'exécution](#2-architecture-dexécution)
3. [Configuration crontab](#3-configuration-crontab)
4. [Build & déploiement Docker](#4-build--déploiement-docker)
5. [Surveillance et alertes](#5-surveillance-et-alertes)
6. [Logs](#6-logs)
7. [Bonnes pratiques](#7-bonnes-pratiques)

---

## 1. Vue d'ensemble

### Principe

Toutes les tâches planifiées sont **exclusivement gérées dans le conteneur Docker** via une crontab personnalisée. Aucune tâche cron n'est programmée sur l'hôte.

### Tâches actives (vérification 03/03/2026)

| Tâche | Script | Fréquence | Log |
| --- | --- | --- | --- |
| Scheduler d'articles | `scheduler_articles.py` | Lundi 6h | `/app/rapports/cron_scheduler.log` |
| Extraction par mot-clé | `get-keyword-from-rss.py` | Toutes les 2h de 6h à 22h (9×/jour) | `/app/rapports/cron_get_keyword.log` |
| Surveillance cron | `check_cron_health.py` | Toutes les 10 min | `/app/rapports/cron_health.log` |

---

## 2. Architecture d'exécution

```mermaid
flowchart TB
    subgraph HOST["Hôte (macOS / serveur)"]
        ENV[".env\nCrédentials & config"]
        DOCKER_CMD["docker run\n--env-file .env"]
    end

    subgraph CONTAINER["Conteneur Docker (python:3.10)"]
        CRON_SVC["Service cron\n(mode foreground)"]
        CRONTAB["/etc/cron.d/scheduler_cron\n(copie de ./crontab)"]

        subgraph JOBS["Jobs planifiés"]
            J1["scheduler_articles.py\nLundi 6h00"]
            J2["get-keyword-from-rss.py\nToutes les 2h (6h-22h)"]
            J3["check_cron_health.py\nToutes les 10 min"]
        end

        subgraph LOGS["Logs"]
            L1["/app/rapports/cron_scheduler.log"]
            L2["/app/rapports/cron_get_keyword.log"]
            L3["/app/rapports/cron_health.log"]
        end

        subgraph VOLUMES["Volumes montés"]
            V1["/app/rapports → ./rapports"]
            V2["/app/data → ./data"]
        end
    end

    subgraph ALERT["Notification"]
        SMTP["SMTP\n(alertes mail)"]
    end

    ENV --> DOCKER_CMD
    DOCKER_CMD --> CONTAINER
    CRONTAB --> CRON_SVC
    CRON_SVC --> J1 & J2 & J3
    J1 --> L1
    J2 --> L2
    J3 --> L3
    J3 -->|Échec détecté| SMTP

    classDef job fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#333333
    classDef log fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px,color:#333333
    classDef alert fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#333333
    class J1,J2,J3 job
    class L1,L2,L3 log
    class SMTP alert
```

---

## 3. Configuration crontab

### Fichier `crontab` (racine du projet)

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Scheduler d'articles — chaque lundi à 6h
0 6 * * 1 root cd /app && python3 scripts/scheduler_articles.py >> /app/rapports/cron_scheduler.log 2>&1

# Extraction par mot-clé — toutes les 2h de 6h à 22h (6,8,10,12,14,16,18,20,22)
0 6-22/2 * * * root cd /app && python3 scripts/get-keyword-from-rss.py 2>&1 | tee -a /app/rapports/cron_get_keyword.log

# Surveillance santé cron — toutes les 10 minutes
*/10 * * * * root cd /app && python3 scripts/check_cron_health.py >> /app/rapports/cron_health.log 2>&1
```

> Le fichier est copié dans `/etc/cron.d/scheduler_cron` lors du build Docker (format avec utilisateur `root` sur chaque ligne, obligatoire pour `/etc/cron.d/`).

### Cycle de vie de la planification

```mermaid
sequenceDiagram
    participant Docker
    participant Cron
    participant Script
    participant Log
    participant Mail

    Docker->>Cron: Lancement (CMD cron -f)
    loop Chaque déclenchement programmé
        Cron->>Script: Exécution (cd /app && python3 ...)
        Script->>Log: Écriture résultats / erreurs
    end
    loop Toutes les 10 min
        Cron->>Script: check_cron_health.py
        Script->>Log: fraîcheur cron_test.log OK ?
        alt Inactivité ou erreur détectée
            Script->>Mail: Alerte SMTP administrateur
        end
    end
```

---

## 4. Build & déploiement Docker

### Build de l'image

```bash
docker build -t wudd-ai .
```

### Lancement du conteneur

```bash
docker run --env-file .env -d \
  --name wudd-ai-final \
  -v $(pwd)/rapports:/app/rapports \
  -v $(pwd)/data:/app/data \
  wudd-ai
```

### Vérification immédiate

```bash
# Le fichier de test doit être mis à jour chaque minute
docker exec wudd-ai-final cat /app/cron_test.log

# Recharger la crontab après modification
docker exec wudd-ai-final service cron reload
```

---

## 5. Surveillance et alertes

### Fonctionnement de `check_cron_health.py`

```mermaid
flowchart TD
    START([Déclenchement toutes les 10 min]) --> CHECK_LOG{cron_test.log\nmodifié < 2 min ?}
    CHECK_LOG -->|Oui| CHECK_ERR{Erreurs dans\ncron_scheduler.log ?}
    CHECK_LOG -->|Non| ALERT_INACTIF["Alerte : cron inactif"]
    CHECK_ERR -->|Non| OK([Santé OK — log entry])
    CHECK_ERR -->|Oui| ALERT_ERR["Alerte : erreur scheduler"]
    ALERT_INACTIF --> SEND_MAIL["Envoi mail SMTP\n(variables .env)"]
    ALERT_ERR --> SEND_MAIL

    classDef ok fill:#e8f5e9,stroke:#388e3c,color:#333333
    classDef err fill:#ffebee,stroke:#c62828,color:#333333
    class OK ok
    class ALERT_INACTIF,ALERT_ERR,SEND_MAIL err
```

### Variables d'environnement de notification (`.env`)

```env
CRON_ALERT_MAIL=admin@example.com
CRON_ALERT_FROM=cron-bot@example.com
CRON_ALERT_SMTP=smtp.example.com
CRON_ALERT_PORT=587
CRON_ALERT_USER=monuser
CRON_ALERT_PASS=motdepasse
```

---

## 6. Logs

| Fichier | Contenu | Commande de consultation |
| --- | --- | --- |
| `/app/rapports/cron_scheduler.log` | Sorties du scheduler d'articles | `docker exec analyse-actualites tail -n 50 /app/rapports/cron_scheduler.log` |
| `/app/rapports/cron_get_keyword.log` | Sorties extraction mot-clé (9×/jour) | `docker exec analyse-actualites tail -n 50 /app/rapports/cron_get_keyword.log` |
| `/app/rapports/cron_health.log` | Résultats surveillance santé | `docker exec analyse-actualites tail -n 50 /app/rapports/cron_health.log` |

---

## 7. Bonnes pratiques

- **Format `/etc/cron.d/`** : inclure l'utilisateur (`root`) sur chaque ligne de tâche
- **Recharger après modification** : `docker exec wudd-ai-final service cron reload`
- **Tester le SMTP** avec un serveur de test avant passage en production
- **Adapter la fréquence** de `check_cron_health.py` selon la criticité
- **Consulter régulièrement** `cron_health.log` et `cron_scheduler.log`
- **Volumes montés** : les dossiers `rapports/` et `data/` persistent hors du conteneur

---

**Dernière mise à jour** : 3 mars 2026 · Version 2.1
