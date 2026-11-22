// H.A.V.O.C. WhatsApp bridge.
// Links your WhatsApp as a "linked device" (like WhatsApp Web) using Baileys, keeps a local
// store of recent messages, and exposes a tiny HTTP API on 127.0.0.1 for the Python side.
//
// This is an unofficial client. It is against WhatsApp's Terms of Service and carries a small
// risk of the number being restricted. Keep sending volume human-sized.
//
//   GET  /health                      -> { ok }
//   GET  /status                      -> { connected, me, hasQr }
//   GET  /qr                          -> { qr, dataUrl }  (scan in WhatsApp > Linked devices)
//   GET  /groups                      -> [{ id, name, participants }]
//   GET  /messages?chat=&since=&limit -> [{ id, chat, chatName, sender, text, ts, fromMe }]
//   POST /send { chat, text, file? }  -> { ok, id }   (file must be in data/inbox)
//   POST /delete { chat, id }         -> { ok }       (delete for everyone, own recent sends only)
//
// Every request needs the header  x-bridge-token: <WA_BRIDGE_TOKEN>  when that env var is set.

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isJidGroup,
  normalizeMessageContent,
  useMultiFileAuthState,
} from 'baileys';
import pino from 'pino';
import QRCode from 'qrcode';
import qrcodeTerminal from 'qrcode-terminal';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
loadDotEnv(path.join(ROOT, '.env'));

const PORT = Number(process.env.WA_BRIDGE_PORT || 3777);
const HOST = '127.0.0.1';
const TOKEN = process.env.WA_BRIDGE_TOKEN || '';
const DATA = path.join(ROOT, 'data', 'whatsapp');
const AUTH_DIR = path.join(DATA, 'auth');
const STORE_FILE = path.join(DATA, 'messages.json');
const MAX_PER_CHAT = 1500;

fs.mkdirSync(AUTH_DIR, { recursive: true });
const logger = pino({ level: process.env.WA_LOG_LEVEL || 'warn' });

const state = { sock: null, connected: false, me: null, qr: null, groups: {}, retries: 0 };
/** @type {Record<string, Array<{id:string, chat:string, sender:string, text:string, ts:number, fromMe:boolean}>>} */
let store = {};
try { store = JSON.parse(fs.readFileSync(STORE_FILE, 'utf8')); } catch { store = {}; }

let saveTimer = null;
function saveSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fs.writeFile(STORE_FILE, JSON.stringify(store), (err) => err && logger.error(err));
  }, 2000);
}

export function messageText(msg) {
  const c = normalizeMessageContent(msg?.message);
  if (!c) return '';
  return (
    c.conversation ||
    c.extendedTextMessage?.text ||
    c.imageMessage?.caption && `[image] ${c.imageMessage.caption}` ||
    c.videoMessage?.caption && `[video] ${c.videoMessage.caption}` ||
    c.documentMessage && `[document: ${c.documentMessage.fileName || 'file'}] ${c.documentMessage.caption || ''}`.trim() ||
    c.pollCreationMessage?.name && `[poll] ${c.pollCreationMessage.name}: ${(c.pollCreationMessage.options || []).map(o => o.optionName).join(' / ')}` ||
    c.pollCreationMessageV3?.name && `[poll] ${c.pollCreationMessageV3.name}` ||
    (c.imageMessage && '[image]') || (c.videoMessage && '[video]') || (c.audioMessage && '[voice note]') ||
    (c.stickerMessage && '[sticker]') || ''
  );
}

function remember(msg) {
  const chat = msg?.key?.remoteJid;
  if (!chat || chat === 'status@broadcast') return;
  const text = messageText(msg);
  if (!text) return;
  const list = (store[chat] ||= []);
  const id = msg.key.id;
  if (list.some((m) => m.id === id)) return;
  list.push({
    id,
    chat,
    sender: msg.key.fromMe ? 'me' : (msg.pushName || msg.key.participant || chat).toString(),
    text,
    ts: Number(msg.messageTimestamp || Date.now() / 1000),
    fromMe: Boolean(msg.key.fromMe),
  });
  if (list.length > MAX_PER_CHAT) list.splice(0, list.length - MAX_PER_CHAT);
  saveSoon();
}

async function refreshGroups() {
  if (!state.sock) return;
  try {
    const all = await state.sock.groupFetchAllParticipating();
    state.groups = Object.fromEntries(
      Object.values(all).map((g) => [g.id, { id: g.id, name: g.subject, participants: g.participants?.length || 0 }]),
    );
  } catch (e) {
    logger.warn({ err: String(e) }, 'groupFetchAllParticipating failed');
  }
}

async function connect() {
  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  let version;
  try { ({ version } = await fetchLatestBaileysVersion()); } catch { /* use bundled default */ }
  const sock = makeWASocket({
    auth,
    logger,
    ...(version ? { version } : {}),
    browser: Browsers.windows('Desktop'),
    markOnlineOnConnect: false, // don't flip your status to "online" all day
    syncFullHistory: false,
  });
  state.sock = sock;
  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (u) => {
    if (u.qr) {
      state.qr = u.qr;
      console.log('\nScan this in WhatsApp > Settings > Linked devices > Link a device:\n');
      qrcodeTerminal.generate(u.qr, { small: true });
    }
    if (u.connection === 'open') {
      state.connected = true;
      state.qr = null;
      state.retries = 0;
      state.me = sock.user?.id || null;
      console.log(`WhatsApp linked as ${sock.user?.name || state.me}`);
      await refreshGroups();
    }
    if (u.connection === 'close') {
      state.connected = false;
      const code = u.lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.log('WhatsApp logged this device out. Delete data/whatsapp/auth and restart to re-link.');
        return;
      }
      const delay = Math.min(30000, 1000 * 2 ** state.retries++);
      console.log(`WhatsApp connection closed (${code}); reconnecting in ${delay / 1000}s`);
      setTimeout(() => connect().catch((e) => logger.error(e)), delay);
    }
  });

  sock.ev.on('messaging-history.set', ({ messages }) => (messages || []).forEach(remember));
  sock.ev.on('messages.upsert', ({ messages }) => (messages || []).forEach(remember));
  sock.ev.on('groups.update', () => refreshGroups());
}

const INBOX = path.join(ROOT, 'data', 'inbox');
const sentKeys = [];
const MIME = {
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif',
  '.pdf': 'application/pdf', '.mp4': 'video/mp4', '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.txt': 'text/plain',
};

function validJid(chat) {
  return Boolean(isJidGroup(chat) || chat.endsWith('@s.whatsapp.net') || chat.endsWith('@lid'));
}

// Only files in data/inbox (things you sent from your phone) can go out.
export function inboxFile(file, inbox = INBOX) {
  const resolved = path.resolve(inbox, path.basename(String(file)));
  const full = path.resolve(String(file));
  const pick = full.startsWith(path.resolve(inbox) + path.sep) ? full : resolved;
  if (!pick.startsWith(path.resolve(inbox) + path.sep)) throw new Error('file must be in data/inbox');
  if (!fs.existsSync(pick)) throw new Error(`no inbox file ${path.basename(pick)}`);
  return pick;
}

export function buildContent(text, file, inbox = INBOX) {
  if (!file) return { text };
  const p = inboxFile(file, inbox);
  const ext = path.extname(p).toLowerCase();
  const mimetype = MIME[ext] || 'application/octet-stream';
  const data = fs.readFileSync(p);
  const caption = text || undefined;
  if (mimetype.startsWith('image/') && ext !== '.gif') return { image: data, caption, mimetype };
  if (mimetype.startsWith('video/')) return { video: data, caption, mimetype };
  const fileName = path.basename(p).replace(/^\d{10,}_/, '');
  return { document: data, fileName, mimetype, caption };
}

function send(res, code, body) {
  res.writeHead(code, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => { data += c; if (data.length > 1e6) reject(new Error('too large')); });
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch (e) { reject(e); } });
  });
}

export function filterMessages(st, groups, { chat, since = 0, limit = 200 }) {
  const chats = chat ? [chat] : Object.keys(st);
  const out = [];
  for (const c of chats) {
    for (const m of st[c] || []) if (m.ts >= since) out.push({ ...m, chatName: groups[c]?.name || c });
  }
  out.sort((a, b) => a.ts - b.ts);
  return out.slice(-limit);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${HOST}`);
  if (TOKEN && req.headers['x-bridge-token'] !== TOKEN && url.pathname !== '/health') {
    return send(res, 401, { error: 'bad token' });
  }
  try {
    if (url.pathname === '/health') return send(res, 200, { ok: true });
    if (url.pathname === '/status') {
      return send(res, 200, { connected: state.connected, me: state.me, hasQr: Boolean(state.qr) });
    }
    if (url.pathname === '/qr') {
      if (!state.qr) return send(res, 200, { qr: null, dataUrl: null, connected: state.connected });
      return send(res, 200, { qr: state.qr, dataUrl: await QRCode.toDataURL(state.qr, { margin: 1, width: 320 }) });
    }
    if (url.pathname === '/groups') {
      if (state.connected) await refreshGroups();
      return send(res, 200, Object.values(state.groups));
    }
    if (url.pathname === '/messages') {
      const chat = url.searchParams.get('chat') || '';
      const since = Number(url.searchParams.get('since') || 0);
      const limit = Math.min(1000, Number(url.searchParams.get('limit') || 200));
      return send(res, 200, filterMessages(store, state.groups, { chat, since, limit }));
    }
    if (url.pathname === '/send' && req.method === 'POST') {
      const { chat, text, file } = await readBody(req);
      if (!chat || (!text && !file)) return send(res, 400, { error: 'chat and text (or file) are required' });
      if (!validJid(chat)) return send(res, 400, { error: 'chat must be a WhatsApp JID' });
      let content;
      try {
        content = buildContent(String(text || '').slice(0, 4000), file);
      } catch (e) {
        return send(res, 400, { error: String(e.message || e) });
      }
      if (!state.connected) return send(res, 503, { error: 'WhatsApp not connected' });
      const sent = await state.sock.sendMessage(chat, content);
      if (sent) {
        remember(sent);
        sentKeys.push(sent.key);
        if (sentKeys.length > 30) sentKeys.shift();
      }
      return send(res, 200, { ok: true, id: sent?.key?.id });
    }
    if (url.pathname === '/delete' && req.method === 'POST') {
      // Delete-for-everyone of a message this bridge sent (used by Havoc's undo).
      const { chat, id } = await readBody(req);
      const key = sentKeys.find((k) => k.id === id && k.remoteJid === chat);
      if (!key) return send(res, 404, { error: 'not a message this bridge sent recently' });
      if (!state.connected) return send(res, 503, { error: 'WhatsApp not connected' });
      await state.sock.sendMessage(chat, { delete: key });
      sentKeys.splice(sentKeys.indexOf(key), 1);
      const list = store[chat] || [];
      const i = list.findIndex((m) => m.id === id);
      if (i >= 0) { list.splice(i, 1); saveSoon(); }
      return send(res, 200, { ok: true });
    }
    send(res, 404, { error: 'not found' });
  } catch (e) {
    send(res, 500, { error: String(e?.message || e) });
  }
});

function loadDotEnv(file) {
  try {
    for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
    }
  } catch { /* no .env */ }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  server.listen(PORT, HOST, () => console.log(`WhatsApp bridge on http://${HOST}:${PORT}`));
  connect().catch((e) => { console.error('WhatsApp connect failed:', e); });
}
