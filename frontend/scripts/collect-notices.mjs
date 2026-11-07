/** Preserve license/notice texts from the packages actually installed by npm ci.
 * The inventory intentionally includes development tooling; it is not a claim
 * that every installed package is present in the compiled JavaScript bundle.
 */
import { createHash } from 'node:crypto';
import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const frontendDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const noticeName = /^(?:licen[cs]e|copying|notice|copyright)(?:[._-].*)?$|[.-](?:licen[cs]e|notice)(?:[._-].*)?$/i;
const sourceOrImage = /\.(?:[cm]?[jt]sx?|map|svg|png|ico|jpe?g|gif|webp)$/i;

async function jsonFile(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}

async function directories(directory) {
  try {
    return (await readdir(directory, { withFileTypes: true })).filter(item => item.isDirectory()).sort((a, b) => a.name.localeCompare(b.name, 'en'));
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

async function packageDirectories(nodeModules) {
  const result = [];
  for (const entry of await directories(nodeModules)) {
    if (entry.name.startsWith('.')) continue;
    const directory = path.join(nodeModules, entry.name);
    if (entry.name.startsWith('@')) {
      for (const scoped of await directories(directory)) result.push(path.join(directory, scoped.name));
    } else result.push(directory);
  }
  return result;
}

async function noticeFiles(directory, relative = '', inLicenseDirectory = false) {
  const files = [];
  const entries = (await readdir(path.join(directory, relative), { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name, 'en'));
  for (const entry of entries) {
    if (entry.name === 'node_modules' || entry.name === '.git' || entry.isSymbolicLink()) continue;
    const child = path.join(relative, entry.name);
    if (entry.isDirectory()) {
      files.push(...await noticeFiles(directory, child, inLicenseDirectory || /^(?:licen[cs]es?|notices?)$/i.test(entry.name)));
    } else if (entry.isFile() && !sourceOrImage.test(entry.name)
               && (inLicenseDirectory || noticeName.test(entry.name))) files.push(child);
  }
  return files;
}

export async function collectFrontendNotices(directory = frontendDirectory) {
  const manifest = await jsonFile(path.join(directory, 'package.json'));
  const lock = await jsonFile(path.join(directory, 'package-lock.json'));
  await stat(path.join(directory, 'node_modules'));
  await stat(path.join(directory, 'dist', 'index.html'));
  const destination = path.join(directory, 'dist', 'third-party');
  await rm(destination, { recursive: true, force: true });
  await mkdir(destination, { recursive: true });
  const packages = [];
  const queue = await packageDirectories(path.join(directory, 'node_modules'));
  const directRuntime = new Set(Object.keys(manifest.dependencies || {}));
  const directDevelopment = new Set(Object.keys(manifest.devDependencies || {}));
  for (let index = 0; index < queue.length; index += 1) {
    const packageDirectory = queue[index];
    let installed;
    try { installed = await jsonFile(path.join(packageDirectory, 'package.json')); }
    catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    const relativeDirectory = path.relative(directory, packageDirectory).split(path.sep).join('/');
    const locked = lock.packages?.[relativeDirectory];
    if (!installed.name || !installed.version || !locked || locked.version !== installed.version) {
      throw new Error(`Pacote instalado diverge do lockfile: ${relativeDirectory}. Execute npm ci.`);
    }
    const slug = `${installed.name}-${installed.version}`.replace(/[^a-zA-Z0-9._+-]/g, '_');
    const record = {
      name: installed.name,
      version: installed.version,
      installed_path: relativeDirectory,
      declared_runtime_dependency: directRuntime.has(installed.name),
      declared_development_dependency: directDevelopment.has(installed.name),
      development_only_in_lock: locked.dev === true,
      optional_in_lock: locked.optional === true,
      license_metadata: installed.license ?? installed.licenses ?? null,
      homepage: installed.homepage ?? null,
      repository: installed.repository ?? null,
      integrity: locked.integrity ?? null,
      files: [],
    };
    for (const relative of await noticeFiles(packageDirectory)) {
      const relativeDestination = path.join('files', slug, relative);
      const target = path.join(destination, relativeDestination);
      await mkdir(path.dirname(target), { recursive: true });
      await cp(path.join(packageDirectory, relative), target);
      const bytes = await readFile(target);
      record.files.push({
        original: relative.split(path.sep).join('/'),
        path: relativeDestination.split(path.sep).join('/'),
        bytes: bytes.length,
        sha256: createHash('sha256').update(bytes).digest('hex'),
      });
    }
    packages.push(record);
    queue.push(...await packageDirectories(path.join(packageDirectory, 'node_modules')));
  }
  packages.sort((a, b) => `${a.name}@${a.version}:${a.installed_path}`.localeCompare(`${b.name}@${b.version}:${b.installed_path}`, 'en'));
  for (const name of directRuntime) {
    const item = packages.find(entry => entry.name === name && entry.installed_path === `node_modules/${name}`);
    if (!item || !item.files.length) throw new Error(`A dependência direta ${name} não forneceu texto de licença/aviso para o pacote.`);
  }
  const inventory = {
    schema_version: 1,
    application: manifest.name,
    application_version: manifest.version,
    source: 'node_modules instalado por npm ci; versões conferidas com package-lock.json',
    scope: 'Inventário de todos os pacotes instalados nesta construção, incluindo ferramentas de desenvolvimento e dependências opcionais. Presença neste inventário não comprova inclusão no JavaScript final.',
    application_license: 'Não atribuída por este coletor. Os avisos preservam as licenças dos componentes de terceiros.',
    package_count: packages.length,
    notice_file_count: packages.reduce((sum, item) => sum + item.files.length, 0),
    packages_without_notice_files: packages.filter(item => !item.files.length).map(item => `${item.name}@${item.version}`),
    packages,
  };
  await writeFile(path.join(destination, 'inventory.json'), JSON.stringify(inventory, null, 2) + '\n', 'utf8');
  const text = [
    'ESCRITURA INTEGRADA — AVISOS DO FRONTEND', '',
    'Este arquivo não define nem altera a licença do código da aplicação.',
    'Os componentes preservam suas próprias licenças, autores e avisos.',
    'A pasta files contém cópias dos textos de licença/avisos disponíveis nos pacotes instalados.',
    'inventory.json registra versão, origem declarada, integridade do lockfile e hashes dos textos.', '',
    inventory.scope, '',
    ...packages.map(item => `${item.name} ${item.version} — ${item.development_only_in_lock ? 'somente desenvolvimento no lockfile' : 'pacote da árvore instalada'} — ${item.files.length} texto(s) disponível(is)`),
    '',
    'Vue: https://github.com/vuejs/core/blob/main/LICENSE',
    'Lucide: https://github.com/lucide-icons/lucide/blob/main/LICENSE',
    'Os textos incluídos pertencem às versões instaladas; os links apontam aos repositórios oficiais.',
  ].join('\n') + '\n';
  await writeFile(path.join(destination, 'NOTICE.txt'), text, 'utf8');
  return { package_count: inventory.package_count, notice_file_count: inventory.notice_file_count, destination };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const result = await collectFrontendNotices();
  console.log(`Avisos do frontend: ${result.package_count} pacotes; ${result.notice_file_count} textos de licença/aviso.`);
}
