// Local image codecs for PDF.js, including CCITT QR images in fiscal PDFs.
// JS fallbacks preserve the existing CSP without enabling eval or WebAssembly.
import {mkdir,copyFile,readFile} from 'node:fs/promises';
const root=new URL('../',import.meta.url);
const pkg=JSON.parse(await readFile(new URL('node_modules/pdfjs-dist/package.json',root),'utf8'));
const destination=new URL(`public/pdfjs-codecs/${pkg.version}/`,root);
await mkdir(destination,{recursive:true});
for(const file of ['jbig2_nowasm_fallback.js','openjpeg_nowasm_fallback.js','LICENSE_JBIG2','LICENSE_PDFJS_JBIG2','LICENSE_OPENJPEG','LICENSE_PDFJS_OPENJPEG']) {
 await copyFile(new URL(`node_modules/pdfjs-dist/wasm/${file}`,root),new URL(file,destination));
}
