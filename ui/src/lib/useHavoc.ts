import { useCallback, useEffect, useRef, useState } from "react";

// One live connection to the shared brain. Every device that opens HAVOC (the PC window, the
// phone app, the desktop app) gets the same history on connect and the same events afterwards,
// including turns that came in through Discord DMs.

export type CoreState = "offline" | "idle" | "listening" | "thinking" | "speaking";
export type Msg =
  | { id: string; kind: "user"; text: string; channel: string; files: string[] }
  | { id: string; kind: "bot"; text: string; streaming?: boolean }
  | { id: string; kind: "tool"; name: string; done: boolean };
export type Alert = { id: string; title: string; body: string; at: number };
export type Pending = { tool?: string; preview: string } | null;

let seq = 0;
const nid = () => `${Date.now().toString(36)}-${(seq++).toString(36)}`;

/** "...\n\nAttached files (in the inbox, ...): a.jpg, b.pdf" -> clean text + file names. */
export function splitAttachments(text: string): { text: string; files: string[] } {
  const m = text.match(/\n*\s*Attached files[^:]*:\s*(.+)$/s);
  if (!m) return { text, files: [] };
  const files = m[1].split(",").map((f) => f.trim().replace(/^\d{10,}_/, "")).filter(Boolean);
  return { text: text.slice(0, m.index).trim(), files };
}

export function useHavoc() {
  const [state, setState] = useState<CoreState>("offline");
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [activity, setActivity] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [remote, setRemote] = useState(false);
  const [greeting, setGreeting] = useState("");
  const level = useRef(0); // read by the 3D core every frame; no re-render needed
  const ws = useRef<WebSocket | null>(null);
  const streamId = useRef<string | null>(null);
  const tick = useRef(0);

  const handle = useCallback((ev: Record<string, unknown>) => {
    switch (ev.type) {
      case "hello": {
        setRemote(Boolean(ev.remote));
        if (ev.state) setState(ev.state as CoreState);
        setGreeting(String(ev.greeting || ""));
        setPending((ev.pending as Pending) || null);
        const hist = (ev.history as { role: string; content: string; channel: string }[]) || [];
        setMessages(
          hist.map((h) => {
            if (h.role === "user") {
              const { text, files } = splitAttachments(h.content);
              return { id: nid(), kind: "user", text, channel: h.channel, files } as Msg;
            }
            return { id: nid(), kind: "bot", text: h.content } as Msg;
          }),
        );
        setHistoryLoaded(true);
        break;
      }
      case "state":
        setState(ev.state as CoreState);
        if (ev.state === "idle") setActivity(null);
        break;
      case "user": {
        const { text, files } = splitAttachments(String(ev.text || ""));
        streamId.current = null;
        setMessages((m) => [...m, { id: nid(), kind: "user", text, channel: String(ev.channel || "text"), files }]);
        setCaption("");
        break;
      }
      case "token": {
        const t = String(ev.text || "");
        setMessages((m) => {
          if (streamId.current) {
            return m.map((x) => (x.id === streamId.current && x.kind === "bot" ? { ...x, text: x.text + t } : x));
          }
          const id = nid();
          streamId.current = id;
          return [...m, { id, kind: "bot", text: t, streaming: true }];
        });
        break;
      }
      case "retract":
        if (streamId.current) {
          const id = streamId.current;
          streamId.current = null;
          setMessages((m) => m.filter((x) => x.id !== id));
        }
        break;
      case "tool": {
        const name = String(ev.name || "");
        streamId.current = null;
        if (ev.status === "running") {
          setActivity(name);
          setMessages((m) => [...m, { id: nid(), kind: "tool", name, done: false }]);
        } else {
          setMessages((m) => {
            const idx = [...m].reverse().findIndex((x) => x.kind === "tool" && x.name === name && !x.done);
            if (idx < 0) return m;
            const real = m.length - 1 - idx;
            return m.map((x, i) => (i === real ? { ...x, done: true } : x)) as Msg[];
          });
        }
        break;
      }
      case "confirm":
        setPending({ tool: String(ev.tool || ""), preview: String(ev.preview || "") });
        break;
      case "final": {
        const text = String(ev.text || "");
        setMessages((m) => {
          if (streamId.current) {
            const id = streamId.current;
            return m.map((x) => (x.id === id && x.kind === "bot" ? { ...x, text, streaming: false } : x));
          }
          return [...m, { id: nid(), kind: "bot", text }];
        });
        streamId.current = null;
        setPending((ev.pending as Pending) || null);
        setActivity(null);
        tick.current++;
        break;
      }
      case "transcript":
        setCaption(String(ev.text || ""));
        break;
      case "level":
        level.current = Number(ev.value) || 0;
        break;
      case "notify":
        setAlerts((a) => [{ id: nid(), title: String(ev.title), body: String(ev.body || ""), at: Date.now() }, ...a].slice(0, 20));
        break;
    }
  }, []);

  useEffect(() => {
    let delay = 800;
    let stopped = false;
    let timer: number | undefined;
    const open = () => {
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.current = sock;
      sock.onopen = () => {
        delay = 800;
        setConnected(true);
      };
      sock.onmessage = (e) => handle(JSON.parse(e.data));
      sock.onclose = (e) => {
        setConnected(false);
        setState("offline");
        if (e.code === 4401) {
          window.location.href = "/login";
          return;
        }
        if (!stopped) timer = window.setTimeout(open, delay);
        delay = Math.min(delay * 2, 10000);
      };
    };
    open();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      ws.current?.close();
    };
  }, [handle]);

  const send = useCallback((obj: Record<string, unknown>) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(obj));
  }, []);

  return {
    state, connected, messages, historyLoaded, pending, alerts, activity, caption, remote, greeting, level,
    replyCount: tick,
    say: (text: string, attachments: string[] = []) => send({ type: "chat", text, attachments }),
    mic: () => send({ type: "mic" }),
    stop: () => send({ type: "stop" }),
    reset: () => {
      setMessages([]);
      send({ type: "reset" });
    },
    setSpeak: (on: boolean) => send({ type: "speak", on }),
    setMute: (on: boolean) => send({ type: "mute", on }),
    dismissAlert: (id: string) => setAlerts((a) => a.filter((x) => x.id !== id)),
  };
}

export type Havoc = ReturnType<typeof useHavoc>;
