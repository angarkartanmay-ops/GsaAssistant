import { AnimatePresence, motion } from "framer-motion";
import { STATE_LABELS, toolLabel } from "../lib/labels";
import type { CoreState } from "../lib/useHavoc";

const spring = { type: "spring" as const, stiffness: 260, damping: 26 };

/** Dynamic-island style pill: state, plus whatever tool is running right now. */
export function StatusPill({ state, activity, connected }: { state: CoreState; activity: string | null; connected: boolean }) {
  const label = activity ? toolLabel(activity) : STATE_LABELS[state] ?? state;
  const dot = !connected ? "bg-bad" : state === "idle" ? "bg-ok" : "bg-signal";
  return (
    <motion.div
      layout
      transition={spring}
      className="glass inline-flex items-center gap-2.5 rounded-full py-1.5 pl-3 pr-4"
      role="status"
      aria-live="polite"
    >
      <span className={`h-2 w-2 rounded-full ${dot} ${state !== "offline" ? "breathe" : ""}`} />
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={label}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={spring}
          className="whitespace-nowrap font-mono text-[12px] uppercase tracking-[0.14em] text-fog-300"
        >
          {label}
        </motion.span>
      </AnimatePresence>
    </motion.div>
  );
}
