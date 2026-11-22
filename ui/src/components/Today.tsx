import { AnimatePresence, motion } from "framer-motion";
import { Bell, CalendarCheck, Ear, Lightning, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api, native, type Status, type Task } from "../lib/api";
import type { Havoc } from "../lib/useHavoc";

const spring = { type: "spring" as const, stiffness: 100, damping: 20 };

const SYSTEM_NAMES: Record<string, string> = {
  llm: "Brain", gmail: "Mail", dashboard: "Dashboard", discord: "Discord", whatsapp: "WhatsApp", voice: "Voice",
};

function dueLabel(due: string | null) {
  if (!due) return null;
  const d = new Date(due.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return due;
  const days = Math.round((d.setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000);
  if (days < 0) return { text: `${-days}d overdue`, tone: "text-bad" };
  if (days === 0) return { text: "today", tone: "text-warn" };
  if (days === 1) return { text: "tomorrow", tone: "text-warn" };
  return { text: `in ${days}d`, tone: "text-fog-500" };
}

function Section({ title, icon, children, aside }: { title: string; icon: React.ReactNode; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="min-w-0">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-fog-500">
          {icon} {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Today({ h, onAsk }: { h: Havoc; onAsk: (t: string) => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [wake, setWake] = useState(() => native()?.isWakeEnabled() ?? false);
  const replies = h.replyCount.current;

  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Status>("/api/status").then((s) => alive && setStatus(s)).catch(() => undefined);
    load();
    const t = window.setInterval(load, 20000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [h.connected]);

  useEffect(() => {
    api<Task[]>("/api/tasks")
      .then((t) => (setTasks(t), setTaskError(null)))
      .catch((e) => setTaskError((e as Error).message));
  }, [replies, h.connected]);

  return (
    <div className="flex flex-col gap-7">
      <Section title="Systems" icon={<Lightning size={13} weight="bold" />}>
        {!status ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-9 rounded-lg" />)}
          </div>
        ) : (
          <ul className="grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-3">
            {Object.entries(status.connectors).map(([k, v]) => (
              <li key={k} className="flex min-w-0 items-center gap-2" title={v.detail}>
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${v.ok ? "bg-ok breathe" : "bg-bad"}`} />
                <span className="text-[13.5px] text-fog-300">{SYSTEM_NAMES[k] ?? k}</span>
                <span className="truncate font-mono text-[11px] text-fog-600">{v.ok ? "" : v.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Due"
        icon={<CalendarCheck size={13} weight="bold" />}
        aside={
          <button onClick={() => onAsk("What's on my dashboard? Refresh it.")} className="tactile rounded-lg px-2 py-1 font-mono text-[11px] uppercase tracking-[0.14em] text-fog-500 hover:bg-ink-850 hover:text-fog-100">
            Refresh
          </button>
        }
      >
        {taskError ? (
          <p className="text-[13.5px] text-bad">Couldn't load tasks: {taskError}</p>
        ) : !tasks ? (
          <div className="space-y-2">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-10 rounded-lg" />)}</div>
        ) : tasks.length === 0 ? (
          <p className="max-w-[40ch] text-[13.5px] leading-relaxed text-fog-500">
            Nothing due. Either you're on top of things or the dashboard isn't connected yet. Suspiciously quiet either way.
          </p>
        ) : (
          <ul className="divide-y divide-white/[0.05]">
            {tasks.slice(0, 7).map((t) => {
              const due = dueLabel(t.due);
              return (
                <li key={t.id} className="flex items-baseline justify-between gap-3 py-2.5">
                  <span className="min-w-0 text-[14px] leading-snug text-fog-100">{t.title}</span>
                  <span className="flex shrink-0 items-center gap-2 font-mono text-[11.5px]">
                    {t.points && <span className="text-fog-600">{t.points} pts</span>}
                    {due && typeof due === "object" ? <span className={due.tone}>{due.text}</span> : due && <span className="text-fog-500">{due}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title="Alerts" icon={<Bell size={13} weight="bold" />}>
        {h.alerts.length === 0 ? (
          <p className="text-[13.5px] text-fog-500">No alerts since you opened this.</p>
        ) : (
          <ul className="divide-y divide-white/[0.05]">
            <AnimatePresence initial={false}>
              {h.alerts.slice(0, 6).map((a) => (
                <motion.li key={a.id} layout initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, height: 0 }} transition={spring} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-signal">{a.title}</div>
                    <div className="mt-0.5 text-[13.5px] leading-snug text-fog-300">{a.body}</div>
                  </div>
                  <button aria-label="Dismiss" onClick={() => h.dismissAlert(a.id)} className="rounded-md p-1 text-fog-600 hover:bg-ink-850 hover:text-fog-100">
                    <X size={12} weight="bold" />
                  </button>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </Section>

      {native() && (
        <Section title="This phone" icon={<Ear size={13} weight="bold" />}>
          <label className="flex cursor-pointer items-center justify-between gap-4 py-1">
            <span>
              <span className="block text-[14px] text-fog-100">Listen for "Hey Havoc"</span>
              <span className="block text-[12.5px] text-fog-500">Runs on the phone. Google Assistant is untouched.</span>
            </span>
            <input
              type="checkbox"
              checked={wake}
              onChange={(e) => {
                native()?.setWakeEnabled(e.target.checked);
                setWake(e.target.checked);
              }}
              className="h-5 w-9 accent-[var(--color-signal)]"
            />
          </label>
          <button onClick={() => native()?.openSettings()} className="tactile mt-2 rounded-lg px-2 py-1 text-[13px] text-signal hover:bg-ink-850">
            Phone settings
          </button>
        </Section>
      )}
    </div>
  );
}
