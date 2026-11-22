import { AnimatePresence, motion } from "framer-motion";
import { ChatCircleText, ListChecks, PlugsConnected } from "@phosphor-icons/react";
import { lazy, Suspense, useEffect, useState } from "react";
import { api, type Me } from "./lib/api";
import { useHavoc } from "./lib/useHavoc";
import { StatusPill } from "./components/StatusPill";
import { Conversation } from "./components/Conversation";
import { Composer } from "./components/Composer";
import { Today } from "./components/Today";
import { Connections } from "./components/Connections";

// three.js is most of the bundle: load it after the chat so the page is usable instantly.
const LazyCore = lazy(() => import("./components/core/Core").then((m) => ({ default: m.Core })));
function Core(props: React.ComponentProps<typeof LazyCore>) {
  return (
    <Suspense fallback={<div className={props.className} aria-hidden />}>
      <LazyCore {...props} />
    </Suspense>
  );
}

type Tab = "talk" | "today";
const spring = { type: "spring" as const, stiffness: 100, damping: 20 };

function useIsWide() {
  const q = "(min-width: 1024px)";
  const [wide, setWide] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setWide(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return wide;
}

export default function App() {
  const h = useHavoc();
  const wide = useIsWide();
  const [tab, setTab] = useState<Tab>("talk");
  const [showConnections, setShowConnections] = useState(false);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api<Me>("/api/me").then(setMe).catch(() => undefined);
  }, [h.connected]);

  const ask = (text: string) => {
    h.say(text);
    setTab("talk");
  };

  const caption = h.caption && (
    <motion.p key={h.caption} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="max-w-[46ch] text-center text-[14px] italic text-fog-500">
      "{h.caption}"
    </motion.p>
  );

  const header = (
    <header className="relative z-10 flex items-center justify-between gap-3 px-4 pb-2 pt-[max(14px,env(safe-area-inset-top))] sm:px-8">
      <div className="min-w-0">
        <div className="font-mono text-[15px] font-semibold tracking-[0.34em] text-fog-100">H.A.V.O.C.</div>
        <div className="hidden truncate text-[12px] text-fog-600 sm:block">Helpful Assistant, Very Occasionally Chaotic</div>
      </div>
      {wide && <StatusPill state={h.state} activity={h.activity} connected={h.connected} />}
      <button
        onClick={() => setShowConnections(true)}
        className="tactile inline-flex items-center gap-2 rounded-xl border border-white/[0.07] px-3 py-2 text-[13px] text-fog-300 hover:bg-ink-850 hover:text-fog-100"
      >
        <PlugsConnected size={16} />
        <span className="hidden sm:inline">Connections</span>
      </button>
    </header>
  );

  return (
    <div className={`grain relative flex flex-col ${wide ? "min-h-[100dvh]" : "h-[100dvh] overflow-hidden"}`}>
      {/* soft vignette behind the core; colour stays within the one accent */}
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(70%_60%_at_28%_38%,rgba(92,180,217,0.07),transparent_70%)]" />
      {header}

      {wide ? (
        <main className="relative z-10 mx-auto grid w-full max-w-[1500px] flex-1 grid-cols-[minmax(0,1.08fr)_minmax(420px,0.92fr)] gap-8 px-8 pb-8">
          <section className="flex min-h-0 flex-col">
            <div className="relative flex flex-col items-start">
              <Core mode={h.state} level={h.level} className="-ml-6 h-[min(52vh,520px)] w-full max-w-[620px]" />
              <div className="absolute bottom-2 left-0 right-[10%] flex justify-center"><AnimatePresence>{caption}</AnimatePresence></div>
            </div>
            <div className="mt-2 max-w-[640px] overflow-y-auto pr-2">
              <Today h={h} onAsk={ask} />
            </div>
          </section>
          <section className="glass flex h-[calc(100dvh-96px)] min-h-0 flex-col rounded-[2rem]">
            <Conversation h={h} onSuggest={ask} />
            <Composer h={h} />
          </section>
        </main>
      ) : (
        <main className="relative z-10 flex min-h-0 flex-1 flex-col">
          <div className="flex shrink-0 flex-col items-center px-4">
            <Core mode={h.state} level={h.level} className="h-[min(22vh,190px)] w-full max-w-[280px]" />
            <div className="-mt-2 mb-2"><StatusPill state={h.state} activity={h.activity} connected={h.connected} /></div>
            <AnimatePresence>{caption}</AnimatePresence>
          </div>
          <AnimatePresence mode="wait" initial={false}>
            {tab === "talk" ? (
              <motion.section key="talk" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} transition={spring} className="glass mx-3 mb-2 flex min-h-0 flex-1 flex-col rounded-[1.6rem]">
                <Conversation h={h} onSuggest={ask} />
                <Composer h={h} />
              </motion.section>
            ) : (
              <motion.section key="today" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={spring} className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 pt-2">
                <Today h={h} onAsk={ask} />
              </motion.section>
            )}
          </AnimatePresence>
          <nav className="z-10 mx-3 shrink-0 mb-[max(10px,env(safe-area-inset-bottom))] grid grid-cols-2 gap-1 rounded-2xl bg-ink-900/90 p-1 backdrop-blur">
            {([["talk", "Talk", ChatCircleText], ["today", "Today", ListChecks]] as const).map(([id, label, Icon]) => (
              <button key={id} onClick={() => setTab(id)} className={`tactile relative flex items-center justify-center gap-2 rounded-xl py-2.5 text-[14px] ${tab === id ? "text-fog-100" : "text-fog-500"}`}>
                {tab === id && <motion.span layoutId="dock" className="absolute inset-0 rounded-xl bg-ink-800" transition={{ type: "spring", stiffness: 300, damping: 30 }} />}
                <Icon size={18} weight={tab === id ? "fill" : "regular"} className="relative" />
                <span className="relative">{label}</span>
              </button>
            ))}
          </nav>
        </main>
      )}

      <AnimatePresence>{showConnections && <Connections onClose={() => setShowConnections(false)} />}</AnimatePresence>
      {me && !me.local && <span className="sr-only">Connected remotely to {me.name}</span>}
    </div>
  );
}
