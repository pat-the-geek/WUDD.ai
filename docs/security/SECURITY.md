# Guide de Sécurité pour GitHub

## 🔐 Données Sensibles Protégées

Ce projet a été configuré pour **exclure automatiquement** toutes les données sensibles de GitHub.

### ✅ Fichiers protégés (ignorés par Git)

#### 1. Credentials et configuration
- `.env` - **CRITIQUE** : Contient les tokens API et URLs privées
- `.venv/`, `venv/`, `ENV/` - Environnements virtuels Python

#### 2. Données personnelles
- `data/raw/` - Contenu HTML brut des articles
- `data/articles/*.json` - Articles avec résumés et URLs potentiellement privées
- `rapports/markdown/*.md` - Rapports générés
- `rapports/pdf/*.pdf` - Exports PDF

#### 3. Archives et backups
- `archives/` - Anciennes versions de scripts (peuvent contenir credentials)
- `*.bak`, `*.tmp` - Fichiers temporaires

#### 4. Système
- `.DS_Store` - Métadonnées macOS
- `__pycache__/`, `*.pyc` - Cache Python
- Images (`.png`, `.jpg`, etc.) - Peuvent contenir captures d'écran sensibles

---

## 🚀 Configuration Initiale

### Avant le premier commit

1. **Vérifier que `.env` n'est PAS commité** :
   ```bash
   git status
   # .env ne doit PAS apparaître dans les fichiers à commiter
   ```

2. **Copier le template de configuration** :
   ```bash
   cp .env.example .env
   # Puis éditer .env avec vos vraies credentials
   ```

3. **Vérifier le .gitignore** :
   ```bash
   git check-ignore -v .env
   # Doit afficher : .gitignore:93:.env    .env
   ```

---

## ⚠️ Si vous avez DÉJÀ commité des données sensibles

### Méthode 1 : Supprimer de l'historique (recommandé)

```bash
# Supprimer .env de tout l'historique Git
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch .env" \
  --prune-empty --tag-name-filter cat -- --all

# Forcer le push (attention : réécrit l'historique)
git push origin --force --all
git push origin --force --tags
```

### Méthode 2 : Révoquer et régénérer les credentials

1. **Révoquer immédiatement** :
   - Aller sur Manager Infomaniak
   - Révoquer le token API actuel
   - Générer un nouveau token

2. **Supprimer le dépôt GitHub** et recréer depuis zéro

---

## 🔍 Vérifications Avant Chaque Push

### Checklist automatique

```bash
# 1. Vérifier qu'aucun fichier sensible n'est staged
git status

# 2. Rechercher des patterns sensibles dans les fichiers à commiter
git diff --cached | grep -i "bearer\|token\|password\|secret\|api_key"

# 3. Lister tous les fichiers qui seront commitésgit diff --cached --name-only

# 4. Vérifier qu'un .env n'est pas présent
git ls-files | grep "\.env$" && echo "⚠️ ALERTE: .env détecté !" || echo "✅ OK"
```

### Script de vérification automatique (pré-commit)

Créer `.git/hooks/pre-commit` :
```bash
#!/bin/bash
if git diff --cached --name-only | grep -q "\.env$"; then
    echo "❌ ERREUR: Tentative de commit de .env bloquée !"
    echo "Retirez .env avec: git reset HEAD .env"
    exit 1
fi

# Rechercher des patterns sensibles
if git diff --cached | grep -iE "(bearer|api[_-]?key|password|secret).*=.*[a-zA-Z0-9]{20,}"; then
    echo "⚠️ ATTENTION: Potentiel credential détecté dans le diff"
    echo "Vérifiez le contenu avant de continuer"
    read -p "Continuer quand même ? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
```

Rendre exécutable :
```bash
chmod +x .git/hooks/pre-commit
```

---

## 📋 Liste des Variables d'Environnement Sensibles

**Ne JAMAIS exposer publiquement** :

| Variable | Description | Risque |
|----------|-------------|--------|
| `bearer` | Token API Infomaniak EurIA | ⚠️ **CRITIQUE** - Accès complet à l'API payante |
| `REEDER_JSON_URL` | URL privée du flux JSON source | ⚠️ **ÉLEVÉ** - Exposition de votre liste d'articles |
| `URL` | Endpoint API avec Product ID | ⚠️ **MOYEN** - Révèle votre configuration |

---

## 🔄 Rotation des Secrets (Recommandé)

**Fréquence** : Tous les 3-6 mois ou immédiatement si compromis

### Procédure :
1. Générer nouveau token sur Manager Infomaniak
2. Mettre à jour `.env` localement
3. Tester les scripts
4. Révoquer l'ancien token
5. Documenter la date de rotation

---

## 📞 En Cas de Fuite de Données

### Actions immédiates :

1. **Révoquer tous les tokens** exposés
2. **Changer l'URL du flux JSON source** (si exposée)
3. **Supprimer le dépôt GitHub** (si historique compromis)
4. **Nettoyer l'historique Git** (filter-branch)
5. **Vérifier les logs d'accès API** chez Infomaniak
6. **Notifier** les personnes concernées

### Contacts :
- Support Infomaniak : https://www.infomaniak.com/fr/support
- Email projet : patrick.ostertag@gmail.com

---

## ✅ Bonnes Pratiques

- ✅ Toujours utiliser `.env` pour les secrets
- ✅ Vérifier `git status` avant chaque commit
- ✅ Utiliser `.env.example` pour documenter les variables nécessaires
- ✅ Ne jamais hardcoder de credentials dans le code
- ✅ Utiliser des tokens avec permissions minimales
- ✅ Activer l'authentification à deux facteurs sur GitHub
- ✅ Configurer des secret scanning alerts sur GitHub
- ✅ Configurer `ACCESS_PASSWORD` pour protéger le viewer sur un réseau partagé
- ✅ Définir `SECRET_KEY` en production pour des sessions persistantes
- ✅ Utiliser `ALLOWED_IPS` pour limiter l'accès à des adresses IP connues

---

## 🔐 Contrôle d'accès au Viewer

Le viewer WUDD.ai supporte trois mécanismes d'accès configurables via `.env` :

| Mécanisme | Variable | Comportement |
|-----------|----------|--------------|
| Mot de passe | `ACCESS_PASSWORD` | Page de connexion affichée si non authentifié |
| Whitelist IP | `ALLOWED_IPS` | IPs autorisées sans mot de passe |
| Clé de session | `SECRET_KEY` | Persistance des sessions entre redémarrages |
| Proxies de confiance | `TRUSTED_PROXIES` | IPs des proxies autorisés à définir `X-Forwarded-For` |

**Pourquoi PAS les adresses MAC :**  
Les adresses MAC (couche 2 / Ethernet) ne sont pas transmises dans les requêtes HTTP.
Le serveur Flask ne voit que l'adresse IP du client. Les adresses MAC sont locales
à chaque segment réseau et changent à chaque saut routeur — elles ne peuvent donc
pas servir de mécanisme d'identification fiable au niveau applicatif.

---

**Dernière mise à jour** : 28 mars 2026  
**Responsable sécurité** : Patrick Ostertag
