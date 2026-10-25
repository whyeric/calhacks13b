"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ChatReply, ToolCall } from "@/lib/types";
import { apiPost } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Message =
  | { role: "owner"; text: string }
  | { role: "desk"; text: string; tool_calls: ToolCall[] };

export function Drawer({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <aside className="drawer" role="dialog" aria-label={title}>
      <div className="section-heading">
        <h2>{title}</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          aria-label={`Close ${title}`}
        >
          ✕
        </Button>
      </div>
      {children}
    </aside>
  );
}
export function ToolCallDetails({ call }: { call: ToolCall }) {
  return (
    <details className="tool-call">
      <summary>
        Looked up <code>{call.name}</code>
      </summary>
      <p className="eyebrow">Input</p>
      <pre>{JSON.stringify(call.input, null, 2)}</pre>
      <p className="eyebrow">Result</p>
      <pre>{JSON.stringify(call.output, null, 2)}</pre>
    </details>
  );
}
const SUGGESTIONS = [
  "Why didn't you buy rain insurance this week?",
  "Why was this hedge declined?",
];
export function ChatDrawer({
  businessId,
  open,
  onClose,
}: {
  businessId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, pending]);
  async function send(text: string) {
    const message = text.trim();
    if (!message || pending) return;
    setPending(true);
    setError("");
    setMessages((rows) => [...rows, { role: "owner", text: message }]);
    try {
      const reply = await apiPost<ChatReply>(
        `/businesses/${encodeURIComponent(businessId)}/chat`,
        { message },
      );
      setMessages((rows) => [
        ...rows,
        { role: "desk", text: reply.reply, tool_calls: reply.tool_calls },
      ]);
      setInput("");
    } catch (err) {
      // Keep the typed question so the owner can resend it.
      setInput(message);
      setMessages((rows) => rows.slice(0, -1));
      setError(
        err instanceof Error
          ? err.message
          : "The desk could not answer. Please retry.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <Drawer title="Ask the desk" open={open} onClose={onClose}>
      <p className="muted">
        Answers quote the desk’s own records. Numbers come from tool results.
      </p>
      <div className="chat-log" aria-live="polite">
        {!messages.length && (
          <div className="suggestions">
            {SUGGESTIONS.map((text) => (
              <Button
                variant="outline"
                key={text}
                onClick={() => send(text)}
                disabled={pending}
              >
                {text}
              </Button>
            ))}
          </div>
        )}
        {messages.map((row, index) => (
          <div
            key={index}
            className={`chat-message ${row.role}`}
            data-testid={`chat-${row.role}`}
          >
            <span className="eyebrow">
              {row.role === "owner" ? "You" : "Desk"}
            </span>
            <p>{row.text}</p>
            {row.role === "desk" &&
              row.tool_calls.map((call, i) => (
                <ToolCallDetails key={i} call={call} />
              ))}
          </div>
        ))}
        {pending && <p className="muted">The desk is checking its records…</p>}
        <div ref={endRef} />
      </div>
      {error && <p role="alert">{error}</p>}
      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <label htmlFor="chat-input">Your question</label>
        <textarea
          id="chat-input"
          value={input}
          rows={2}
          maxLength={2000}
          placeholder="Why?"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <Button className="primary" disabled={pending || !input.trim()}>
          {pending ? "Asking…" : "Ask"}
        </Button>
      </form>
    </Drawer>
  );
}
