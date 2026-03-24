# WUDD.ai — Spécification Technique Client Natif
## Version 1.0 — Mars 2026

---

## 1. Stack Technique

| Composant | Technologie | Version minimale |
|---|---|---|
| Langage | Swift | 5.9+ |
| Framework UI | SwiftUI | iOS 17 / macOS 14 |
| Graphiques | Swift Charts | iOS 16 / macOS 13 |
| Cartographie | MapKit (SwiftUI) | iOS 17 / macOS 14 |
| Rendu Markdown | swift-markdown-ui (Gonzalo Nuñez) | 2.3+ |
| Rendu Mermaid | WKWebView + mermaid.min.js (CDN local) | — |
| HTTP / REST | URLSession (async/await) | — |
| SSE Streaming | URLSession.bytes (AsyncSequence) | — |
| Cache disque | URLCache (système) + FileManager | — |
| Cache mémoire | NSCache | — |
| Persistance config | UserDefaults | — |
| Persistance légère | SwiftData (ou UserDefaults pour MVP) | iOS 17 / macOS 14 |
| Gestion d'état | @Observable (Observation framework) | iOS 17 / macOS 14 |
| Concurrence | Swift Concurrency (async/await, actors) | — |
| Tests unitaires | XCTest | — |
| Tests UI | XCUITest | — |

---

## 2. Architecture du Projet

### 2.1 Pattern : MVVM + Services

```
WUDDClient/
├── App/
│   ├── WUDDClientApp.swift          # @main, AppDelegate si nécessaire
│   └── AppState.swift               # Observable global state
│
├── Core/
│   ├── Network/
│   │   ├── APIClient.swift          # URLSession wrapper, base URL, headers
│   │   ├── SSEClient.swift          # Server-Sent Events streaming client
│   │   ├── NetworkMonitor.swift     # NWPathMonitor — statut réseau
│   │   └── APIError.swift           # Types d'erreurs enum
│   │
│   ├── Models/                      # Structs Codable mappant le JSON backend
│   │   ├── Article.swift
│   │   ├── Entity.swift
│   │   ├── Alert.swift
│   │   ├── FluxSource.swift
│   │   ├── QuotaConfig.swift
│   │   ├── SchedulerTask.swift
│   │   ├── SearchResult.swift
│   │   └── ...
│   │
│   ├── Services/                    # Couche métier — appels API groupés
│   │   ├── ArticleService.swift
│   │   ├── EntityService.swift
│   │   ├── AlertService.swift
│   │   ├── ReportService.swift
│   │   ├── SearchService.swift
│   │   ├── SettingsService.swift
│   │   ├── QuotaService.swift
│   │   └── SchedulerService.swift
│   │
│   └── Persistence/
│       ├── ServerConfig.swift       # UserDefaults wrapper pour l'URL serveur
│       ├── CacheManager.swift       # NSCache + URLCache
│       └── AnnotationStore.swift    # Cache local des annotations
│
├── Features/
│   ├── Onboarding/
│   │   ├── ServerSetupView.swift
│   │   └── ServerSetupViewModel.swift
│   │
│   ├── Articles/
│   │   ├── FluxListView.swift
│   │   ├── ArticleListView.swift
│   │   ├── ArticleDetailView.swift
│   │   ├── ArticleCard.swift
│   │   ├── ArticleFullReportView.swift
│   │   ├── SimilarArticlesPanel.swift
│   │   └── ViewModels/
│   │       ├── FluxListViewModel.swift
│   │       ├── ArticleListViewModel.swift
│   │       └── ArticleDetailViewModel.swift
│   │
│   ├── Entities/
│   │   ├── EntityDashboardView.swift
│   │   ├── EntityDetailView.swift
│   │   ├── EntityFullReportView.swift
│   │   ├── EntityMapView.swift
│   │   ├── EntityGalleryView.swift
│   │   ├── EntityTimelineView.swift
│   │   └── ViewModels/
│   │       ├── EntityDashboardViewModel.swift
│   │       └── EntityDetailViewModel.swift
│   │
│   ├── Search/
│   │   ├── SearchView.swift
│   │   └── SearchViewModel.swift
│   │
│   ├── Alerts/
│   │   ├── AlertsView.swift
│   │   ├── AlertRulesView.swift
│   │   └── AlertsViewModel.swift
│   │
│   ├── Reports/
│   │   ├── ReportListView.swift
│   │   ├── MarkdownReportView.swift
│   │   └── ViewModels/
│   │       └── ReportViewModel.swift
│   │
│   ├── Chatbot/
│   │   ├── ChatbotView.swift
│   │   ├── ChatbotBubble.swift
│   │   └── ChatbotViewModel.swift
│   │
│   ├── Scheduler/
│   │   ├── SchedulerView.swift
│   │   └── SchedulerViewModel.swift
│   │
│   ├── Settings/
│   │   ├── SettingsView.swift
│   │   ├── ServerSettingsView.swift
│   │   ├── FluxSettingsView.swift
│   │   ├── KeywordSettingsView.swift
│   │   ├── RSSFeedSettingsView.swift
│   │   ├── ProviderSettingsView.swift
│   │   └── ViewModels/
│   │       └── SettingsViewModel.swift
│   │
│   ├── Quota/
│   │   ├── QuotaView.swift
│   │   └── QuotaViewModel.swift
│   │
│   └── TopArticles/
│       ├── TopArticlesView.swift
│       └── TopArticlesViewModel.swift
│
├── Shared/
│   ├── Components/
│   │   ├── SentimentBadge.swift     # Badge coloré sentiment
│   │   ├── EntityChip.swift         # Chip entité avec couleur NER
│   │   ├── EntityHighlighter.swift  # Texte avec entités surlignées
│   │   ├── MarkdownRenderer.swift   # Wrapper swift-markdown-ui
│   │   ├── MermaidView.swift        # WKWebView pour diagrammes Mermaid
│   │   ├── SSEProgressView.swift    # Indicateur streaming SSE
│   │   ├── ConnectionStatusBar.swift
│   │   ├── LoadingView.swift
│   │   ├── ErrorView.swift
│   │   └── ScoreGauge.swift
│   │
│   ├── Extensions/
│   │   ├── Color+NER.swift          # Couleurs par type d'entité
│   │   ├── Date+French.swift        # Formatage dates français
│   │   ├── String+Markdown.swift
│   │   └── View+Conditional.swift
│   │
│   └── Resources/
│       ├── mermaid.min.js           # Copie locale (no CDN en prod)
│       └── Localizable.strings      # Strings FR
│
└── Tests/
    ├── WUDDClientTests/             # Tests unitaires (XCTest)
    └── WUDDClientUITests/           # Tests UI (XCUITest)
```

---

## 3. Modèles de Données (Swift Structs)

### 3.1 Article

```swift
struct Article: Codable, Identifiable {
    // Clés JSON françaises → CodingKeys
    enum CodingKeys: String, CodingKey {
        case datePublication = "Date de publication"
        case sources         = "Sources"
        case url             = "URL"
        case resume          = "Résumé"
        case images          = "Images"
        case entities        = "entities"
        case sentiment       = "sentiment"
        case scoreSentiment  = "score_sentiment"
        case tonEditorial    = "ton_editorial"
        case scoreTon        = "score_ton"
        case tempsLectureMin = "temps_lecture_minutes"
        case tempsLectureLabel = "temps_lecture_label"
        case scoreSource     = "score_source"
        case titre           = "Titre"
    }

    var id: String { url }

    let datePublication: String
    let sources: String
    let url: String
    let resume: String
    var images: [ArticleImage]?
    var entities: [String: [String]]?
    var sentiment: String?
    var scoreSentiment: Int?
    var tonEditorial: String?
    var scoreTon: Int?
    var tempsLectureMin: Double?
    var tempsLectureLabel: String?
    var scoreSource: Int?
    var titre: String?
}

struct ArticleImage: Codable {
    let url: String
    let width: Int?
    enum CodingKeys: String, CodingKey {
        case url = "URL"
        case width = "Width"
    }
}
```

### 3.2 Alerte

```swift
struct WuddAlert: Codable, Identifiable {
    let entity: String
    let type: String
    let niveau: String          // "critique" | "élevé" | "modéré"
    let raison: String
    let articlesCount: Int
    let articles: [String]      // URLs
    let date: String

    var id: String { "\(entity)-\(date)" }

    enum CodingKeys: String, CodingKey {
        case entity, type, niveau, raison
        case articlesCount = "articles_count"
        case articles, date
    }
}
```

### 3.3 Entité NER

```swift
struct EntityStat: Codable, Identifiable {
    let type: String
    let uniqueCount: Int
    let mentionCount: Int
    let top: [EntityEntry]

    var id: String { type }
}

struct EntityEntry: Codable, Identifiable {
    let value: String
    let count: Int
    var id: String { value }
}

enum NERType: String, CaseIterable {
    case person = "PERSON"
    case org    = "ORG"
    case gpe    = "GPE"
    case loc    = "LOC"
    case product = "PRODUCT"
    case event  = "EVENT"
    case date   = "DATE"
    case money  = "MONEY"
    // ... 18 types total

    var color: Color {
        switch self {
        case .person:  return .purple
        case .org:     return .blue
        case .gpe:     return .green
        case .loc:     return .teal
        case .product: return .orange
        case .event:   return .pink
        default:       return .gray
        }
    }
}
```

### 3.4 Tâche Planificateur

```swift
struct SchedulerTask: Codable, Identifiable {
    let name: String
    let script: String
    let cron: String
    let category: String
    let nextRun: String?
    let lastRun: String?
    let logFile: String?
    let detail: String?

    var id: String { name }
}
```

### 3.5 FluxSource

```swift
struct FluxSource: Codable, Identifiable {
    let title: String
    let url: String
    var cron: String?
    var timeout: Int?

    var id: String { title }
}
```

---

## 4. Couche Réseau

### 4.1 APIClient

```swift
@Observable
final class APIClient {
    static let shared = APIClient()

    var baseURL: URL {
        get { URL(string: ServerConfig.shared.serverURL)! }
    }

    private let session: URLSession

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 300
        config.urlCache = URLCache(
            memoryCapacity: 20 * 1024 * 1024,   // 20 MB
            diskCapacity: 100 * 1024 * 1024      // 100 MB
        )
        self.session = URLSession(configuration: config)
    }

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        let url = buildURL(path, query: query)
        let (data, response) = try await session.data(from: url)
        try validate(response)
        return try JSONDecoder().decode(T.self, from: data)
    }

    func post<B: Encodable, T: Decodable>(_ path: String, body: B) async throws -> T {
        var request = URLRequest(url: buildURL(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await session.data(for: request)
        try validate(response)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func buildURL(_ path: String, query: [String: String] = [:]) -> URL {
        var components = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: true)!
        if !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        return components.url!
    }

    private func validate(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw APIError.httpError((response as? HTTPURLResponse)?.statusCode ?? 0)
        }
    }
}
```

### 4.2 SSEClient (Server-Sent Events)

```swift
final class SSEClient {
    private var task: URLSessionDataTask?

    /// Stream SSE depuis un endpoint GET, appelle onChunk pour chaque fragment Markdown reçu
    func stream(url: URL, onChunk: @escaping (String) -> Void, onComplete: @escaping () -> Void) {
        var request = URLRequest(url: url)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = .infinity

        let delegate = SSEDelegate(onChunk: onChunk, onComplete: onComplete)
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        task = session.dataTask(with: request)
        task?.resume()
    }

    /// Stream SSE depuis un endpoint POST (pour /api/chat/stream)
    func streamPOST<B: Encodable>(url: URL, body: B, onChunk: @escaping (String) -> Void, onComplete: @escaping () -> Void) {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = .infinity
        request.httpBody = try? JSONEncoder().encode(body)

        let delegate = SSEDelegate(onChunk: onChunk, onComplete: onComplete)
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        task = session.dataTask(with: request)
        task?.resume()
    }

    func cancel() {
        task?.cancel()
    }
}

// Parsing du format SSE "data: ...\n\n"
private class SSEDelegate: NSObject, URLSessionDataDelegate {
    private var buffer = ""
    let onChunk: (String) -> Void
    let onComplete: () -> Void

    init(onChunk: @escaping (String) -> Void, onComplete: @escaping () -> Void) {
        self.onChunk = onChunk
        self.onComplete = onComplete
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard let text = String(data: data, encoding: .utf8) else { return }
        buffer += text
        let events = buffer.components(separatedBy: "\n\n")
        buffer = events.last ?? ""
        for event in events.dropLast() {
            for line in event.components(separatedBy: "\n") {
                if line.hasPrefix("data: ") {
                    let chunk = String(line.dropFirst(6))
                    if chunk != "[DONE]" {
                        DispatchQueue.main.async { self.onChunk(chunk) }
                    }
                }
            }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        DispatchQueue.main.async { self.onComplete() }
    }
}
```

### 4.3 Services — Exemples

```swift
// ArticleService.swift
final class ArticleService {
    private let api = APIClient.shared

    func listFiles() async throws -> [FileMetadata] {
        try await api.get("/api/files")
    }

    func loadArticles(path: String) async throws -> [Article] {
        let response: FileContentResponse = try await api.get("/api/content", query: ["path": path])
        let data = response.content.data(using: .utf8) ?? Data()
        return try JSONDecoder().decode([Article].self, from: data)
    }

    func topArticles(n: Int = 20, hours: Int = 48) async throws -> [ScoredArticle] {
        try await api.get("/api/articles/top", query: [
            "n": String(n),
            "hours": String(hours)
        ])
    }
}

// EntityService.swift
final class EntityService {
    private let api = APIClient.shared

    func dashboard() async throws -> EntityDashboard {
        try await api.get("/api/entities/dashboard")
    }

    func articles(type: String, value: String) async throws -> [Article] {
        try await api.get("/api/entities/articles", query: ["type": type, "value": value])
    }

    func cooccurrences(type: String, value: String) async throws -> [CooccurrenceEntry] {
        try await api.get("/api/entities/cooccurrences", query: ["type": type, "value": value])
    }
}
```

---

## 5. Gestion de Configuration Serveur

```swift
// ServerConfig.swift — UserDefaults wrapper
@Observable
final class ServerConfig {
    static let shared = ServerConfig()

    private let key = "serverURL"
    private let defaults = UserDefaults.standard

    var serverURL: String {
        get { defaults.string(forKey: key) ?? "" }
        set { defaults.set(newValue, forKey: key) }
    }

    var isConfigured: Bool {
        !serverURL.isEmpty && URL(string: serverURL) != nil
    }

    // Test de connexion
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

---

## 6. Rendu Mermaid (WKWebView)

```swift
// MermaidView.swift
struct MermaidView: UIViewRepresentable {  // NSViewRepresentable sur macOS
    let mermaidCode: String

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.isOpaque = false
        webView.backgroundColor = .clear
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let escaped = mermaidCode
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "`", with: "\\`")

        let html = """
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body { margin: 0; background: transparent; }
            .mermaid { font-family: -apple-system; }
          </style>
          <script src="mermaid.min.js"></script>
        </head>
        <body>
          <div class="mermaid">\(escaped)</div>
          <script>
            mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
          </script>
        </body>
        </html>
        """
        webView.loadHTMLString(html, baseURL: Bundle.main.resourceURL)
    }
}
```

Note : `mermaid.min.js` doit être inclus dans le bundle de l'application (ajouter au target dans Xcode).

---

## 7. Rendu Markdown

Utiliser le package [swift-markdown-ui](https://github.com/gonzalezreal/swift-markdown-ui) (SPM) :

```swift
// MarkdownRenderer.swift
import MarkdownUI

struct MarkdownRenderer: View {
    let content: String
    var isStreaming: Bool = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                // Décomposer le contenu pour détecter les blocs Mermaid
                ForEach(parsedBlocks, id: \.id) { block in
                    switch block.type {
                    case .mermaid(let code):
                        MermaidView(mermaidCode: code)
                            .frame(height: 300)
                    case .markdown(let text):
                        Markdown(text)
                            .markdownTheme(.gitHub)
                    }
                }

                if isStreaming {
                    ProgressView()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 4)
                }
            }
            .padding()
        }
    }

    private var parsedBlocks: [MarkdownBlock] { /* parse mermaid fences */ }
}
```

---

## 8. Gestion de l'État Global

```swift
// AppState.swift
@Observable
final class AppState {
    // Configuration
    let serverConfig = ServerConfig.shared

    // Statut réseau
    var isOnline: Bool = true

    // Navigation
    var selectedFlux: FluxSource?
    var selectedFile: FileMetadata?
    var selectedEntity: EntityEntry?

    // Données partagées (cross-feature)
    var alerts: [WuddAlert] = []
    var alertsCount: Int { alerts.filter { $0.niveau == "critique" || $0.niveau == "élevé" }.count }

    init() {
        // Démarrer le moniteur réseau
        NetworkMonitor.shared.start { [weak self] online in
            self?.isOnline = online
        }
    }
}
```

---

## 9. Navigation Principale

### iOS (TabView)

```swift
struct ContentView: View {
    @State private var appState = AppState()
    @State private var selectedTab = 0

    var body: some View {
        if !appState.serverConfig.isConfigured {
            ServerSetupView()
        } else {
            TabView(selection: $selectedTab) {
                ArticlesTabView()
                    .tabItem { Label("Articles", systemImage: "newspaper") }
                    .tag(0)

                SearchView()
                    .tabItem { Label("Recherche", systemImage: "magnifyingglass") }
                    .tag(1)

                EntityDashboardView()
                    .tabItem { Label("Entités", systemImage: "tag") }
                    .tag(2)

                AlertsView()
                    .badge(appState.alertsCount)
                    .tabItem { Label("Alertes", systemImage: "bell") }
                    .tag(3)

                SettingsView()
                    .tabItem { Label("Paramètres", systemImage: "gearshape") }
                    .tag(4)
            }
            .environment(appState)
        }
    }
}
```

### iPad / macOS (NavigationSplitView)

```swift
struct SplitContentView: View {
    @State private var appState = AppState()
    @State private var columnVisibility = NavigationSplitViewVisibility.all
    @State private var sidebarSelection: SidebarItem? = .articles

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView(selection: $sidebarSelection)
        } content: {
            ContentListView(selection: sidebarSelection)
        } detail: {
            DetailView(selection: sidebarSelection)
        }
        .environment(appState)
        .navigationSplitViewStyle(.balanced)
    }
}
```

---

## 10. Cibles Xcode

| Target | Identifiant | Plateformes |
|---|---|---|
| WUDDClient | com.wudd.client | iOS 17+, macOS 14+ (Universal) |
| WUDDClientTests | com.wudd.client.tests | iOS, macOS |
| WUDDClientUITests | com.wudd.client.uitests | iOS, macOS |

**Approche recommandée :** Application SwiftUI universelle avec `#if os(iOS)` / `#if os(macOS)` pour les adaptations plateforme (pas Mac Catalyst).

---

## 11. Dépendances (Swift Package Manager)

Ajouter dans Xcode via File → Add Package Dependencies :

| Package | URL | Version | Usage |
|---|---|---|---|
| swift-markdown-ui | https://github.com/gonzalezreal/swift-markdown-ui | ≥ 2.3.0 | Rendu Markdown |
| Kingfisher (optionnel) | https://github.com/onevcat/Kingfisher | ≥ 7.0.0 | Cache images avancé |

Note : Swift Charts, MapKit, WKWebView, AVFoundation, URLSession sont tous des frameworks Apple inclus dans le SDK — aucune dépendance externe nécessaire pour ces fonctionnalités.

---

## 12. Permissions & Entitlements

| Permission | Raison | Fichier |
|---|---|---|
| `NSAppTransportSecurity` → `NSAllowsArbitraryLoads: true` | Connexion HTTP locale (IP privée) | Info.plist |
| `com.apple.security.network.client` | Connexions réseau sortantes | .entitlements (macOS) |
| `NSSpeechRecognitionUsageDescription` | TTS (si reconnaissance vocale ajoutée plus tard) | Info.plist |
| `NSMicrophoneUsageDescription` | Si fonctionnalité dictée ajoutée | Info.plist |

**Info.plist — Transport Security :**

```xml
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsArbitraryLoads</key>
    <true/>
</dict>
```

Ceci est nécessaire pour se connecter à `http://192.168.x.x:5050` (HTTP non-TLS sur réseau local).

---

## 13. Performances & Optimisations

| Problème | Solution |
|---|---|
| Listes d'articles longues | `LazyVStack` + identifiants stables |
| Images distantes | URLCache système (100 MB disque) + placeholder |
| Dashboard entités lourd | Cache mémoire TTL 5 min dans le ViewModel |
| Streaming SSE | `@MainActor` pour les updates UI, chunking du Markdown |
| JSON larges fichiers | Décodage sur un thread background (`Task.detached`) |
| Recherche en temps réel | Debounce 300ms avant envoi requête |

---

## 14. Tests

### Unitaires (XCTest)

- `APIClientTests` : mock URLSession, vérification encodage/décodage
- `ArticleDecoderTests` : clés françaises CodingKeys
- `SSEClientTests` : parsing chunks "data: ..."
- `ServerConfigTests` : UserDefaults read/write

### UI (XCUITest)

- `OnboardingTest` : saisie URL + test connexion
- `ArticleListTest` : chargement liste + tap article
- `SearchTest` : saisie + résultats

### Mocks

Créer un `MockAPIClient` (protocol `APIClientProtocol`) pour les tests sans backend réel. Fournir des fixtures JSON dans `Tests/Fixtures/`.
