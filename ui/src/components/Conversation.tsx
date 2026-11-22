import { AnimatePresence, motion } from "framer-motion";
import { ArrowBendDownRight, CheckCircle, CircleNotch, DeviceMobile, DiscordLogo, Microphone, Paperclip, ShieldWarning } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import { CHANNEL_LABELS, toolLabel } from "../lib/labels";
import type { Havoc, Msg } from "../lib/useHavoc";
import { RichText } from "./RichText";

const spring = { type: "spring" as const, stiffness: 100, damping: 20 };

const SUGGESTIONS = [
  "Brief me",
  "What's new in the GSA WhatsApp group?",
  "Any GSA mail I should answer?",
  "What's due on the dashboard this week?",
];

function ChannelBadge({ channel }: { channel: string }) {
  if (channel === "text") return null;
  const Icon = channel === "discord-dm" ? DiscordLogo : channel.includes("voice") ? Microphone : DeviceMobile;
  return (
    <span className="mb-1 inline-flex items-center gap-1 font-mono text-[10.5px] uppercase tracking-[0.14em] text-fog-500">
      <Icon size={12} weight="bold" /> {CHANNEL_LABELS[channel] ?? channel}
    </span>
  );
}

function Bubble({ m }: { m: Msg }) {
  if (m.kind === "tool") {
    return (
      <div className="flex items-center gap-2 pl-1 font-mono text-[12px] text-fog-500">
        {m.done ? <CheckCircle size={14} weight="bold" className="text-signal" /> : <CircleNotch size={14} weight="bold" className="animate-spin text-signal" />}
        {toolLabel(m.name)}
      </div>
    );
  }
  if (m.kind === "user") {
    return (
      <div className="flex flex-col items-end">
        <ChannelBadge channel={m.channel} />
        <div className="max-w-[86%] rounded-2xl rounded-br-md bg-ink-800 px-4 py-2.5 text-[15px] leading-relaxed text-fog-100">
          {m.text && <p className="whitespace-pre-wrap">{m.text}</p>}
          {m.files.length > 0 && (
            <div className={`flex flex-wrap gap-1.5 ${m.text ? "mt-2" : ""}`}>
              {m.files.map((f) => (
                <span key={f} className="inline-flex items-center gap-1 rounded-full bg-ink-700 px-2 py-0.5 text-[12px] text-fog-300">
                  <Paperclip size={12} /> {f}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="max-w-[92%] text-[15px] leading-relaxed text-fog-300">
      <div className="mb-1 font-mono text-[10.5px] uppercase tracking-[0.2em] text-signal">Havoc</div>
      <div className={m.streaming ? "opacity-90" : ""}>
        <RichText text={m.text} />
        {m.streaming && <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-signal" />}
      </div>
    </div>
  );
}

export function Conversation({ h, onSuggest }: { h: Havoc; onSuggest: (t: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  // Scroll only this panel (scrollIntoView would also scroll the page on phones). Braces matter:
  // an effect must return nothing or a cleanup function.
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [h.messages, h.pending]);

  return (
    <div ref={box} className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-4 pt-5 sm:px-7">
      {!h.historyLoaded ? (
        <div className="space-y-5" aria-label="Loading conversation">
          {[72, 48, 64].map((w, i) => (
            <div key={i} className={`flex flex-col gap-2 ${i % 2 ? "items-end" : ""}`}>
              <div className="skeleton h-3 w-16 rounded-full" />
              <div className="skeleton h-14 rounded-2xl" style={{ width: `${w}%` }} />
            </div>
          ))}
        </div>
      ) : h.messages.length === 0 ? (
        <div className="my-auto flex flex-col gap-6 py-8">
          <div>
            <p className="text-2xl font-medium tracking-tight text-fog-100 sm:text-[28px]">{h.greeting || "Standing by, Sir."}</p>
            <p className="mt-2 max-w-[44ch] text-[15px] leading-relaxed text-fog-500">
              Type, talk, or send a photo. Everything you say here, on your phone or in a Discord DM lands in one conversation.
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            {SUGGESTIONS.map((s, i) => (
              <motion.button
                key={s}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ ...spring, delay: i * 0.06 }}
                onClick={() => onSuggest(s)}
                className="tactile group flex items-center gap-2 self-start rounded-xl px-2 py-1.5 text-left text-[15px] text-fog-300 hover:bg-ink-850 hover:text-fog-100"
              >
                <ArrowBendDownRight size={16} className="text-fog-600 transition-colors group-hover:text-signal" />
                {s}
              </motion.button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <AnimatePresence initial={false}>
            {h.messages.map((m) => (
              <motion.div key={m.id} layout="position" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={spring}>
                <Bubble m={m} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      <AnimatePresence>
        {h.pending && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={spring}
            className="mt-5 rounded-2xl border border-warn/30 bg-warn/[0.06] p-4"
          >
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] text-warn">
              <ShieldWarning size={15} weight="bold" /> Needs your go-ahead
            </div>
            <pre className="mt-2.5 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-fog-100">{h.pending.preview}</pre>
            <div className="mt-3 flex gap-2">
              <button onClick={() => h.say("yes")} className="tactile rounded-xl bg-signal px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-signal-strong">
                Go ahead
              </button>
              <button onClick={() => h.say("no")} className="tactile rounded-xl px-4 py-2 text-sm text-fog-300 hover:bg-ink-800">
                Cancel
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
