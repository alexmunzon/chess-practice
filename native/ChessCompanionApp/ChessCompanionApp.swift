#if os(iOS)
import SwiftUI
import UIKit

enum AppMode: String, CaseIterable, Identifiable {
    case study, replay
    var id: Self { self }
    var title: String { self == .study ? "Study position" : "Replay game" }
}

/// Which mode is on screen. Only the visible mode's model is ever active.
@MainActor final class AppModeState: ObservableObject {
    @Published var mode: AppMode = .study
}

@main
struct ChessCompanionApp: App {
    @StateObject private var model: OfflineStudyModel
    @StateObject private var replay: ReplayGameModel
    @StateObject private var modeState = AppModeState()
    private let fixtures: [StudyFixture]
    private let replayAvailable: Bool
    @Environment(\.scenePhase) private var scenePhase
    init() {
        // Constructing the models does not start WebKit, inference, SDK or audio.
        let resources = StudyResources(root: Bundle.main.bundleURL)
        fixtures = (try? resources.availableFixtures()) ?? [.starting]
        replayAvailable = (try? resources.replayAvailable()) ?? false
#if COMPANION_SELFTEST
        if SelfTestRunner.requested {
            _model = StateObject(wrappedValue: SelfTestRunner.makeModel(resources: resources))
            _replay = StateObject(wrappedValue: SelfTestRunner.makeReplayModel(resources: resources))
            return
        }
#endif
        _model = StateObject(wrappedValue: OfflineStudyModel(
            makeBackend: { try LocalOfflineBackend(resources: resources) },
            recognizer: OfflinePixelRecognizer(resources: resources),
            loadFixture: { try resources.checked($0.asset) }, speech: OfflineNativeSpeech()))
        _replay = StateObject(wrappedValue: ReplayGameModel(
            makeBackend: { try LocalOfflineBackend(resources: resources) },
            recognizer: OfflinePixelRecognizer(resources: resources),
            loadFrame: { try resources.checked($0.asset) }))
    }
    var body: some Scene {
        WindowGroup {
            RootView(model: model, replay: replay, modeState: modeState, fixtures: fixtures, replayAvailable: replayAvailable)
#if COMPANION_SELFTEST
                .modifier(SelfTestHook(model: model, replay: replay, modeState: modeState))
#endif
                .onAppear { apply(scenePhase, mode: modeState.mode) }
                .onDisappear { model.setActive(false); replay.leave() }
                .onChange(of: scenePhase) { _, phase in apply(phase, mode: modeState.mode) }
                .onChange(of: modeState.mode) { old, new in
                    // Leaving replay clears it completely; entering a mode only re-enables it.
                    if old == .replay && new != .replay { replay.leave() }
                    apply(scenePhase, mode: new)
                }
        }
    }
    private func apply(_ phase: ScenePhase, mode: AppMode) {
        let visible = phase == .active
        model.setActive(visible && mode == .study)
        replay.setActive(visible && mode == .replay)
    }
}

private struct RootView: View {
    @ObservedObject var model: OfflineStudyModel
    @ObservedObject var replay: ReplayGameModel
    @ObservedObject var modeState: AppModeState
    let fixtures: [StudyFixture]
    let replayAvailable: Bool
    var body: some View {
        VStack(spacing: 0) {
            if replayAvailable {
                Picker("Mode", selection: Binding(get: { modeState.mode }, set: { modeState.mode = $0 })) {
                    ForEach(AppMode.allCases) { mode in Text(mode.title).tag(mode) }
                }.pickerStyle(.segmented).padding(.horizontal).padding(.top, 4).accessibilityIdentifier("app-mode")
            }
            if replayAvailable && modeState.mode == .replay {
                ReplayGameView(model: replay)
            } else {
                StudyView(model: model, fixtures: fixtures)
            }
        }
    }
}

private struct StudyView: View {
    @ObservedObject var model: OfflineStudyModel
    let fixtures: [StudyFixture]
    var body: some View {
        NavigationStack {
            Form {
                Section("Study position") {
                    Picker("Position", selection: Binding(get: { model.fixture }, set: { model.selectFixture($0) })) {
                        ForEach(fixtures) { fixture in Text(fixture.title).tag(fixture) }
                    }.accessibilityIdentifier("study-position")
                    Text(model.status).accessibilityIdentifier("study-status")
                    if model.ready {
                        Button("Read board") { model.recognizeFixture() }.disabled(model.busy)
                    } else {
                        Button("Start local engine") { model.start() }.disabled(model.busy)
                    }
                    if model.busy { ProgressView() }
                }
                if let bytes = model.imageBytes, let image = UIImage(data: bytes) {
                    Section("Image and unreviewed recognition") {
                        Image(uiImage: image).resizable().scaledToFit().accessibilityLabel("Bundled synthetic board image")
                        if let board = model.board {
                            Text(board.complete ? "All 64 squares have a proposal. Check every piece." : "Unknown squares block analysis.")
                            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 1), count: 8), spacing: 1) {
                                ForEach(0..<64, id: \.self) { index in
                                    let square = "\(Array("abcdefgh")[index % 8])\(8-index/8)"
                                    let label = board.squares[square] ?? "unknown"
                                    VStack(spacing: 2) {
                                        Text(label == "empty" ? "·" : label == "unknown" ? "?" : label).font(.system(.body, design: .monospaced))
                                        Text(square).font(.caption2)
                                    }.frame(maxWidth: .infinity).padding(.vertical, 5)
                                        .background((index/8+index%8).isMultiple(of: 2) ? Color.secondary.opacity(0.1) : Color.secondary.opacity(0.25))
                                        .accessibilityElement(children: .ignore)
                                        .accessibilityLabel("\(square), \(label)")
                                }
                            }
                        }
                    }
                }
                if model.board?.complete == true {
                    Section("Supply and review complete state") {
                        Text("Check the pieces and all six FEN fields. Earlier repetition history is unknown.")
                        if let sample = model.fixture.referenceFEN {
                            Button("Use sample FEN") { model.editFEN(sample) }
                        }
                        TextField("Complete six-field FEN", text: Binding(get: { model.fen }, set: { model.editFEN($0) }), axis: .vertical)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().font(.system(.body, design: .monospaced))
                        ForEach(ReviewField.allCases) { field in
                            Toggle(field.title, isOn: Binding(get: { model.checks.contains(field) }, set: { model.setReview(field, checked: $0) }))
                        }
                        Button("Validate reviewed position") { model.validate() }.disabled(!model.canValidate)
                        Button("Analyze offline position") { model.analyze() }.disabled(!model.canAnalyze)
                    }
                }
                if let text = model.recommendation {
                    Section("Offline recommendation") {
                        Text(text).font(.headline).accessibilityIdentifier("study-recommendation")
#if !targetEnvironment(simulator)
                        Button("Speak offline move") { model.speak() }.disabled(!model.canSpeak)
                        Button("Stop speech") { model.stopSpeech() }
#endif
                    }
                }
                Section { Button("Reset study", role: .destructive) { model.reset() } }
            }.navigationTitle("Chess Companion")
        }
    }
}
#endif
