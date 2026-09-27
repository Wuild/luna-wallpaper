import {cp, mkdir, rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root = new URL('../', import.meta.url);
const dist = new URL('dist/', root);
await rm(dist, {recursive: true, force: true});
await mkdir(dist, {recursive: true});
await cp(new URL('src/', root), dist, {recursive: true, filter: p => !p.includes('__pycache__')});
for (const name of ['metadata.json', 'schemas', 'LICENSE', 'LICENSE-NOTICE'])
    await cp(new URL(name, root), new URL(name, dist), {recursive: true});
execFileSync('glib-compile-schemas', ['--strict', fileURLToPath(new URL('schemas/', dist))], {stdio: 'inherit'});
console.log('Built Luna - Wallpaper in dist/');
