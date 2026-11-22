import { Fragment, type ReactNode } from "react";

/**
 * Tiny, safe formatter for assistant text: **bold**, `code`, links, "- " lists and line breaks.
 * Builds React nodes (never innerHTML), so mail and chat content can't inject markup.
 */
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)]+)/g;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={k} className="font-semibold text-fog-100">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={k} className="rounded-md bg-ink-800 px-1.5 py-0.5 font-mono text-[0.88em] text-fog-100">{part.slice(1, -1)}</code>;
    if (/^https?:\/\//.test(part))
      return (
        <a key={k} href={part} target="_blank" rel="noreferrer" className="break-all text-signal underline decoration-signal/40 underline-offset-2 hover:decoration-signal">
          {part}
        </a>
      );
    return <Fragment key={k}>{part}</Fragment>;
  });
}

export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = (i: number) => {
    if (!list.length) return;
    blocks.push(
      <ul key={`ul-${i}`} className="my-1.5 space-y-1 pl-1">
        {list.map((li, j) => (
          <li key={j} className="flex gap-2.5">
            <span className="mt-[0.6em] h-1 w-1 shrink-0 rounded-full bg-signal/70" />
            <span>{inline(li, `li-${i}-${j}`)}</span>
          </li>
        ))}
      </ul>,
    );
    list = [];
  };
  text.split("\n").forEach((line, i) => {
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (m) {
      list.push(m[1]);
      return;
    }
    flush(i);
    if (line.trim() === "") blocks.push(<div key={`sp-${i}`} className="h-2" />);
    else blocks.push(<p key={`p-${i}`}>{inline(line, `p-${i}`)}</p>);
  });
  flush(-1);
  return <>{blocks}</>;
}
