#!/usr/bin/env node
/** Local development assets only. No downloads, server, signing or distribution. */
import {mkdir,readFile,writeFile,readdir,realpath,stat} from 'node:fs/promises';
import {resolve,dirname,relative,isAbsolute,join,basename,sep} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const ROOT=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const sha=data=>createHash('sha256').update(data).digest('hex');
const sources=[
 ['index.html','native/ChessCompanionRuntime/index.html','text/html'],
 ['runtime.js','native/ChessCompanionRuntime/runtime.js','text/javascript'],
 ...['device-backend','worker-engine','position','move-speech','observation','device-game-session','replay-runtime'].map(name=>[`core/${name}.js`,`src/core/${name}.js`,'text/javascript']),
 ['vendor/chess.js','node_modules/chess.js/dist/esm/chess.js','text/javascript'],
 ['engine/stockfish.js','node_modules/stockfish/bin/stockfish-19-single.js','text/javascript'],
 ['engine/stockfish.wasm','node_modules/stockfish/bin/stockfish-19-single.wasm','application/wasm'],
 ['licenses/Stockfish-Copying.txt','node_modules/stockfish/Copying.txt','text/plain'],
 ['licenses/chess.js-LICENSE','node_modules/chess.js/LICENSE','text/plain'],
 ['THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md','text/plain'],
];
function inside(root,path){const rel=relative(root,path);return rel===''||(!isAbsolute(rel)&&rel!=='..'&&!rel.startsWith('..'+sep));}
export async function buildDeviceRuntime(outputDirectory) {
 if(typeof outputDirectory!=='string'||!outputDirectory)throw new Error('An explicit empty output directory is required.');
 const output=resolve(outputDirectory),repo=await realpath(ROOT);
 if(inside(repo,output))throw new Error('Development runtime assets must stay outside the source repository.');
 // Resolve the nearest existing ancestor before creating anything through symlinks.
 let ancestor=output,tail=[];
 for(;;){try{await stat(ancestor);break;}catch(e){if(e.code!=='ENOENT')throw e;tail.unshift(basename(ancestor));ancestor=dirname(ancestor);}}
 const canonical=resolve(await realpath(ancestor),...tail);
 if(inside(repo,canonical))throw new Error('Output resolves inside the source repository.');
 const lock=JSON.parse(await readFile(join(ROOT,'package-lock.json'),'utf8'));
 for(const [name,version] of [['stockfish','19.0.1'],['chess.js','1.4.0']]){
  const pkg=JSON.parse(await readFile(join(ROOT,'node_modules',name,'package.json'),'utf8'));
  if(pkg.version!==version||lock.packages?.['node_modules/'+name]?.version!==version||lock.packages?.['']?.dependencies?.[name]!==version)throw new Error('Unexpected local dependency version: '+name);
 }
 await mkdir(output,{recursive:true});if((await readdir(output)).length)throw new Error('Output directory must be empty; existing files are preserved.');
 const manifest={schemaVersion:1,mode:'private-on-device-runtime-assets',entry:'index.html',versions:{stockfish:'19.0.1','chess.js':'1.4.0'},distribution:'Local development only; GPL corresponding-source delivery must be verified before sharing a bundled engine.',assets:{}};
 for(const [target,source,mimeType] of sources){
  const original=await readFile(join(ROOT,source));let bytes=original;
  if(target==='core/position.js'){
   const text=original.toString('utf8');if((text.match(/from 'chess\.js'/g)||[]).length!==1)throw new Error('Rules import layout changed.');
   bytes=Buffer.from(text.replace("from 'chess.js'","from '../vendor/chess.js'"));
  }
  await mkdir(dirname(join(output,target)),{recursive:true});await writeFile(join(output,target),bytes,{flag:'wx'});
  manifest.assets[target]={mimeType,byteLength:bytes.length,sha256:sha(bytes),source,sourceSha256:sha(original)};
 }
 await writeFile(join(output,'runtime-manifest.json'),JSON.stringify(manifest,null,2)+'\n',{flag:'wx'});
 return {outputDirectory:await realpath(output),manifestSha256:sha(await readFile(join(output,'runtime-manifest.json'))),assetCount:Object.keys(manifest.assets).length,engineBytes:manifest.assets['engine/stockfish.wasm'].byteLength};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
 try{if(process.argv.length!==4||process.argv[2]!=='--out')throw new Error('Usage: node scripts/build-device-runtime.mjs --out EMPTY_DIRECTORY_OUTSIDE_REPO');console.log(JSON.stringify(await buildDeviceRuntime(process.argv[3])));}
 catch(error){console.error(error.message);process.exitCode=1;}
}
