"""Build an offline Mac trace from the reviewed composed harness and pinned app resources."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
APP = "native/ChessCompanionApp"
HOST = "native/ChessCompanionRuntime/NativeEngineRuntime.swift"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one trace insertion point: {old}")
    return source.replace(old, new, 1)


def runtime_js(source):
    source = replace_once(source, "const workers = new Set();", """const workers = new Set();
// Active only during the synchronous entry to DeviceBackend.handle.
let dispatchTrace;
let traceCount = 0;
function trace(id, event, category) {
  if (!id || traceCount >= 144) return;
  traceCount++;
  try {
    globalThis.webkit.messageHandlers.chessWorkerTrace.postMessage(
      JSON.stringify({id,event,ms:performance.now(),category}));
  } catch {}
}""")
    source = replace_once(source, "  globalThis.webkit.messageHandlers.chessRuntime.postMessage(text);", """  if (value.kind === 'reply') trace(value.transportId, 'jsReplyPostAttempt');
  globalThis.webkit.messageHandlers.chessRuntime.postMessage(text);
  if (value.kind === 'reply') trace(value.transportId, 'jsReplyPostReturned');""")
    source = replace_once(source, "  try {\n    if (closed || !backend)", """  trace(transportId, 'jsSubmit');
  try {
    if (closed || !backend)""")
    source = replace_once(source, "    const result = await backend.handle(commandJSON);", """    let work;
    const previousTrace = dispatchTrace;
    dispatchTrace = transportId;
    try { work = backend.handle(commandJSON); }
    finally { dispatchTrace = previousTrace; }
    const result = await work;""")
    return replace_once(source, "  backend=new DeviceBackend({analyzer:createWorkerAnalyzer({createWorker})});", """  const analyze = createWorkerAnalyzer({createWorker});
  backend = new DeviceBackend({analyzer: (input, options) => {
    const id = dispatchTrace;
    return analyze(input, options, (event, category) => trace(id, event, category));
  }});""")


def worker_js(source):
    source = replace_once(source, "{signal, startupTimeoutMs = 10000, graceMs = 1500} = {}) {",
                          "{signal, startupTimeoutMs = 10000, graceMs = 1500} = {}, observe) {\n"
                          "    const trace = (name, category) => { try { observe?.(name, category); } catch {} };\n"
                          "    trace('analyzerEntered');")
    source = replace_once(source, "const claimedWorkers = new WeakSet();", r"""const claimedWorkers = new WeakSet();

function workerMessageCategory(data) {
  if (typeof data !== 'string') return 'nonText';
  const prefix = data.slice(0, 256).trimStart();
  if (!prefix) return 'empty';
  if (/^uciok(?:\s|$)/.test(prefix)) return 'uciok';
  if (/^readyok(?:\s|$)/.test(prefix)) return 'readyok';
  if (/^bestmove(?:\s|$)/.test(prefix)) return 'bestmove';
  if (/^info\s+depth(?:\s|$)/.test(prefix)) return 'infoDepth';
  if (/^info\s+string(?:\s|$)/.test(prefix)) return 'infoString';
  if (/^info(?:\s|$)/.test(prefix)) return 'otherInfo';
  if (/^id(?:\s|$)/.test(prefix)) return 'id';
  if (/^option(?:\s|$)/.test(prefix)) return 'option';
  return 'otherText';
}""")
    source = replace_once(source, "      let totalBytes = 0, info = {...empty};",
                          "      let totalBytes = 0, info = {...empty};\n"
                          "      let goAttempted = false, sawWorkerMessageAfterGo = false, messageSamples = 0;\n"
                          "      const pageProbeTimers = [];")
    source = replace_once(source, "        signal?.removeEventListener('abort', abort);\n        shutdown();",
                          "        signal?.removeEventListener('abort', abort);\n"
                          "        for (const probe of pageProbeTimers) clearTimeout(probe);\n"
                          "        trace('engineFinishEntered');\n        shutdown();")
    source = replace_once(source, "      const abort = () => finish(new WorkerEngineError('Analysis cancelled.', 'ABORTED'));",
                          """      const abort = () => {
        if (!done) trace('workerAbortSignal');
        finish(new WorkerEngineError('Analysis cancelled.', 'ABORTED'));
      };""")
    source = replace_once(source, "        error ? reject(error) : resolve(result);",
                          "        trace(error ? 'engineFailed' : 'engineCompleted');\n"
                          "        error ? reject(error) : resolve(result);")
    source = replace_once(source, """        try { worker.postMessage(command); }
        catch { finish(new WorkerEngineError('Could not send an engine command.', 'ENGINE_ERROR')); }""",
                          """        const isGo = command.startsWith('go ');
        if (command === 'uci') trace('uciPostAttempt');
        else if (command === 'isready') trace('isReadyPostAttempt');
        else if (isGo) {
          goAttempted = true;
          trace('goPostAttempt');
        }
        try {
          worker.postMessage(command);
          if (isGo) trace('goPostReturned');
        } catch {
          if (isGo) trace('goPostThrew');
          finish(new WorkerEngineError('Could not send an engine command.', 'ENGINE_ERROR'));
        }""")
    source = replace_once(source, "          timer = setTimeout(timeout, movetimeMs + graceMs);",
                          """          timer = setTimeout(() => {
            trace('searchTimerFired');
            timeout();
          }, movetimeMs + graceMs);
          trace('searchTimerScheduled');
          pageProbeTimers.push(setTimeout(() => trace('pageTimer100msFired'), 100));
          pageProbeTimers.push(setTimeout(() => trace('pageTimer1000msFired'), 1000));
          trace('pageTimerProbesScheduled');""")
    source = replace_once(source, """      const onMessage = event => {
        if (done) return;
        try {""", """      const onMessage = event => {
        if (done) return;
        if (goAttempted && !sawWorkerMessageAfterGo) {
          sawWorkerMessageAfterGo = true;
          trace('firstWorkerMessageAfterGo');
        }
        try {""")
    source = replace_once(source, "          const text = event.data;", """          const text = event.data;
          if (goAttempted && messageSamples < 8) {
            messageSamples++;
            trace('workerMessageClassified', workerMessageCategory(text));
          } else if (goAttempted && messageSamples === 8) {
            messageSamples++;
            trace('workerMessageSampleLimitReached');
          }""")
    source = replace_once(source, """      const onError = () => finish(new WorkerEngineError('Local engine worker failed.', 'ENGINE_ERROR'));
      const onMessageError = () => finish(new WorkerEngineError('Engine message could not be decoded.', 'ENGINE_OUTPUT'));""",
                          """      const onError = () => {
        if (goAttempted && !done) trace('workerErrorAfterGo');
        finish(new WorkerEngineError('Local engine worker failed.', 'ENGINE_ERROR'));
      };
      const onMessageError = () => {
        if (goAttempted && !done) trace('workerMessageErrorAfterGo');
        finish(new WorkerEngineError('Engine message could not be decoded.', 'ENGINE_OUTPUT'));
      };""")
    for marker in ("uciok", "readyok"):
        phase = {"uciok": "uci", "readyok": "ready"}[marker]
        line = f"if (text === '{marker}' && phase === '{phase}') {{"
        source = replace_once(source, line, f"{line}\n          trace('{marker}');")
    source = replace_once(source, "          if (phase !== 'searching') {",
                          "          trace('bestmove');\n          if (phase !== 'searching') {")
    return replace_once(source, "        const candidate = createWorker();",
                        "        trace('workerCreating');\n"
                        "        const candidate = createWorker();\n"
                        "        trace('workerCreated');")


def native_host(source):
    source = replace_once(source, '        configuration.userContentController.add(relay, name: "chessRuntime")',
                          '        configuration.userContentController.add(relay, name: "chessRuntime")\n'
                          '        configuration.userContentController.add(ComposedWorkerTrace.shared, name: "chessWorkerTrace")')
    source = replace_once(source, '                    guard self?.pending?.transportId == transportId else { return }',
                          '                    guard self?.pending?.transportId == transportId else { return }\n'
                          '                    ComposedWorkerTrace.shared.record("nativeTimerExpired", transportId)')
    source = replace_once(source, '                view.callAsyncJavaScript(',
                          '                ComposedWorkerTrace.shared.dispatch(transportId, kind: kind)\n'
                          '                view.callAsyncJavaScript(')
    source = replace_once(source, '        if isReady { webView?.evaluateJavaScript("globalThis.chessDeviceRuntime?.cancel();", completionHandler: nil) }',
                          '''        if isReady {
            if let previous, webView != nil {
                ComposedWorkerTrace.shared.record("nativeCancelDispatched", previous.transportId)
            }
            webView?.evaluateJavaScript("globalThis.chessDeviceRuntime?.cancel();", completionHandler: nil)
        }''')
    line = '                    guard case .failure(let error) = result, self?.pending?.transportId == transportId else { return }'
    source = replace_once(source, line,
                          '''                    if case .success = result {
                        ComposedWorkerTrace.shared.record("nativeDispatchCallbackSuccess", transportId)
                    } else {
                        ComposedWorkerTrace.shared.record("nativeDispatchCallbackFailure", transportId)
                    }
''' + line)
    line = "        guard let current = pending, current.transportId == transportId else { return }"
    if source.count(line) != 1:
        raise ValueError("Unexpected native reply handler")
    source = source.replace(line,
                            '        ComposedWorkerTrace.shared.recordReply(transportId, envelope: envelope, matchedPending: pending?.transportId == transportId)\n'
                            + line)
    line = "        guard clock.now < current.deadline else { cancel(error: NativeEngineRuntimeError.timedOut); return }"
    if source.count(line) != 2:
        raise ValueError("Unexpected native deadline guards")
    source = source.replace(line, """        guard clock.now < current.deadline else {
            ComposedWorkerTrace.shared.record("nativeReplyPastDeadline", transportId)
            cancel(error: NativeEngineRuntimeError.timedOut); return
        }""")
    return replace_once(source, '        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "chessRuntime")',
                        '        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "chessWorkerTrace")\n'
                        '        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "chessRuntime")')


def read_json(path):
    return json.loads(path.read_bytes())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def verify_assets(root, assets):
    for name, asset in assets.items():
        file = root / name
        if not file.is_file() or file.is_symlink() or file.stat().st_size != asset["byteLength"] or sha(file) != asset["sha256"]:
            raise ValueError(f"Unpinned asset: {file}")


def update_asset(root, manifest, name):
    file = root / name
    manifest["assets"][name].update(byteLength=file.stat().st_size, sha256=sha(file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Latest diagnostic preparation JSON")
    parser.add_argument("--work", type=Path, required=True, help="New private build directory")
    parser.add_argument("--out", type=Path, required=True, help="New evidence directory")
    args = parser.parse_args()
    baseline = read_json(args.baseline)
    exe_old, bundle, challenge = map(Path, baseline["commandArgv"])
    if sha(exe_old) != baseline["macExecutableSha256"] or sha(bundle / "ChessCompanion") != baseline["appExecutableSha256"]:
        raise ValueError("Baseline executable identity changed")
    if sha(challenge) != "c02544067d3aba32b660e1093df77b0c7eac6076984c003bd2454f8c0c192f2b":
        raise ValueError("Baseline challenge changed")
    previous_sources = baseline["sourceSha256"]
    for name, digest in previous_sources.items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Checkout has changed from the diagnostic baseline: {name}")
    for path in (args.work, args.out):
        if ROOT in path.resolve().parents or path.resolve() == ROOT:
            raise ValueError("Build directories must be outside the repository")
        path.mkdir(parents=True, exist_ok=False)

    # Assemble a data-only mirror. The iOS executable is never copied.
    mirror = args.work / "resources"
    mirror.mkdir()
    app_manifest = read_json(bundle / "app-assets.json")
    runtime_manifest = read_json(bundle / "Runtime/runtime-manifest.json")
    if sha(bundle / "app-assets.json") != baseline["appManifestSha256"] or sha(bundle / "Runtime/runtime-manifest.json") != baseline["runtimeManifestSha256"]:
        raise ValueError("Baseline manifests changed")
    verify_assets(bundle, app_manifest["assets"])
    verify_assets(bundle / "Runtime", runtime_manifest["assets"])
    for name in list(app_manifest["assets"]) + ["Runtime/" + name for name in runtime_manifest["assets"]]:
        target = mirror / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle / name, target)
    runtime = mirror / "Runtime"
    for name, transform in (("runtime.js", runtime_js), ("core/worker-engine.js", worker_js)):
        file = runtime / name
        file.write_text(transform(file.read_text()))
        update_asset(runtime, runtime_manifest, name)
        subprocess.run(["node", "--input-type=module", "--check"], input=file.read_bytes(), check=True)
    write_json(runtime / "runtime-manifest.json", runtime_manifest)
    update_asset(mirror, app_manifest, "Runtime/runtime-manifest.json")
    write_json(mirror / "app-assets.json", app_manifest)
    verify_assets(mirror, app_manifest["assets"])
    verify_assets(runtime, runtime_manifest["assets"])

    snapshot = args.work / "sources"
    files = list(previous_sources) + [APP + "/ComposedWorkerTrace.swift"]
    for name in files:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        src = (ROOT / name).read_text()
        if name == HOST:
            src = native_host(src)
        elif name == APP + "/VerifyComposedStudy.swift":
            src = replace_once(src, baseline["appManifestSha256"], sha(mirror / "app-assets.json"))
            src = replace_once(src, baseline["runtimeManifestSha256"], sha(runtime / "runtime-manifest.json"))
            src = replace_once(src, '    defer { diagnostics.freezeBeforeCleanup(); model.reset(); current?.release() }',
                               '    defer {\n'
                               '        ComposedWorkerTrace.shared.freezeBeforeCleanup()\n'
                               '        diagnostics.freezeBeforeCleanup(); model.reset(); current?.release()\n'
                               '    }')
            src = replace_once(src, '            report["diagnostics"] = diagnostics.snapshot()',
                               '            report["diagnostics"] = diagnostics.snapshot()\n'
                               '            report["workerTrace"] = ComposedWorkerTrace.shared.snapshot()')
        target.write_text(src)

    exe = args.work / "VerifyComposedWorkerTrace"
    original = baseline["compileCommand"]
    compile_cmd = original[:original.index("-module-cache-path")] + [
        "-module-cache-path", str(args.work / "module-cache"), "-emit-executable", "-o", str(exe),
        *map(str, (snapshot / name for name in files)),
    ]
    compiled = subprocess.run(compile_cmd, capture_output=True, timeout=150)
    (args.out / "compile.stdout.txt").write_bytes(compiled.stdout)
    (args.out / "compile.stderr.txt").write_bytes(compiled.stderr)
    compiled.check_returncode()
    run = [str(exe), str(mirror), str(challenge)]
    stdout, stderr = args.out / "mac-run.stdout.json", args.out / "mac-run.stderr.txt"
    shell = shlex.join(run) + " > " + shlex.quote(str(stdout)) + " 2> " + shlex.quote(str(stderr))
    prep = {
        "scope": "generated Mac evaluation snapshots and data-only resource mirror",
        "basePreparation": str(args.baseline), "basePreparationSha256": sha(args.baseline),
        "preparerSha256": sha(Path(__file__)), "compileCommand": compile_cmd,
        "sourceSnapshotSha256": {name: sha(snapshot / name) for name in files},
        "appAssets": app_manifest["assets"], "runtimeAssets": runtime_manifest["assets"],
        "appManifestSha256": sha(mirror / "app-assets.json"), "challengeSha256": sha(challenge),
        "macExecutableSha256": sha(exe), "commandArgv": run, "proposedCommand": shell,
        "executed": False,
    }
    write_json(args.out / "preparation.json", prep)
    print(json.dumps({"macExecutableSha256": prep["macExecutableSha256"], "proposedCommand": shell}))


if __name__ == "__main__":
    main()
