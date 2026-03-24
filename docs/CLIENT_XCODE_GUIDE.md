# WUDD.ai Client — Guide Xcode : De la Spécification à l'Application
## Version 1.0 — Mars 2026

---

## Prérequis

| Outil | Version requise |
|---|---|
| macOS | 14.0 Sonoma ou plus récent |
| Xcode | 15.0 ou plus récent |
| Compte développeur Apple | Requis pour déploiement sur devices physiques |
| Swift | 5.9+ (inclus avec Xcode 15) |

---

## Phase 1 — Création du Projet Xcode

### Étape 1.1 — Nouveau projet

1. Ouvrir Xcode → **File → New → Project**
2. Choisir la plateforme : **Multiplatform** (onglet en haut)
3. Sélectionner le template : **App**
4. Cliquer **Next**

### Étape 1.2 — Configuration du projet

Remplir les champs :

| Champ | Valeur |
|---|---|
| Product Name | `WUDDClient` |
| Team | Votre compte développeur Apple |
| Organization Identifier | `com.votredomaine` (ex: `com.wudd`) |
| Bundle Identifier | `com.votredomaine.WUDDClient` (auto-rempli) |
| Interface | **SwiftUI** |
| Language | **Swift** |
| Include Tests | **Cocher** (Unit Tests + UI Tests) |

5. Cliquer **Next**
6. Choisir un dossier de destination (ex: `~/Developer/WUDDClient`)
7. Cliquer **Create**

### Étape 1.3 — Configurer les cibles de déploiement

Dans le **Project Navigator** (panneau gauche), cliquer sur `WUDDClient` (icône bleue en haut).

Dans **TARGETS → WUDDClient** :
- Onglet **General** → **Minimum Deployments** :
  - iOS : `17.0`
  - macOS : `14.0`

Dans **PROJECT → WUDDClient** :
- Onglet **Info** → même configuration

---

## Phase 2 — Structure des Dossiers

### Étape 2.1 — Créer les groupes de dossiers

Dans le Project Navigator, faire **clic droit sur WUDDClient** → **New Group** pour créer la hiérarchie suivante :

```
WUDDClient/
├── App/
├── Core/
│   ├── Network/
│   ├── Models/
│   ├── Services/
│   └── Persistence/
├── Features/
│   ├── Onboarding/
│   ├── Articles/
│   │   └── ViewModels/
│   ├── Entities/
│   │   └── ViewModels/
│   ├── Search/
│   ├── Alerts/
│   ├── Reports/
│   │   └── ViewModels/
│   ├── Chatbot/
│   ├── Scheduler/
│   ├── Settings/
│   │   └── ViewModels/
│   ├── Quota/
│   └── TopArticles/
├── Shared/
│   ├── Components/
│   ├── Extensions/
│   └── Resources/
└── Tests/
```

**Conseil :** Créer les groupes sans créer les fichiers pour l'instant. Les fichiers seront ajoutés étape par étape.

### Étape 2.2 — Vérifier la structure de fichiers sur disque

Xcode crée les groupes comme des dossiers virtuels par défaut. Pour qu'ils correspondent à des vrais dossiers sur disque (recommandé) :

1. Sélectionner tous les groupes créés
2. Clic droit → **Convert to Folder** (ou lors de la création choisir **New Folder**)

---

## Phase 3 — Fichiers de Configuration Essentiels

### Étape 3.1 — Info.plist : Transport Security

Dans le **Project Navigator** → `WUDDClient/Info.plist` (ou via **TARGETS → WUDDClient → Info**) :

Ajouter la clé `NSAppTransportSecurity` :

1. Cliquer sur `+` pour ajouter une clé
2. Taper `NSAppTransportSecurity` → choisir le type `Dictionary`
3. Développer et ajouter :
   - Clé : `NSAllowsArbitraryLoads` → Type : `Boolean` → Valeur : `YES`

**Pourquoi :** Permet la connexion HTTP non-TLS vers l'adresse IP locale du serveur Flask (ex: `http://192.168.1.10:5050`).

### Étape 3.2 — Entitlements macOS

Dans **TARGETS → WUDDClient → Signing & Capabilities** :

1. Cliquer **+ Capability**
2. Ajouter **App Sandbox** (si pas déjà présent)
3. Dans les entitlements, cocher :
   - **Network → Outgoing Connections (Client)** : ON

---

## Phase 4 — Dépendances (Swift Package Manager)

### Étape 4.1 — Ajouter swift-markdown-ui

1. **File → Add Package Dependencies**
2. Dans la barre de recherche, coller : `https://github.com/gonzalezreal/swift-markdown-ui`
3. Choisir la version : **Up to Next Major Version** → `2.3.0`
4. Cliquer **Add Package**
5. Dans la fenêtre des targets, cocher `WUDDClient`
6. Cliquer **Add Package**

### Étape 4.2 — (Optionnel) Ajouter Kingfisher pour le cache d'images

1. **File → Add Package Dependencies**
2. Coller : `https://github.com/onevcat/Kingfisher`
3. Version : **Up to Next Major** → `7.0.0`
4. Ajouter au target `WUDDClient`

### Étape 4.3 — Ajouter mermaid.min.js

1. Télécharger `mermaid.min.js` depuis [https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js](https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js)
2. Glisser le fichier dans `Shared/Resources/` dans le Project Navigator
3. Dans la boîte de dialogue : vérifier que **Add to targets: WUDDClient** est coché
4. Vérifier dans **TARGETS → WUDDClient → Build Phases → Copy Bundle Resources** que `mermaid.min.js` y figure

---

## Phase 5 — Implémentation par Couches

L'ordre d'implémentation suit les dépendances : Core d'abord, puis Features, puis UI.

### Étape 5.1 — Core/Persistence/ServerConfig.swift

Créer le fichier `ServerConfig.swift` dans `Core/Persistence/` :

```swift
import Foundation
import Observation

@Observable
final class ServerConfig {
    static let shared = ServerConfig()
    private init() {}

    private let key = "serverURL"

    var serverURL: String {
        get { UserDefaults.standard.string(forKey: key) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: key) }
    }

    var isConfigured: Bool {
        !serverURL.isEmpty && URL(string: serverURL) != nil
    }

    func testConnection() async -> Bool {
        guard let url = URL(string: serverURL + "/api/files") else { return false }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }
}
```

### Étape 5.2 — Core/Network/APIError.swift

```swift
import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case httpError(Int)
    case decodingError(Error)
    case networkError(Error)
    case serverNotConfigured

    var errorDescription: String? {
        switch self {
        case .invalidURL:           return "URL du serveur invalide"
        case .httpError(let code):  return "Erreur serveur : \(code)"
        case .decodingError(let e): return "Erreur de décodage : \(e.localizedDescription)"
        case .networkError(let e):  return "Erreur réseau : \(e.localizedDescription)"
        case .serverNotConfigured:  return "Serveur non configuré"
        }
    }
}
```

### Étape 5.3 — Core/Network/APIClient.swift

Créer le fichier selon la spécification technique (section 4.1).

### Étape 5.4 — Core/Network/SSEClient.swift

Créer le fichier selon la spécification technique (section 4.2).

### Étape 5.5 — Core/Models/ — Tous les modèles

Créer un fichier par modèle selon la spécification technique (section 3) :
- `Article.swift`
- `Alert.swift`
- `EntityStat.swift`
- `FluxSource.swift`
- `SchedulerTask.swift`
- `SearchResult.swift`
- `QuotaConfig.swift`
- `FileMetadata.swift`
- `ScoredArticle.swift`
- `CooccurrenceEntry.swift`

### Étape 5.6 — Core/Services/

Créer les services (section 4.3 de la spec technique) :
- `ArticleService.swift`
- `EntityService.swift`
- `AlertService.swift`
- `SearchService.swift`
- `SettingsService.swift`
- `QuotaService.swift`
- `SchedulerService.swift`
- `ReportService.swift`

### Étape 5.7 — App/AppState.swift

Créer le fichier selon la spécification technique (section 8).

---

## Phase 6 — Shared Components

### Étape 6.1 — Shared/Extensions/Color+NER.swift

```swift
import SwiftUI

extension Color {
    static func nerColor(for type: String) -> Color {
        switch type.uppercased() {
        case "PERSON":   return .purple
        case "ORG":      return .blue
        case "GPE":      return .green
        case "LOC":      return .teal
        case "PRODUCT":  return .orange
        case "EVENT":    return .pink
        case "DATE":     return .gray
        case "MONEY":    return Color(red: 0.1, green: 0.6, blue: 0.3)
        default:         return .secondary
        }
    }
}
```

### Étape 6.2 — Shared/Components/SentimentBadge.swift

```swift
import SwiftUI

struct SentimentBadge: View {
    let sentiment: String?

    var body: some View {
        if let sentiment {
            Text(sentiment.capitalized)
                .font(.caption2)
                .fontWeight(.medium)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(color.opacity(0.15))
                .foregroundStyle(color)
                .clipShape(Capsule())
        }
    }

    private var color: Color {
        switch sentiment?.lowercased() {
        case "positif":  return .green
        case "négatif":  return .red
        default:         return .gray
        }
    }
}
```

### Étape 6.3 — Shared/Components/EntityChip.swift

```swift
import SwiftUI

struct EntityChip: View {
    let value: String
    let type: String

    var body: some View {
        Text(value)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.nerColor(for: type).opacity(0.12))
            .foregroundStyle(Color.nerColor(for: type))
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}
```

### Étape 6.4 — Shared/Components/MermaidView.swift

Créer selon la spécification technique (section 6). Sur macOS, utiliser `NSViewRepresentable` au lieu de `UIViewRepresentable` :

```swift
#if os(iOS)
import UIKit
typealias PlatformViewRepresentable = UIViewRepresentable
#else
import AppKit
typealias PlatformViewRepresentable = NSViewRepresentable
#endif
```

### Étape 6.5 — Shared/Components/MarkdownRenderer.swift

Créer selon la spécification technique (section 7). Import `MarkdownUI` (package ajouté à l'étape 4.1).

---

## Phase 7 — Feature : Onboarding (Configuration Serveur)

### Étape 7.1 — Features/Onboarding/ServerSetupView.swift

```swift
import SwiftUI

struct ServerSetupView: View {
    @State private var urlInput: String = ""
    @State private var isTesting = false
    @State private var testResult: Bool? = nil
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(spacing: 32) {
            // Logo et titre
            VStack(spacing: 8) {
                Image(systemName: "newspaper.circle.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.blue)
                Text("WUDD.ai")
                    .font(.largeTitle.bold())
                Text("Votre veille intelligente")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            // Formulaire
            VStack(alignment: .leading, spacing: 12) {
                Text("Adresse du serveur")
                    .font(.headline)

                TextField("http://192.168.1.10:5050", text: $urlInput)
                    .textFieldStyle(.roundedBorder)
                    #if os(iOS)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .autocapitalization(.none)
                    #endif

                Text("Exemple : http://192.168.1.10:5050 ou https://wudd.mondomaine.com")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if let error = errorMessage {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(.red)
                }

                if let result = testResult {
                    Label(
                        result ? "Connexion réussie" : "Serveur inaccessible",
                        systemImage: result ? "checkmark.circle" : "xmark.circle"
                    )
                    .foregroundStyle(result ? .green : .red)
                }
            }
            .padding()
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))

            // Actions
            VStack(spacing: 12) {
                Button {
                    Task { await testConnection() }
                } label: {
                    if isTesting {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Tester la connexion", systemImage: "network")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.bordered)
                .disabled(urlInput.isEmpty || isTesting)

                Button("Enregistrer et continuer") {
                    saveAndContinue()
                }
                .buttonStyle(.borderedProminent)
                .disabled(testResult != true)
            }
        }
        .padding(32)
        .frame(maxWidth: 480)
    }

    private func testConnection() async {
        isTesting = true
        testResult = nil
        errorMessage = nil
        ServerConfig.shared.serverURL = urlInput.trimmingCharacters(in: .whitespaces)
        testResult = await ServerConfig.shared.testConnection()
        if testResult == false {
            errorMessage = "Impossible de joindre le serveur. Vérifiez l'adresse et que le serveur est démarré."
        }
        isTesting = false
    }

    private func saveAndContinue() {
        ServerConfig.shared.serverURL = urlInput.trimmingCharacters(in: .whitespaces)
    }
}
```

---

## Phase 8 — Feature : Articles

### Étape 8.1 — Implémenter ArticleListViewModel

Dans `Features/Articles/ViewModels/ArticleListViewModel.swift` :

```swift
import Foundation
import Observation

@Observable
final class ArticleListViewModel {
    var articles: [Article] = []
    var isLoading = false
    var errorMessage: String?
    var filterSentiment: String? = nil
    var sortOrder: SortOrder = .dateDesc

    enum SortOrder { case dateDesc, dateAsc, scoreDesc }

    private let service = ArticleService()

    func load(path: String) async {
        isLoading = true
        errorMessage = nil
        do {
            articles = try await service.loadArticles(path: path)
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    var filteredArticles: [Article] {
        var result = articles
        if let sentiment = filterSentiment {
            result = result.filter { $0.sentiment == sentiment }
        }
        switch sortOrder {
        case .dateDesc: result.sort { $0.datePublication > $1.datePublication }
        case .dateAsc:  result.sort { $0.datePublication < $1.datePublication }
        case .scoreDesc: result.sort { ($0.scoreSource ?? 0) > ($1.scoreSource ?? 0) }
        }
        return result
    }
}
```

### Étape 8.2 — Implémenter ArticleCard et ArticleListView

Suivre les spécifications fonctionnelles (section 3.2) pour créer les composants visuels avec SwiftUI.

---

## Phase 9 — Feature : Streaming SSE dans les Views

### Exemple : SynthèseView avec streaming

```swift
import SwiftUI

struct EntitySynthesisView: View {
    let entityType: String
    let entityValue: String

    @State private var content = ""
    @State private var isStreaming = false
    private let sseClient = SSEClient()

    var body: some View {
        ScrollView {
            MarkdownRenderer(content: content, isStreaming: isStreaming)
        }
        .navigationTitle(entityValue)
        .toolbar {
            Button("Régénérer") { startStream() }
                .disabled(isStreaming)
        }
        .task { startStream() }
        .onDisappear { sseClient.cancel() }
    }

    private func startStream() {
        content = ""
        isStreaming = true

        guard let url = URL(string: ServerConfig.shared.serverURL
            + "/api/synthesize-topic"
            + "?entity_type=\(entityType.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")"
            + "&entity_value=\(entityValue.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")"
        ) else { return }

        sseClient.stream(url: url) { chunk in
            content += chunk
        } onComplete: {
            isStreaming = false
        }
    }
}
```

---

## Phase 10 — Navigation Principale (App Entry Point)

### Étape 10.1 — App/WUDDClientApp.swift

```swift
import SwiftUI

@main
struct WUDDClientApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appState)
        }
        #if os(macOS)
        .defaultSize(width: 1200, height: 800)
        #endif
    }
}
```

### Étape 10.2 — App/RootView.swift

```swift
import SwiftUI

struct RootView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        if !appState.serverConfig.isConfigured {
            ServerSetupView()
        } else {
            #if os(iOS)
            if UIDevice.current.userInterfaceIdiom == .pad {
                SplitContentView()
            } else {
                TabContentView()
            }
            #else
            SplitContentView()  // macOS
            #endif
        }
    }
}
```

---

## Phase 11 — Build et Tests

### Étape 11.1 — Build pour le simulateur

1. Dans la barre Xcode, sélectionner la cible :
   - iOS : `iPhone 16 Pro` (simulateur)
   - macOS : `My Mac`
2. **Product → Build** (`⌘B`)
3. Corriger les erreurs de compilation (normalement liées à des imports manquants)

### Étape 11.2 — Run sur simulateur

1. **Product → Run** (`⌘R`)
2. L'app se lance — l'écran de configuration serveur apparaît
3. Entrer l'URL du backend local : `http://localhost:5050` (si backend tourne sur la même machine)
4. Tester la connexion → si OK, explorer les features

### Étape 11.3 — Lancer les tests unitaires

1. **Product → Test** (`⌘U`)
2. Vérifier le rapport dans le **Report Navigator** (onglet 6)

### Étape 11.4 — Run sur device physique

1. Connecter l'iPhone ou iPad en USB
2. Dans la barre Xcode, sélectionner le device physique
3. Dans **TARGETS → Signing & Capabilities** : choisir votre Team
4. **Product → Run** (`⌘R`)

---

## Phase 12 — Déploiement

### Distribution ad-hoc (test interne)

1. **Product → Archive** (`⌘⇧B` puis Archive)
2. Dans **Organizer** → sélectionner l'archive → **Distribute App**
3. Choisir **Ad Hoc** ou **Development**
4. Exporter le `.ipa` et installer via **Apple Configurator** ou **TestFlight**

### Distribution via TestFlight

1. Créer l'app sur [App Store Connect](https://appstoreconnect.apple.com)
2. **Product → Archive → Distribute App → App Store Connect**
3. Uploader le build
4. Sur App Store Connect → TestFlight → Ajouter testeurs

### App Store

1. Préparer les captures d'écran (6.5", 5.5", iPad Pro 12.9")
2. Remplir la fiche App Store (description, catégorie, PEGI)
3. Soumettre via **Distribute App → App Store Connect**

---

## Checklist de Développement

### Phase 1 — MVP (Fonctionnalités essentielles)
- [ ] Configuration serveur (URL + test de connexion)
- [ ] Navigation principale (TabView iPhone / SplitView iPad+Mac)
- [ ] Liste des flux et articles
- [ ] Détail article (résumé, entités, sentiment)
- [ ] Recherche globale
- [ ] Alertes (liste + niveaux)

### Phase 2 — Enrichissements
- [ ] Tableau de bord entités (liste + stats)
- [ ] Détail entité (articles, co-occurrences)
- [ ] Synthèse IA streamée (SSE)
- [ ] Top articles
- [ ] Sources / crédibilité
- [ ] Rapport complet article (SSE + Markdown)

### Phase 3 — Fonctionnalités avancées
- [ ] Carte géographique (MapKit + geocoding)
- [ ] Galerie images entités
- [ ] Chronologie entités
- [ ] Rapport complet entité (SSE multi-phases)
- [ ] Chatbot IA (SSE)
- [ ] Planificateur (cron status)
- [ ] Quotas (sliders + compteurs)
- [ ] Diagrammes Mermaid (WKWebView)

### Phase 4 — Finalisation
- [ ] Annotations (notes + tags)
- [ ] TTS (lecture à voix haute)
- [ ] Partage natif (Share Sheet)
- [ ] Export PDF / Markdown
- [ ] Mode hors ligne (cache)
- [ ] Tests unitaires (>80% couverture Core/)
- [ ] Tests UI (parcours principaux)
- [ ] Accessibilité VoiceOver
- [ ] Icône app + écran de lancement

---

## Ressources Complémentaires

| Ressource | URL |
|---|---|
| Documentation SwiftUI | https://developer.apple.com/documentation/swiftui |
| Swift Charts | https://developer.apple.com/documentation/charts |
| MapKit SwiftUI | https://developer.apple.com/documentation/mapkit/mapview |
| URLSession async/await | https://developer.apple.com/documentation/foundation/urlsession |
| swift-markdown-ui | https://github.com/gonzalezreal/swift-markdown-ui |
| Human Interface Guidelines | https://developer.apple.com/design/human-interface-guidelines |
| App Store Connect | https://appstoreconnect.apple.com |

---

## Conseils Importants

1. **Tester sur device réel dès que possible** — le comportement réseau diffère du simulateur
2. **L'URL HTTP locale ne fonctionnera pas sur App Store** sans justification — prévoir HTTPS pour la production
3. **App Transport Security** : pour l'accès à une IP locale, `NSAllowsArbitraryLoads` est nécessaire mais à documenter dans l'App Store review notes
4. **Background networking** : pour les longues synthèses SSE, utiliser `URLSessionConfiguration.background` si l'app doit continuer à streamer en arrière-plan
5. **Multitasking iPad** : tester en Split View et Slide Over (le NavigationSplitView gère bien ces cas automatiquement)
6. **Dynamic Type** : utiliser uniquement `.font(.headline)`, `.font(.body)`, etc. — jamais de tailles fixes en points
