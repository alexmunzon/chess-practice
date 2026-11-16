import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,readdir,rm,symlink} from 'node:fs/promises';
import {join,resolve,dirname} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {buildDeviceRuntime} from '../scripts/build-device-runtime.mjs';
const ROOT=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const sha=data=>createHash('sha256').update(data).digest('hex');

test('private phone asset bundle is local, pinned, complete, hashed and executable as portable modules',async t=>{
 const dir=await mkdtemp(join(tmpdir(),'device-runtime-test-'));t.after(()=>rm(dir,{recursive:true,force:true}));
 const built=await buildDeviceRuntime(join(dir,'bundle'));
 const bytes=await readFile(join(built.outputDirectory,'runtime-manifest.json'));assert.equal(sha(bytes),built.manifestSha256);
 const manifest=JSON.parse(bytes);assert.equal(manifest.mode,'private-on-device-runtime-assets');assert.equal(manifest.entry,'index.html');assert.equal(built.assetCount,16);
 assert.deepEqual(Object.keys(manifest.assets).sort(),['THIRD_PARTY_NOTICES.md','core/device-backend.js','core/device-game-session.js','core/move-speech.js','core/observation.js','core/position.js','core/prewarmed-engine.js','core/replay-runtime.js','core/worker-engine.js','engine/stockfish.js','engine/stockfish.wasm','index.html','licenses/Stockfish-Copying.txt','licenses/chess.js-LICENSE','runtime.js','vendor/chess.js']);
 for(const name of ['core/observation.js','core/device-game-session.js','core/replay-runtime.js']){const data=await readFile(join(ROOT,manifest.assets[name].source));assert.equal(manifest.assets[name].source,'src/'+name);assert.equal(manifest.assets[name].mimeType,'text/javascript');assert.equal(sha(data),manifest.assets[name].sha256,'tracker modules are copied unmodified');}
 assert.deepEqual(manifest.versions,{stockfish:'19.0.1','chess.js':'1.4.0'});assert.ok(built.engineBytes>90_000_000);
 for(const [name,asset] of Object.entries(manifest.assets)){
  const data=await readFile(join(built.outputDirectory,name));assert.equal(data.length,asset.byteLength);assert.equal(sha(data),asset.sha256);assert.match(asset.sourceSha256,/^[a-f0-9]{64}$/);
  if(name.endsWith('.js')&&!name.startsWith('engine/')){
   const text=data.toString();for(const match of text.matchAll(/\bfrom\s+['"]([^'"]+)['"]/g)){
    assert.ok(match[1].startsWith('.'),'no bare or remote import');await readFile(resolve(dirname(join(built.outputDirectory,name)),match[1]));
   }
  }
 }
 assert.match((await readFile(join(built.outputDirectory,'licenses/Stockfish-Copying.txt'),'utf8')),/GNU GENERAL PUBLIC LICENSE/);
 assert.match((await readFile(join(built.outputDirectory,'index.html'),'utf8')),/connect-src 'self' blob:/);
 assert.match((await readFile(join(built.outputDirectory,'runtime.js'),'utf8')),/new Worker\(engineURL \+ '#' \+ encodeURIComponent\(wasmURL\)\)/);
 assert.match((await readFile(join(built.outputDirectory,'runtime.js'),'utf8')),/import \{ReplayRuntime\} from '\.\/core\/replay-runtime\.js';/);
 assert.match((await readFile(join(built.outputDirectory,'runtime.js'),'utf8')),/import \{createPrewarmedAnalyzer\} from '\.\/core\/prewarmed-engine\.js';/);
 assert.equal(manifest.assets['core/prewarmed-engine.js'].source,'src/core/prewarmed-engine.js');
 assert.equal(manifest.assets['core/prewarmed-engine.js'].sha256,sha(await readFile(join(ROOT,'src/core/prewarmed-engine.js'))),'pre-started engine is copied unmodified');
 const {DeviceBackend}=await import(pathToFileURL(join(built.outputDirectory,'core/device-backend.js')));
 const backend=new DeviceBackend({analyzer:()=>assert.fail('position validation does not need an engine')});
 const result=await backend.handle(JSON.stringify({schemaVersion:1,requestId:'asset-check',kind:'position',fen:'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'}));
 assert.equal(result.position.legalMoves.length,20);backend.close();
 await assert.rejects(buildDeviceRuntime(built.outputDirectory),/must be empty/);assert.equal(sha(await readFile(join(built.outputDirectory,'runtime-manifest.json'))),built.manifestSha256);
});

test('bundle generation rejects repository destinations and paths through repository symlinks',async t=>{
 await assert.rejects(buildDeviceRuntime(ROOT),/outside/);
 await assert.rejects(buildDeviceRuntime(join(ROOT,'..generated-assets')),/outside/);
 await assert.rejects(buildDeviceRuntime(join(ROOT,'native','must-not-write-generated-engine')),/outside/);
 const dir=await mkdtemp(join(tmpdir(),'device-runtime-path-test-'));t.after(()=>rm(dir,{recursive:true,force:true}));
 const link=join(dir,'repository-link');await symlink(ROOT,link);
 await assert.rejects(buildDeviceRuntime(join(link,'must-not-write-generated-engine')),/inside/);
 assert.deepEqual(await readdir(dir),['repository-link']);
});
