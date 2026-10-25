import type { ReactNode } from "react";

// Desk replies are plain text with light Markdown (Claude writes **bold**, `code` and lists).
// They are rendered as React elements, never as HTML, and every word and number stays exactly
// as the API wrote it: only the Markdown marks are dropped.
type Block =
  { kind: "p"; text: string } | { kind: "ul" | "ol"; items: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

function blocks(text: string): Block[] {
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push({ kind: "p", text: para.join("\n") });
    para = [];
  };
  for (const line of text.split(/\r?\n/)) {
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flush();
      const kind = bullet ? "ul" : "ol";
      const item = (bullet ?? numbered)![1];
      const last = out[out.length - 1];
      if (last && last.kind === kind) last.items.push(item);
      else out.push({ kind, items: [item] });
    } else if (!line.trim()) {
      flush();
    } else {
      // A heading reads as a bold line; a list item's wrapped continuation joins the item.
      const heading = HEADING.exec(line);
      const last = out[out.length - 1];
      if (
        !para.length &&
        !heading &&
        last &&
        last.kind !== "p" &&
        /^\s/.test(line)
      )
        last.items[last.items.length - 1] += ` ${line.trim()}`;
      else para.push(heading ? `**${heading[1]}**` : line);
    }
  }
  flush();
  return out;
}

// `code` first so its contents stay literal, then **bold**, then *italic*. Underscores are left
// alone: ids like hdg_taxi_20261026_rain must not turn italic.
const INLINE = /`([^`\n]+)`|\*\*(.+?)\*\*|\*([^*\s](?:[^*\n]*[^*\s])?)\*/g;

function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let at = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > at) nodes.push(text.slice(at, m.index));
    const key = nodes.length;
    if (m[1] !== undefined) nodes.push(<code key={key}>{m[1]}</code>);
    else if (m[2] !== undefined)
      nodes.push(<strong key={key}>{inline(m[2])}</strong>);
    else nodes.push(<em key={key}>{m[3]}</em>);
    at = m.index + m[0].length;
  }
  if (at < text.length) nodes.push(text.slice(at));
  return nodes;
}

export function ChatText({ text }: { text: string }) {
  return (
    <div className="chat-text">
      {blocks(text).map((block, i) =>
        block.kind === "p" ? (
          <p key={i}>{inline(block.text)}</p>
        ) : block.kind === "ul" ? (
          <ul key={i}>
            {block.items.map((item, j) => (
              <li key={j}>{inline(item)}</li>
            ))}
          </ul>
        ) : (
          <ol key={i}>
            {block.items.map((item, j) => (
              <li key={j}>{inline(item)}</li>
            ))}
          </ol>
        ),
      )}
    </div>
  );
}
