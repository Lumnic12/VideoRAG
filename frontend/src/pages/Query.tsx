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
  'What is SSIM and how is it used?',
  'Summarize the main topics in the video',
  'At what timestamp does the presenter switch topics?',
  'What code examples are shown?',
]

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

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: q,
    }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await queryVideo({ question: q })
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: res.answer,
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
          Query your indexed videos using natural language — powered by FAISS retrieval + LLM.
        </p>
      </div>

      {/* Seed questions (shown when empty) */}
      {messages.length === 0 && (
        <div className="animate-fadein" style={{ marginBottom: '1.5rem' }}>
          <p className="text-sm text-muted" style={{ marginBottom: '0.75rem' }}>
            Try asking:
          </p>
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
              <div className="message-bubble">{msg.content}</div>

              {/* Sources */}
              {msg.sources && msg.sources.length > 0 && (
                <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                  {msg.sources.map((src, i) => (
                    <div
                      key={i}
                      className="card-glass"
                      style={{ padding: '0.5rem 0.75rem', fontSize: '0.75rem' }}
                    >
                      <span className="font-mono text-accent">
                        ⏱ {src.timestamp_sec.toFixed(1)}s
                      </span>
                      {' · '}
                      <span className="text-muted">{src.text}</span>
                      {' '}
                      <span className="badge badge-info" style={{ padding: '0.1rem 0.4rem', fontSize: '0.65rem' }}>
                        {(src.score * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                  {msg.latency !== undefined && (
                    <span className="text-xs text-muted">⚡ {msg.latency}ms</span>
                  )}
                </div>
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
              <span className="text-muted" style={{ fontSize: '0.85rem' }}>Retrieving context…</span>
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
            placeholder="Ask anything about your video… (Enter to send, Shift+Enter for newline)"
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
