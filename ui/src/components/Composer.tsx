import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, CircleNotch, Microphone, Paperclip, Stop, X } from "@phosphor-icons/react";
import { useRef, useState } from "react";
import { api } from "../lib/api";
import type { Havoc } from "../lib/useHavoc";

type Upload = { label: string; name: string | null; error?: string };

/**
 * Type, attach, talk. On the PC the mic button wakes HAVOC's own microphone loop; on the
 * phone it records on the phone and sends the clip to the PC for transcription.
 */
export function Composer({ h }: { h: Havoc }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Upload[]>([]);
  const [recording, setRecording] = useState(false);
  const [sendingVoice, setSendingVoice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const rec = useRef<MediaRecorder | null>(null);

  const ready = files.filter((f) => f.name).map((f) => f.name as string);
  const uploading = files.some((f) => !f.name && !f.error);

  const submit = () => {
    if (uploading || (!text.trim() && !ready.length)) return;
    h.say(text.trim(), ready);
    setText("");
    setFiles([]);
    input.current?.focus();
  };

  const upload = async (list: FileList | null) => {
    if (!list) return;
    for (const file of Array.from(list)) {
      const entry: Upload = { label: file.name, name: null };
      setFiles((f) => [...f, entry]);
      const fd = new FormData();
      fd.append("file", file, file.name);
      try {
        const r = await api<{ name: string }>("/api/upload", { method: "POST", body: fd });
        setFiles((f) => f.map((x) => (x === entry ? { ...x, name: r.name } : x)));
      } catch (e) {
        setFiles((f) => f.map((x) => (x === entry ? { ...x, error: (e as Error).message } : x)));
      }
    }
  };

  const toggleRecording = async () => {
    setError(null);
    if (!h.remote) return h.mic();
    if (rec.current?.state === "recording") return rec.current.stop();
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser can't record. Open HAVOC over the https Tailscale address.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone permission was denied.");
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m));
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      setRecording(false);
      setSendingVoice(true);
      const type = r.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      const fd = new FormData();
      fd.append("audio", new Blob(chunks, { type }), `voice.${ext}`);
      fd.append("attachments", JSON.stringify(ready));
      setFiles([]);
      try {
        const res = await api<{ audio_url: string | null }>("/api/voice", { method: "POST", body: fd });
        if (res.audio_url) new Audio(res.audio_url).play().catch(() => undefined);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setSendingVoice(false);
      }
    };
    rec.current = r;
    r.start();
    setRecording(true);
  };

  const listening = recording || (!h.remote && h.state === "listening");

  return (
    <div className="border-t border-white/[0.06] p-3 sm:p-4">
      <AnimatePresence initial={false}>
        {files.length > 0 && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="flex flex-wrap gap-1.5 pb-3">
              {files.map((f, i) => (
                <span
                  key={i}
                  className={`inline-flex max-w-full items-center gap-1.5 rounded-full border py-1 pl-2.5 pr-1 text-[12.5px] ${
                    f.error ? "border-bad/40 text-bad" : "border-white/[0.08] bg-ink-850 text-fog-300"
                  }`}
                >
                  {!f.name && !f.error ? <CircleNotch size={13} className="animate-spin" /> : <Paperclip size={13} />}
                  <span className="max-w-[190px] truncate">{f.error ? `${f.label}: ${f.error}` : f.label}</span>
                  <button aria-label={`Remove ${f.label}`} onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} className="rounded-full p-1 hover:bg-ink-700">
                    <X size={11} weight="bold" />
                  </button>
                </span>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-end gap-2">
        <button
          onClick={toggleRecording}
          disabled={sendingVoice}
          aria-label={listening ? "Stop listening" : "Talk"}
          className={`tactile grid h-11 w-11 shrink-0 place-items-center rounded-xl border ${
            listening ? "border-signal bg-signal text-ink-950" : "border-white/[0.07] bg-ink-850 text-fog-300 hover:text-fog-100"
          } disabled:opacity-50`}
        >
          {sendingVoice ? <CircleNotch size={19} className="animate-spin" /> : recording ? <Stop size={18} weight="fill" /> : <Microphone size={19} weight={listening ? "fill" : "regular"} />}
        </button>
        <button
          onClick={() => picker.current?.click()}
          aria-label="Attach a photo or file"
          className="tactile grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-ink-850 text-fog-300 hover:text-fog-100"
        >
          <Paperclip size={19} />
        </button>
        <input ref={picker} type="file" multiple hidden accept="image/*,application/pdf,.pptx,.docx,.xlsx" onChange={(e) => (upload(e.target.files), (e.target.value = ""))} />
        <textarea
          ref={input}
          value={text}
          rows={1}
          onChange={(e) => {
            setText(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
            if (e.key === "Escape") h.stop();
          }}
          placeholder={files.length ? "Where should these go?" : "Message Havoc"}
          aria-label="Message"
          className="field min-h-11 flex-1 resize-none py-2.5 leading-6"
        />
        <button
          onClick={submit}
          disabled={uploading || (!text.trim() && !ready.length)}
          aria-label="Send"
          className="tactile grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-signal text-ink-950 hover:bg-signal-strong disabled:bg-ink-800 disabled:text-fog-600"
        >
          <ArrowUp size={19} weight="bold" />
        </button>
      </div>
      {error && <p className="mt-2 text-[13px] text-bad">{error}</p>}
    </div>
  );
}
