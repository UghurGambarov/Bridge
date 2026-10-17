// Minimal, safe rendering of the light Markdown real models write (bold, inline code, bullets,
// headings, rules). Builds React elements only — never injects HTML — so model text cannot add markup.
import { ReactNode } from "react";

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(<strong key={`${keyBase}-${i++}`}>{tok.slice(2, -2)}</strong>);
    else out.push(<code key={`${keyBase}-${i++}`} className="rounded bg-paper-sunk px-1 font-mono text-[0.9em]">{tok.slice(1, -1)}</code>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function RichText({ text, className }: { text: string; className?: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = (k: number) => {
    if (list.length) {
      blocks.push(<ul key={`ul-${k}`} className="my-1 list-disc space-y-0.5 pl-5">{list}</ul>);
      list = [];
    }
  };
  lines.forEach((raw, k) => {
    const line = raw.trimEnd();
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) return flush(k);
    const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      list.push(<li key={`li-${k}`}>{inline(bullet[1], `li-${k}`)}</li>);
      return;
    }
    flush(k);
    if (!line.trim()) return;
    const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (heading) {
      blocks.push(<div key={`h-${k}`} className="mt-1.5 font-semibold">{inline(heading[1], `h-${k}`)}</div>);
      return;
    }
    blocks.push(<p key={`p-${k}`} className="my-0.5">{inline(line, `p-${k}`)}</p>);
  });
  flush(lines.length);
  return <div className={className}>{blocks}</div>;
}
