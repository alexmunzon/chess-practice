import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';

// Simulator-only mock-glasses copy (docs/MOCK_GLASSES_RUN.md). Static checks always run: Meta's code is opt-in
// and Simulator-only, the Swift and Python pins agree, the Info.plist keys stay limited, and the source never
// uses the phone-camera feed, microphone, audio session or speech. The external frameworks and video (outside
// the repo) are hash-checked only when present; otherwise those checks skip.
const app = new URL('../native/ChessCompanionApp/', import.meta.url);
const read = name => readFile(new URL(name, app), 'utf8');
const sha = data => createHash('sha256').update(data).digest('hex');
const EXT = '/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15';

test('mock-glasses flag is Simulator-only and refuses device builds', async () => {
  const py = await read('prepare_app.py');
  assert.match(py, /if args\.mock_glasses and not args\.simulator:\s*\n\s*parser\.error\(/);
  const run = spawnSync('python3', ['-B', new URL('prepare_app.py', app).pathname, '--out', '/nonexistent/x',
    '--runtime-assets', '/nonexistent', '--fixture', '/nonexistent', '--mock-glasses', '/nonexistent',
    '--mock-glasses-video', '/nonexistent'], {encoding: 'utf8'});
  assert.notEqual(run.status, 0);
  assert.match(run.stderr, /requires --simulator/);
  // Meta sources and frameworks enter the build only through the mock-glasses branch.
  const sources = py.slice(py.indexOf('SOURCES = ['), py.indexOf(']', py.indexOf('SOURCES = [')));
  assert.doesNotMatch(sources, /IOSAdapters|MockGlasses|CaptureCoordinator/);
});

test('Info.plist keys: SDK-validated set only, both opt-outs, no camera/microphone usage', async () => {
  const py = await read('prepare_app.py');
  const info = py.slice(py.indexOf('MOCK_GLASSES_INFO = {'), py.indexOf('\n}\n', py.indexOf('MOCK_GLASSES_INFO = {')));
  for (const key of ['NSBluetoothAlwaysUsageDescription', 'NSLocalNetworkUsageDescription', 'NSBonjourServices',
    'UIBackgroundModes', 'UISupportedExternalAccessoryProtocols', 'CFBundleURLTypes', '"MetaAppID": "0"',
    '"Analytics": {"OptOut": True}', '"CrashReporting": {"OptOut": True}']) assert.ok(info.includes(key), key);
  assert.doesNotMatch(info, /NSCamera|NSMicrophone|ClientToken|TeamID/);
  assert.doesNotMatch(py, /"NSCameraUsageDescription"\s*:|"NSMicrophoneUsageDescription"\s*:/);
});

test('Swift and Python video pins agree; source avoids camera, microphone and speech APIs', async () => {
  const py = await read('prepare_app.py');
  const swift = await read('MockGlassesSource.swift');
  const pin = py.match(/MOCK_GLASSES_VIDEO_SHA256 = "([0-9a-f]{64})"/)[1];
  assert.ok(swift.includes(`static let videoSHA256 = "${pin}"`));
  const code = swift.split('\n').filter(line => !line.trim().startsWith('//')).join('\n');
  assert.doesNotMatch(code, /cameraFacing|AVCaptureSession|AVAudioSession|AVSpeech|SFSpeech|requestPermission|startRegistration|NativeSpeechOutput\(/);
  assert.match(swift, /#if COMPANION_MOCK_GLASSES && !targetEnvironment\(simulator\)\n#error/);
  // Entry hook: a same-line condition change in the shared entry file (line count unchanged), and the
  // mock file supplies SelfTestHook only for the mock build (SelfTest.swift is never compiled with it).
  const entry = await read('ChessCompanionApp.swift');
  assert.match(entry, /#if COMPANION_SELFTEST \|\| COMPANION_MOCK_GLASSES\n\s*\.modifier\(SelfTestHook\(/);
  assert.equal(entry.match(/MOCK_GLASSES/g).length, 1);
  assert.match(swift, /struct SelfTestHook: ViewModifier[\s\S]*MockGlassesRunner\.launchIfRequested/);
  assert.match(py, /if args\.mock_glasses and args\.self_test:\s*\n\s*parser\.error\(/);
});

test('external frameworks and video match the pins (skips without the outside folder)', async t => {
  if (!existsSync(`${EXT}/phase1/frameworks`)) { t.skip('external mock-glasses folder not present'); return; }
  const py = await read('prepare_app.py');
  for (const name of ['MWDATCore', 'MWDATCamera', 'MWDATMockDevice']) {
    const pin = py.match(new RegExp(`"${name}": "([0-9a-f]{64})"`))[1];
    assert.equal(sha(await readFile(`${EXT}/phase1/frameworks/${name}.framework/${name}`)), pin, name);
  }
  assert.equal(sha(await readFile(`${EXT}/phase2/replay-14.mp4`)), py.match(/MOCK_GLASSES_VIDEO_SHA256 = "([0-9a-f]{64})"/)[1]);
});
