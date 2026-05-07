import { useState, type KeyboardEvent, useRef, useEffect } from 'react'
import { queryVideo, type QueryResult } from '../lib/api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: QueryResult['sources']
  latency?: number
}

const SEED_QUESTIONS = [
  'What is this video about?',
  'Summarize the main topics covered',
  'At what timestamp does the presenter switch topics?',
  'What code examples are shown?',
  'Explain the key concepts in simple terms',
]

const fmt = (s: number) => {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

/** Strip [⚡ via ...] provider tag */
function stripProviderTag(text: string): string {
  return text.replace(/^\[⚡ via [^\]]+\]\s*\n*/m, '').trim()
}

/** Minimal markdown renderer */
function renderMarkdown(raw: string) {
  const text = stripProviderTag(raw)
  const lines = text.split('\n')
  const elements: React.JSX.Element[] = []
  let inCode = false
  let codeLines: string[] = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.trim().startsWith('```')) {
      if (inCode) {
        elements.push(
          <pre key={`c${i}`} style={{
            background: '#0c0f1a', border: '1px solid #1e293b', borderRadius: 8,
            padding: '10px 14px', fontSize: '0.82em', overflowX: 'auto',
            fontFamily: '"JetBrains Mono", monospace', color: '#94a3b8', margin: '6px 0'
          }}>
            <code>{codeLines.join('\n')}</code>
          </pre>
        )
        codeLines = []
        inCode = false
      } else { inCode = true }
      continue
    }
    if (inCode) { codeLines.push(line); continue }
    if (!line.trim()) { elements.push(<div key={`br${i}`} style={{ height: 8 }} />); continue }
    if (line.startsWith('### ')) { elements.push(<h4 key={i} style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', margin: '6px 0 3px' }}>{line.slice(4)}</h4>); continue }
    if (line.startsWith('## ')) { elements.push(<h3 key={i} style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', margin: '8px 0 4px' }}>{line.slice(3)}</h3>); continue }
    if (line.startsWith('# ')) { elements.push(<h2 key={i} style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0', margin: '10px 0 5px' }}>{line.slice(2)}</h2>); continue }
    if (line.match(/^\s*[-*•]\s/)) {
      elements.push(<div key={i} style={{ display: 'flex', gap: 8, margin: '2px 0', lineHeight: 1.6 }}>
        <span style={{ color: '#818cf8', fontWeight: 700, flexShrink: 0 }}>•</span>
        <span>{inlineFormat(line.replace(/^\s*[-*•]\s/, ''))}</span>
      </div>); continue
    }
    if (line.match(/^\s*\d+\.\s/)) {
      const m = line.match(/^(\s*\d+\.)\s(.*)/)
      if (m) {
        elements.push(<div key={i} style={{ display: 'flex', gap: 8, margin: '2px 0', lineHeight: 1.6 }}>
          <span style={{ color: '#818cf8', fontWeight: 600, flexShrink: 0, minWidth: 22 }}>{m[1]}</span>
          <span>{inlineFormat(m[2])}</span>
        </div>)
        continue
      }
    }
    elements.push(<p key={i} style={{ margin: '3px 0', lineHeight: 1.65 }}>{inlineFormat(line)}</p>)
  }
  return <>{elements}</>
}

function inlineFormat(text: string): (string | React.JSX.Element)[] {
  const parts: (string | React.JSX.Element)[] = []
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let last = 0, m: RegExpExecArray | null
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const t = m[0]
    if (t.startsWith('**')) parts.push(<strong key={m.index} style={{ color: '#e2e8f0' }}>{t.slice(2, -2)}</strong>)
    else if (t.startsWith('*')) parts.push(<em key={m.index}>{t.slice(1, -1)}</em>)
    else parts.push(<code key={m.index} style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc', padding: '1px 5px', borderRadius: 4, fontSize: '0.88em', fontFamily: 'monospace' }}>{t.slice(1, -1)}</code>)
    last = m.index + t.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

export function Query() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (question?: string) => {
    const q = question ?? input.trim()
    if (!q || loading) return
    setInput('')

    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: q }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    // Build chat history from prior messages
    const history = messages
      .filter(m => m.content)
      .map(m => ({ role: m.role as 'user' | 'assistant', content: stripProviderTag(m.content) }))

    try {
      const res = await queryVideo({
        question: q,
        chat_history: history.length > 0 ? history : undefined,
      })
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: stripProviderTag(res.answer),
        sources: res.sources,
        latency: res.latency_ms,
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (err: unknown) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '⚠️ Could not reach the backend. Make sure it\'s running on port 8000.',
      }
      setMessages((prev) => [...prev, errorMsg])
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="page-content animate-fadein" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="page-header" style={{ marginBottom: '1.5rem' }}>
        <h1 className="page-title">Ask VideoRAG</h1>
        <p className="page-subtitle">
          Query your indexed videos using natural language — powered by FAISS retrieval + local Ollama LLM.
        </p>
      </div>

      {/* Seed questions */}
      {messages.length === 0 && (
        <div className="animate-fadein" style={{ marginBottom: '1.5rem' }}>
          <p className="text-sm text-muted" style={{ marginBottom: '0.75rem' }}>Try asking:</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {SEED_QUESTIONS.map((q) => (
              <button
                key={q}
                id={`seed-${q.slice(0, 20).replace(/\s+/g, '-').toLowerCase()}`}
                className="btn btn-secondary"
                style={{ fontSize: '0.8rem', padding: '0.4rem 0.9rem' }}
                onClick={() => send(q)}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Chat messages */}
      <div className="chat-messages" id="chat-messages" style={{ flex: 1, marginBottom: '1rem' }}>
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'user' ? 'U' : '🤖'}
            </div>
            <div>
              <div className="message-bubble" style={{ lineHeight: 1.65 }}>
                {msg.role === 'assistant' ? renderMarkdown(msg.content) : msg.content}
              </div>

              {/* Sources */}
              {msg.sources && msg.sources.length > 0 && (
                <details style={{ marginTop: '0.5rem' }}>
                  <summary style={{ cursor: 'pointer', fontSize: '0.75rem', color: '#6366f1', fontWeight: 600, marginBottom: 6 }}>
                    📎 {msg.sources.length} source(s) referenced
                  </summary>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', marginTop: 6 }}>
                    {msg.sources.map((src, i) => (
                      <div
                        key={i}
                        className="card-glass"
                        style={{ padding: '0.5rem 0.75rem', fontSize: '0.75rem' }}
                      >
                        <span className="font-mono text-accent">
                          ⏱ {fmt(src.timestamp_sec)}
                        </span>
                        {' · '}
                        <span style={{ color: '#64748b', fontSize: '0.72rem' }}>
                          {src.type === 'transcript' || src.type === 'transcript_window' ? '🎙️' : '🖼️'}
                          {' '}{src.text.slice(0, 180)}…
                        </span>
                        {' '}
                        <span className="badge badge-info" style={{ padding: '0.1rem 0.4rem', fontSize: '0.65rem' }}>
                          {(src.score * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                    {msg.latency !== undefined && (
                      <span className="text-xs text-muted">⚡ {msg.latency.toFixed(0)}ms · Local Ollama</span>
                    )}
                  </div>
                </details>
              )}
            </div>
          </div>
        ))}

        {/* Loading bubble */}
        {loading && (
          <div className="message assistant animate-fadein">
            <div className="message-avatar">🤖</div>
            <div className="message-bubble" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
              <span className="text-muted" style={{ fontSize: '0.85rem' }}>Querying FAISS + Ollama…</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input row */}
      <div className="chat-input-row" id="chat-input-row">
        <div className="chat-input-wrap">
          <textarea
            id="chat-input"
            className="chat-input input"
            placeholder="Ask anything about your indexed videos… (Enter to send, Shift+Enter for newline)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            aria-label="Question input"
          />
        </div>

        <button
          id="chat-send-btn"
          className="btn btn-primary btn-icon"
          style={{ width: 52, height: 52 }}
          onClick={() => send()}
          disabled={!input.trim() || loading}
          aria-label="Send message"
        >
          {loading ? <div className="spinner" style={{ width: 16, height: 16 }} /> : '➤'}
        </button>
      </div>
    </div>
  )
}
