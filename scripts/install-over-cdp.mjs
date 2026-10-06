#!/usr/bin/env node
// Open Decky Loader's install prompt for a Wake Dispatch release on a device, over
// Steam's CEF remote debugging port. Development only: it never confirms the prompt,
// someone at the device has to tap Install (or Update / Reinstall).
//
// Usage:
//   scripts/install-over-cdp.mjs <host> [vX.Y.Z] [--dry-run] [--port 8081]
//
//   <host>      the device's address, e.g. 192.0.2.10
//   vX.Y.Z      release tag to install (default: the latest release)
//   --dry-run   resolve the release and check the device, but open no prompt
//   --port N    CEF remote debugging port (default 8081)
//
// Requires Node >= 22 (global fetch and WebSocket) and, on the device, Decky's
// "Allow Remote CEF Debugging" setting. See CONTRIBUTING.md.

const REPO = 'jedwards1230/decky-wake-dispatch';
const PLUGIN_NAME = 'Wake Dispatch';
const ASSET_NAME = 'wake-dispatch.zip';
const MAX_ASSET_SIZE = 5 * 1024 * 1024;
const TIMEOUT_MS = 10_000;
const TAG_RE = /^v(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$/;
const DIGEST_RE = /^sha256:([0-9a-f]{64})$/;
const HOST_RE = /^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])$/;
// Decky's PluginInstallType (these three are unchanged from 3.0.0 to 3.2.10).
const INSTALL = 0;
const REINSTALL = 1;
const UPDATE = 2;
const TYPE_NAMES = { [INSTALL]: ['INSTALL', 'Install'], [REINSTALL]: ['REINSTALL', 'Reinstall'], [UPDATE]: ['UPDATE', 'Update'] };

function fail(message) {
  console.error(`install-over-cdp: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const opts = { host: null, tag: null, dryRun: false, port: 8081 };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--port' || arg.startsWith('--port=')) {
      const value = arg === '--port' ? argv[++i] : arg.slice('--port='.length);
      if (!/^\d{1,5}$/.test(value ?? '') || +value < 1 || +value > 65535) fail(`bad --port ${JSON.stringify(value)}`);
      opts.port = +value;
    } else if (arg === '-h' || arg === '--help') {
      console.log('usage: scripts/install-over-cdp.mjs <host> [vX.Y.Z] [--dry-run] [--port 8081]');
      process.exit(0);
    } else if (arg.startsWith('-')) fail(`unknown option ${arg}`);
    else if (opts.host === null) opts.host = arg;
    else if (opts.tag === null) opts.tag = arg;
    else fail(`unexpected argument ${arg}`);
  }
  if (opts.host === null) fail('usage: scripts/install-over-cdp.mjs <host> [vX.Y.Z] [--dry-run] [--port 8081]');
  if (!HOST_RE.test(opts.host)) fail(`bad host ${JSON.stringify(opts.host)}`);
  if (opts.tag !== null && !TAG_RE.test(opts.tag)) fail(`bad tag ${JSON.stringify(opts.tag)} (expected vX.Y.Z)`);
  return opts;
}

// Same checks as py_modules/wake_dispatch/updates.py parse_release.
function parseRelease(doc) {
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) throw new Error('top level is not an object');
  if (doc.draft !== false || doc.prerelease !== false) throw new Error('release is a draft or prerelease');
  if (typeof doc.tag_name !== 'string' || !TAG_RE.test(doc.tag_name)) throw new Error(`unexpected tag ${JSON.stringify(doc.tag_name)}`);
  const version = doc.tag_name.slice(1);
  if (!Array.isArray(doc.assets)) throw new Error('assets is not a list');
  const matches = doc.assets.filter((a) => typeof a === 'object' && a !== null && a.name === ASSET_NAME);
  if (matches.length !== 1) throw new Error(`expected exactly one ${ASSET_NAME} asset, found ${matches.length}`);
  const asset = matches[0];
  if ('state' in asset && asset.state !== 'uploaded') throw new Error(`asset state is ${JSON.stringify(asset.state)}`);
  if (!Number.isInteger(asset.size) || !(asset.size > 0 && asset.size < MAX_ASSET_SIZE)) throw new Error(`unexpected asset size ${JSON.stringify(asset.size)}`);
  const url = `https://github.com/${REPO}/releases/download/v${version}/${ASSET_NAME}`;
  if (asset.browser_download_url !== url) throw new Error(`unexpected download URL ${JSON.stringify(asset.browser_download_url)}`);
  const digest = typeof asset.digest === 'string' ? DIGEST_RE.exec(asset.digest) : null;
  if (digest === null) throw new Error(`unexpected digest ${JSON.stringify(asset.digest)}`);
  return { version, url, sha256: digest[1], size: asset.size };
}

async function getJson(url, headers = {}) {
  const res = await fetch(url, { headers, redirect: 'error', signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (res.status !== 200) throw new Error(`HTTP ${res.status} from ${url}`);
  return res.json();
}

async function resolveRelease(tag) {
  const api = `https://api.github.com/repos/${REPO}/releases/${tag === null ? 'latest' : `tags/${tag}`}`;
  let doc;
  try {
    doc = await getJson(api, { 'User-Agent': 'wake-dispatch-dev-install', Accept: 'application/vnd.github+json' });
  } catch (err) {
    fail(`couldn't fetch the release from GitHub: ${err.message}`);
  }
  try {
    const release = parseRelease(doc);
    if (tag !== null && `v${release.version}` !== tag) throw new Error(`asked for ${tag}, got v${release.version}`);
    return release;
  } catch (err) {
    fail(`GitHub returned an unexpected release: ${err.message}`);
  }
}

// One CDP session on a target: evaluate(expression) -> value, with a timeout per call.
async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await withTimeout(new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = () => reject(new Error('websocket error'));
  }), 'connecting to the CEF target');
  let nextId = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const evaluate = async (expression) => {
    const id = ++nextId;
    const reply = new Promise((resolve) => pending.set(id, resolve));
    ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
    const msg = await withTimeout(reply, 'waiting for the device');
    if (msg.error) throw new Error(msg.error.message);
    if (msg.result.exceptionDetails) throw new Error(msg.result.exceptionDetails.exception?.description ?? msg.result.exceptionDetails.text);
    return msg.result.result.value;
  };
  return { evaluate, close: () => ws.close() };
}

function withTimeout(promise, what) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out ${what}`)), TIMEOUT_MS);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

// Read-only: is Decky there, and is Wake Dispatch installed (and at which version)?
// loader/get_plugins returns [{name, version, load_type, ...}] (3.0.0 and later).
const CHECK_JS = `(async () => {
  if (typeof globalThis.DeckyBackend?.call !== 'function') return { decky: false };
  const name = ${JSON.stringify(PLUGIN_NAME)};
  let plugins = null;
  try { plugins = await DeckyBackend.call('loader/get_plugins'); } catch (e) {}
  if (!Array.isArray(plugins)) plugins = globalThis.DeckyPluginLoader?.plugins ?? [];
  const found = plugins.find((p) => p && p.name === name);
  return { decky: true, installed: !!found, version: found?.version ?? null };
})()`;

const opts = parseArgs(process.argv.slice(2));
const release = await resolveRelease(opts.tag);

let targets;
try {
  targets = await getJson(`http://${opts.host}:${opts.port}/json`);
} catch (err) {
  fail(`couldn't reach CEF remote debugging at ${opts.host}:${opts.port} (is "Allow Remote CEF Debugging" on?): ${err.message}`);
}
const target = Array.isArray(targets) ? targets.find((t) => t.title === 'SharedJSContext') : undefined;
if (!target?.webSocketDebuggerUrl) fail('no SharedJSContext target on the device (is Steam running in Game Mode?)');

const session = await connect(target.webSocketDebuggerUrl).catch((err) => fail(err.message));
try {
  const state = await session.evaluate(CHECK_JS);
  if (!state?.decky) throw new Error('Decky Loader not found on this device');
  // Same version already there -> Decky's Reinstall wording; any other installed version -> Update.
  const installType = !state.installed ? INSTALL : state.version === release.version ? REINSTALL : UPDATE;
  console.log(`release:      v${release.version}`);
  console.log(`url:          ${release.url}`);
  console.log(`sha256:       ${release.sha256}`);
  console.log(`size:         ${release.size} bytes`);
  console.log(`installed:    ${state.installed ? `yes${state.version ? ` (v${state.version})` : ''}` : 'no'}`);
  console.log(`install_type: ${installType} (${TYPE_NAMES[installType][0]})`);
  if (!opts.dryRun) {
    const args = [release.url, PLUGIN_NAME, release.version, release.sha256, installType].map((v) => JSON.stringify(v)).join(', ');
    await session.evaluate(`DeckyBackend.call('utilities/install_plugin', ${args}).then(() => true)`);
    console.log(`A confirm dialog is waiting on the device — tap ${TYPE_NAMES[installType][1]}.`);
  }
} catch (err) {
  console.error(`install-over-cdp: ${err.message}`);
  process.exitCode = 1;
} finally {
  session.close();
}
