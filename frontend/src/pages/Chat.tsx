import { useState, useEffect, useRef, useCallback } from 'react'
import {
  uploadVideo,
  getTaskStatus,
  queryVideo,
  listVideos,
  deleteVideo,
  getKeyframes,
  getAudioUrl,
  reseedVideos,
  type VideoListItem,
  type QuerySource,
  type ChatHistoryMessage,
  type KeyframeInfo,
} from '../lib/api'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: QuerySource[]
  loading?: boolean
}

const fmt = (s: number) => {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

/** Strip [⚡ via ...] provider tag from response */
function stripProviderTag(text: string): string {
  return text.replace(/^\[⚡ via [^\]]+\]\s*\n*/m, '').trim()
}

/** Simple markdown renderer for chat messages */
function renderMarkdown(text: string) {
  const cleaned = stripProviderTag(text)
  const lines = cleaned.split('\n')
  const elements: React.JSX.Element[] = []
  let inCodeBlock = false
  let codeLines: string[] = []
  let codeLanguage = ''

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        elements.push(
          <div key={`code-${i}`} style={mdStyles.codeBlockWrap}>
            {codeLanguage && <div style={mdStyles.codeLang}>{codeLanguage}</div>}
            <pre style={mdStyles.codeBlock}><code>{codeLines.join('\n')}</code></pre>
          </div>
        )
        codeLines = []
        codeLanguage = ''
        inCodeBlock = false
      } else {
        codeLanguage = line.trim().slice(3).trim()
        inCodeBlock = true
      }
      continue
    }

    if (inCodeBlock) { codeLines.push(line); continue }

    if (line.trim() === '') {
      elements.push(<div key={`br-${i}`} style={{ height: 6 }} />)
      continue
    }

    if (line.startsWith('### ')) {
      elements.push(<h4 key={i} style={mdStyles.h3}>{processInline(line.slice(4))}</h4>)
      continue
    }
    if (line.startsWith('## ')) {
      elements.push(<h3 key={i} style={mdStyles.h2}>{processInline(line.slice(3))}</h3>)
      continue
    }
    if (line.startsWith('# ')) {
      elements.push(<h2 key={i} style={mdStyles.h1}>{processInline(line.slice(2))}</h2>)
      continue
    }

    if (line.match(/^\s*[-*•]\s/)) {
      const content = line.replace(/^\s*[-*•]\s/, '')
      elements.push(
        <div key={i} style={mdStyles.bullet}>
          <span style={mdStyles.bulletDot}>•</span>
          <span>{processInline(content)}</span>
        </div>
      )
      continue
    }

    if (line.match(/^\s*\d+\.\s/)) {
      const match = line.match(/^(\s*\d+\.)\s(.*)/)
      if (match) {
        elements.push(
          <div key={i} style={mdStyles.bullet}>
            <span style={mdStyles.numDot}>{match[1]}</span>
            <span>{processInline(match[2])}</span>
          </div>
        )
        continue
      }
    }

    elements.push(<p key={i} style={mdStyles.para}>{processInline(line)}</p>)
  }

  return <>{elements}</>
}

function processInline(text: string): (string | React.JSX.Element)[] {
  const parts: (string | React.JSX.Element)[] = []
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|@\d+:\d+(?:\.\d+)?)/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index))
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**'))
      parts.push(<strong key={match.index} style={{ color: 'var(--text-pure)', fontWeight: 700 }}>{token.slice(2, -2)}</strong>)
    else if (token.startsWith('*') && token.endsWith('*'))
      parts.push(<em key={match.index}>{token.slice(1, -1)}</em>)
    else if (token.startsWith('`') && token.endsWith('`'))
      parts.push(<code key={match.index} style={mdStyles.inlineCode}>{token.slice(1, -1)}</code>)
    else if (token.startsWith('@'))
      parts.push(<span key={match.index} style={mdStyles.timestamp}>⏱ {token.slice(1)}</span>)
    lastIndex = match.index + token.length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts
}

const mdStyles: Record<string, React.CSSProperties> = {
  h1: { fontSize: 18, fontWeight: 700, color: 'var(--text-pure)', margin: '10px 0 5px' },
  h2: { fontSize: 16, fontWeight: 700, color: 'var(--text-pure)', margin: '8px 0 4px' },
  h3: { fontSize: 14, fontWeight: 700, color: 'var(--text-main)', margin: '6px 0 3px' },
  para: { margin: '3px 0', lineHeight: 1.65 },
  bullet: { display: 'flex', gap: 8, alignItems: 'flex-start', margin: '3px 0', lineHeight: 1.65 },
  bulletDot: { color: 'var(--accent-cyan)', fontWeight: 700, flexShrink: 0, marginTop: 2 },
  numDot: { color: 'var(--accent-cyan)', fontWeight: 600, flexShrink: 0, minWidth: 22 },
  inlineCode: {
    background: 'rgba(0, 240, 255, 0.1)', color: 'var(--accent-cyan)',
    padding: '1px 5px', borderRadius: 4, fontSize: '0.88em', fontFamily: 'var(--font-mono)',
  },
  codeBlockWrap: { margin: '8px 0', borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border-light)' },
  codeLang: { background: 'var(--bg-panel)', color: 'var(--text-muted)', fontSize: '0.72em', padding: '4px 12px', fontFamily: 'var(--font-mono)' },
  codeBlock: {
    background: 'var(--bg-deep)', padding: '10px 14px', fontSize: '0.82em',
    overflowX: 'auto', fontFamily: 'var(--font-mono)',
    color: 'var(--text-main)', margin: 0, lineHeight: 1.5,
  },
  timestamp: {
    color: 'var(--accent-cyan)', fontWeight: 600, fontSize: '0.88em',
    background: 'rgba(0, 240, 255, 0.1)', padding: '1px 6px', borderRadius: 4, border: '1px solid rgba(0, 240, 255, 0.2)'
  },
}

const FOLLOW_UP_CHIPS = [
  'Explain in more detail',
  'What happens next?',
  'Summarize the key points',
  'Show related timestamps',
  'What are the main concepts?',
]

export function Chat() {
  const [videos, setVideos] = useState<VideoListItem[]>([])
  const [activeVideoIds, setActiveVideoIds] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadStatus, setUploadStatus] = useState('')
  const [loadingVideos, setLoadingVideos] = useState(true)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [sendingMsg, setSendingMsg] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [showFrames, setShowFrames] = useState(false)
  const [keyframes, setKeyframes] = useState<KeyframeInfo[]>([])
  const [selectedFrame, setSelectedFrame] = useState<KeyframeInfo | null>(null)
  const [hasAudio, setHasAudio] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  const fetchVideos = useCallback(async () => {
    try {
      let list = await listVideos()
      // If empty, try auto-reseeding
      if (list.length === 0) {
        await reseedVideos()
        list = await listVideos()
      }
      setVideos(list)
    } catch {
      // silently fail
    } finally {
      setLoadingVideos(false)
    }
  }, [])

  useEffect(() => {
    const init = async () => {
      await fetchVideos()
    }
    init()
    const id = setInterval(fetchVideos, 15000)
    return () => clearInterval(id)
  }, [fetchVideos])

  // Auto-select the most recent done video on first load
  useEffect(() => {
    if (activeVideoIds.length === 0 && videos.length > 0) {
      const doneVideos = videos.filter(v => v.status === 'done')
      if (doneVideos.length > 0) {
        // Pick the last one (most recently added)
        setActiveVideoIds([doneVideos[doneVideos.length - 1].job_id])
      }
    }
  }, [videos])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])


  // Load keyframes only if exactly ONE video is selected
  useEffect(() => {
    if (activeVideoIds.length !== 1) { setKeyframes([]); setHasAudio(false); return }
    const vidId = activeVideoIds[0]
    getKeyframes(vidId).then(kfs => {
      setKeyframes(kfs)
      if (kfs.length > 0) setSelectedFrame(kfs[0])
    }).catch(() => setKeyframes([]))
    const vid = videos.find(v => v.job_id === vidId)
    setHasAudio(vid?.has_audio ?? false)
  }, [activeVideoIds, videos])

  const buildChatHistory = (): ChatHistoryMessage[] =>
    messages
      .filter(m => !m.loading && m.content)
      .map(m => ({
        role: m.role as 'user' | 'assistant',
        content: stripProviderTag(m.content),
      }))

  const pollJob = (jobId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const task = await getTaskStatus(jobId)
        setUploadProgress(task.progress ?? 0)
        if (task.status === 'processing') setUploadStatus(`Processing… ${task.progress ?? 0}%`)
        if (task.status === 'done') {
          clearInterval(pollRef.current!)
          setUploading(false)
          setUploadStatus('')
          setUploadProgress(0)
          await fetchVideos()
          setActiveVideoIds([jobId])
          setMessages([{
            id: 'welcome',
            role: 'assistant',
            content: `✅ Video processed! Found **${task.keyframe_count ?? 0}** keyframes and transcribed audio.\n\nI now have full visual + audio context of this video. Ask me anything!`,
          }])
        }
        if (task.status === 'failed') {
          clearInterval(pollRef.current!)
          setUploading(false)
          setUploadStatus(`❌ Failed: ${task.error ?? 'Unknown error'}`)
        }
      } catch {
        clearInterval(pollRef.current!)
        setUploading(false)
      }
    }, 2000)
  }

  const handleFile = async (file: File) => {
    if (!file) return
    setUploading(true)
    setUploadStatus('Uploading…')
    setUploadProgress(5)
    try {
      const resp = await uploadVideo(file)
      setUploadStatus('Queued — extracting keyframes…')
      pollJob(resp.task_id)
    } catch (e: any) {
      setUploading(false)
      setUploadStatus(`Upload failed: ${e.message}`)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  const handleDelete = async (jobId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!window.confirm('Delete this video and ALL its data?')) return
    setDeleting(jobId)
    try {
      await deleteVideo(jobId)
      if (activeVideoIds.includes(jobId)) { setActiveVideoIds(prev => prev.filter(id => id !== jobId)); setMessages([]) }
      await fetchVideos()
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`)
    } finally {
      setDeleting(null)
    }
  }

  const sendMessage = async (overrideQuestion?: string) => {
    const question = overrideQuestion || input.trim()
    if (!question || sendingMsg) return
    if (!overrideQuestion) setInput('')

    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', content: question }
    const loadingMsg: ChatMessage = {
      id: Date.now().toString() + '_ai',
      role: 'assistant',
      content: '',
      loading: true,
    }

    const history = buildChatHistory()
    setMessages(prev => [...prev, userMsg, loadingMsg])
    setSendingMsg(true)

    try {
      const result = await queryVideo({
        question,
        video_ids: activeVideoIds.length > 0 ? activeVideoIds : undefined,
        chat_history: history.length > 0 ? history : undefined,
      })
      // Strip provider tag server-side before setting
      const cleanAnswer = stripProviderTag(result.answer)
      setMessages(prev => prev.map(m =>
        m.loading
          ? { ...m, loading: false, content: cleanAnswer, sources: result.sources }
          : m
      ))
    } catch (err: any) {
      setMessages(prev => prev.map(m =>
        m.loading
          ? { ...m, loading: false, content: `⚠️ Error: ${err.message}` }
          : m
      ))
    } finally {
      setSendingMsg(false)
    }
  }

  const activeVideos = videos.filter(v => activeVideoIds.includes(v.job_id))
  const lastAiMsg = [...messages].reverse().find(m => m.role === 'assistant' && !m.loading)

  return (
    <div style={styles.shell}>
      {/* ── Left sidebar: video library ── */}
      <aside style={styles.sidebar}>
        <div style={styles.sidebarHeader}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-pure)' }}>📹 My Videos</span>
          <button
            style={styles.uploadBtn}
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '⏳' : '+ Upload'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="video/mp4,video/mov,video/avi,video/mkv,video/webm"
            style={{ display: 'none' }}
            onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
        </div>

        {/* Upload progress */}
        {uploading && (
          <div style={styles.uploadStatus}>
            <div style={styles.progressTrack}>
              <div style={{ ...styles.progressFill, width: `${uploadProgress}%` }} />
            </div>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{uploadStatus}</span>
          </div>
        )}

        {/* Drag-drop zone */}
        <div
          style={{ ...styles.dropZone, borderColor: dragOver ? 'var(--accent-cyan)' : '#334155', background: dragOver ? 'rgba(99,102,241,0.08)' : 'transparent' }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
        >
          <span style={{ fontSize: 11, color: dragOver ? 'var(--accent-cyan)' : 'var(--text-muted)' }}>
            {dragOver ? '📂 Drop here!' : '📁 Drop video here'}
          </span>
        </div>

        {/* Video list */}
        <div style={styles.videoList}>
          {loadingVideos ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: 12, textAlign: 'center' }}>
              <div className="spinner" style={{ width: 16, height: 16, margin: '0 auto 6px' }} />
              Loading…
            </div>
          ) : videos.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: 16, textAlign: 'center', lineHeight: 1.7 }}>
              No videos yet.<br />Upload one to start!
            </div>
          ) : (
            <>
              <div
                onClick={() => {
                  setActiveVideoIds([])
                  setMessages([])
                  setShowFrames(false)
                }}
                style={{
                  ...styles.videoItem,
                  background: activeVideoIds.length === 0 ? 'var(--gradient-neon)' : 'transparent',
                  borderColor: activeVideoIds.length === 0 ? 'var(--accent-cyan)' : 'var(--border-light)',
                  color: activeVideoIds.length === 0 ? '#000' : 'var(--text-main)',
                  justifyContent: 'center',
                  fontWeight: 700,
                  boxShadow: activeVideoIds.length === 0 ? 'var(--shadow-neon)' : 'none',
                }}
              >
                🌐 Chat with ALL Videos
              </div>
              {videos.map(v => {
                const isActive = activeVideoIds.includes(v.job_id);
                return (
                <div
                  key={v.job_id}
                  onClick={() => {
                    setActiveVideoIds(prev => {
                      if (prev.includes(v.job_id)) return prev.filter(id => id !== v.job_id)
                      return [...prev, v.job_id]
                    })
                    setMessages([])
                    setShowFrames(false)
                  }}
                  style={{
                    ...styles.videoItem,
                    background: isActive ? 'rgba(0, 240, 255, 0.15)' : 'rgba(0, 0, 0, 0.05)',
                    borderColor: isActive ? 'var(--accent-cyan)' : 'var(--border-light)',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={styles.videoName} title={v.filename}>
                      {v.filename.length > 22 ? v.filename.slice(0, 22) + '…' : v.filename}
                    </div>
                    <div style={styles.videoMeta}>
                      {v.status === 'done'
                        ? `✅ ${v.keyframe_count} frames${v.has_audio ? ' · 🎵' : ''}`
                        : v.status === 'processing'
                        ? `⏳ ${v.progress}%`
                        : v.status === 'failed'
                        ? '❌ Failed'
                        : '🕐 Queued'}
                    </div>
                  </div>
                  <button
                    style={styles.deleteBtn}
                    onClick={e => handleDelete(v.job_id, e)}
                    disabled={deleting === v.job_id}
                    title="Delete video"
                  >
                    {deleting === v.job_id ? '…' : '🗑'}
                  </button>
                </div>
                )
              })}
            </>
          )}
        </div>
      </aside>

      {/* ── Main area ── */}
      <main style={styles.chatArea}>
        {/* Chat header */}
        <div style={styles.chatHeader}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
            {activeVideoIds.length > 0 ? (
              <>
                <span style={{ fontWeight: 600, color: 'var(--text-pure)', fontSize: 14 }}>
                  💬 <span style={{ color: 'var(--accent-cyan)' }}>
                    {activeVideoIds.length === 1 ? activeVideos[0]?.filename : `${activeVideoIds.length} Videos Selected`}
                  </span>
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {activeVideoIds.length === 1 ? `${activeVideos[0]?.keyframe_count} frames · ` : ''}Local Ollama
                </span>
              </>
            ) : (
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                Chatting with ALL videos (Global Search)
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            
            
            {activeVideoIds.length === 1 && (
              <button
                style={{
                  ...styles.clearBtn,
                  background: showFrames ? 'rgba(0, 240, 255, 0.15)' : 'var(--border-light)',
                  borderColor: showFrames ? 'rgba(0, 240, 255, 0.4)' : 'var(--border-light)',
                  color: showFrames ? 'var(--accent-cyan)' : 'var(--text-muted)',
                }}
                onClick={() => setShowFrames(s => !s)}
              >
                🎞 Frames
              </button>
            )}
            {messages.length > 0 && (
              <button style={styles.clearBtn} onClick={() => setMessages([])}>
                🗑 Clear
              </button>
            )}
          </div>
        </div>

        {/* Keyframe panel (slide-in) */}
        {showFrames && activeVideoIds.length === 1 && (
          <div style={{
            background: 'var(--bg-panel)',
            borderBottom: '1px solid var(--border-light)',
            padding: '12px 16px',
          }}>
            {/* Audio player */}
            {hasAudio && activeVideoIds.length === 1 && (
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 11, color: 'var(--accent-cyan)', fontWeight: 600, marginBottom: 6 }}>🎵 Extracted Audio</div>
                <audio
                  ref={audioRef}
                  controls
                  src={getAudioUrl(activeVideoIds[0])}
                  style={{ width: '100%', height: 36 }}
                />
              </div>
            )}
            {/* Keyframe strip */}
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 6 }}>
              {keyframes.map((kf, idx) => (
                <div
                  key={kf.index}
                  onClick={() => {
                    setSelectedFrame(kf)
                    if (audioRef.current) audioRef.current.currentTime = kf.timestamp_sec
                  }}
                  style={{
                    flexShrink: 0,
                    width: 100,
                    cursor: 'pointer',
                    borderRadius: 8,
                    overflow: 'hidden',
                    border: selectedFrame?.index === kf.index ? '2px solid var(--accent-cyan)' : '2px solid var(--border-light)',
                    transition: 'border-color 0.2s',
                  }}
                >
                  <img
                    src={kf.image_url}
                    alt={`Frame ${idx}`}
                    style={{ width: '100%', aspectRatio: '16/9', objectFit: 'cover', display: 'block' }}
                    loading="lazy"
                  />
                  <div style={{ padding: '3px 6px', fontSize: 10, color: 'var(--text-muted)', background: 'var(--bg-deep)', textAlign: 'center', fontFamily: 'monospace' }}>
                    {fmt(kf.timestamp_sec)}
                  </div>
                </div>
              ))}
              {keyframes.length === 0 && (
                <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>No keyframes found for this video.</div>
              )}
            </div>
            {/* Selected frame large view */}
            {selectedFrame && (
              <div style={{ marginTop: 10, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <img
                  src={selectedFrame.image_url}
                  alt="Selected frame"
                  style={{ width: 220, borderRadius: 10, border: '1px solid var(--border-light)', flexShrink: 0 }}
                />
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.7 }}>
                  <div><span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>Frame #{selectedFrame.index}</span></div>
                  <div>⏱ <span style={{ fontFamily: 'monospace', color: 'var(--text-pure)' }}>{fmt(selectedFrame.timestamp_sec)}</span></div>
                  <button
                    className="btn btn-secondary"
                    style={{ marginTop: 8, fontSize: 11, padding: '4px 12px' }}
                    onClick={() => sendMessage(`What is happening at ${fmt(selectedFrame.timestamp_sec)} in this video?`)}
                  >
                    Ask about this frame
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Messages */}
        <div style={styles.messages}>
          {messages.length === 0 && activeVideoIds.length === 0 && (
            <div style={styles.emptyState}>
              <div style={styles.toutBanner}>
                <div style={styles.toutGlow} />
                <div style={styles.badgeSuccess}>✨ Next-Gen Video AI</div>
                <h1 style={{ fontSize: '2.5rem', fontWeight: 800, margin: '16px 0 8px', letterSpacing: '-0.03em', background: 'var(--gradient-hot)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                  Semantic Video Synthesizer
                </h1>
                <p style={{ fontSize: '1.1rem', color: 'var(--text-muted)', maxWidth: 500, margin: '0 auto', lineHeight: 1.6 }}>
                  Experience the future of video intelligence. Upload a lecture and let our local Ollama AI instantly dissect visual keyframes and audio transcripts for seamless, context-aware chat.
                </p>
                <div style={{ display: 'flex', gap: 16, marginTop: 32, justifyContent: 'center' }}>
                  <button style={styles.uploadBtnLarge} onClick={() => fileRef.current?.click()}>
                    <span style={{ fontSize: 20 }}>🚀</span> Start Synthesizing
                  </button>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: 12, marginTop: 40, flexWrap: 'wrap', justifyContent: 'center', opacity: 0.6 }}>
                {['What is this video about?', 'Summarize the main topics', 'What are the key concepts?'].map(q => (
                  <button key={q} style={{ ...styles.chipBtn, cursor: 'not-allowed' }} disabled>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.length === 0 && activeVideoIds.length > 0 && (
            <div style={styles.emptyState}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>💬</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-pure)', marginBottom: 8 }}>
                Ready to chat about <span style={{ color: 'var(--accent-cyan)' }}>{activeVideoIds.length === 1 ? activeVideos[0]?.filename : `${activeVideoIds.length} Selected Videos`}</span>
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16, maxWidth: 400, textAlign: 'center' }}>
                I have full context from keyframes + audio transcript via local Ollama.
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
                {['What is this video about?', 'Summarize the key points', 'What happens at the beginning?', 'List the main topics covered', 'Explain the key concepts'].map(q => (
                  <button key={q} style={styles.chipBtn} onClick={() => sendMessage(q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} style={{ ...styles.msgRow, justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
              {msg.role === 'assistant' && (
                <div style={styles.avatar}>🤖</div>
              )}
              <div style={{
                ...styles.bubble,
                background: msg.role === 'user'
                  ? 'linear-gradient(135deg,#4f46e5,#7c3aed)'
                  : 'var(--border-light)',
                borderColor: msg.role === 'user' ? '#4f46e5' : '#334155',
                maxWidth: msg.role === 'user' ? '65%' : '78%',
              }}>
                {msg.loading ? (
                  <div className="typing-dots" style={{ display: 'flex', gap: 4, padding: '4px 0' }}>
                    <span style={dotStyle(0)} />
                    <span style={dotStyle(1)} />
                    <span style={dotStyle(2)} />
                  </div>
                ) : (
                  <>
                    <div style={styles.bubbleText}>
                      {msg.role === 'assistant' ? renderMarkdown(msg.content) : msg.content}
                    </div>
                    {msg.sources && msg.sources.length > 0 && (
                      <details style={styles.sources}>
                        <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--accent-cyan)', fontWeight: 600 }}>
                          📎 {msg.sources.length} source(s) referenced
                        </summary>
                        {msg.sources.map((s, i) => (
                          <div key={i} style={styles.sourceItem}>
                            <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
                              ⏱ {fmt(s.timestamp_sec ?? s.timestamp)}
                            </span>
                            <span style={{ color: 'var(--text-muted)', margin: '0 4px' }}>·</span>
                            <span style={{ color: 'var(--text-muted)' }}>
                              {s.type === 'transcript' || s.type === 'transcript_window' ? '🎙️' : '🖼️'}
                            </span>
                            {' '}
                            {(s.text ?? s.chunk_text ?? '').slice(0, 150)}…
                            <span style={styles.scoreTag}>{((s.score || 0) * 100).toFixed(0)}%</span>
                          </div>
                        ))}
                      </details>
                    )}
                  </>
                )}
              </div>
              {msg.role === 'user' && (
                <div style={{ ...styles.avatar, background: 'linear-gradient(135deg,#4f46e5,#7c3aed)', border: '1px solid var(--accent-cyan)' }}>👤</div>
              )}
            </div>
          ))}

          {/* Follow-up chips */}
          {lastAiMsg && !sendingMsg && messages.length > 1 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', paddingLeft: 42, marginTop: -4 }}>
              {FOLLOW_UP_CHIPS.map(chip => (
                <button key={chip} style={styles.chipBtn} onClick={() => sendMessage(chip)}>
                  {chip}
                </button>
              ))}
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Input bar */}
        <div style={styles.inputBar}>
          {activeVideoIds.length === 0 && (
            <div style={styles.noVideoWarning}>
              ⚠️ No video selected — questions will search across ALL indexed videos
            </div>
          )}
          <div style={styles.inputRow}>
            <textarea
              style={styles.textarea}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              placeholder={
                activeVideoIds.length === 1
                  ? `Ask about "${activeVideos[0]?.filename}"… (Enter to send, Shift+Enter=newline)`
                  : 'Ask a question about your videos…'
              }
              rows={2}
              disabled={sendingMsg}
            />
            <button
              style={{
                ...styles.sendBtn,
                opacity: sendingMsg || !input.trim() ? 0.5 : 1,
                transform: sendingMsg ? 'scale(0.95)' : 'scale(1)',
              }}
              onClick={() => sendMessage()}
              disabled={sendingMsg || !input.trim()}
            >
              {sendingMsg ? (
                <div className="spinner" style={{ width: 18, height: 18 }} />
              ) : '➤'}
            </button>
          </div>
        </div>
      </main>

      <style>{`
        @keyframes dotBounce {
          0%, 100% { transform: translateY(0); opacity: 0.4; }
          50% { transform: translateY(-5px); opacity: 1; }
        }
      `}</style>
    </div>
  )
}

const dotStyle = (i: number): React.CSSProperties => ({
  display: 'inline-block',
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: 'var(--accent-cyan)',
  animation: `dotBounce 1.2s ease ${i * 0.2}s infinite`,
})

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  shell: {
    display: 'flex',
    height: 'calc(100vh - 58px)',
    overflow: 'hidden',
    background: 'var(--bg-deep)',
  },
  sidebar: {
    width: 280,
    minWidth: 280,
    background: 'var(--bg-panel)',
    borderRight: '1px solid var(--border-light)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  sidebarHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '20px 20px 12px',
    borderBottom: '1px solid var(--border-subtle)',
    gap: 6,
  },
  uploadBtn: {
    background: 'var(--gradient-neon)',
    color: '#000',
    border: 'none',
    borderRadius: 8,
    padding: '6px 14px',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    boxShadow: 'var(--shadow-neon)',
  },
  uploadStatus: {
    padding: '12px 20px',
    display: 'flex',
    flexDirection: 'column',
    background: 'rgba(0, 240, 255, 0.03)',
  },
  progressTrack: {
    height: 4,
    background: 'rgba(255, 255, 255, 0.1)',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: 'var(--gradient-neon)',
    borderRadius: 4,
    transition: 'width 0.3s ease',
  },
  dropZone: {
    margin: '12px 20px',
    border: '2px dashed var(--border-light)',
    borderRadius: 12,
    padding: '20px 0',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  videoList: {
    flex: 1,
    overflowY: 'auto',
    padding: '12px 20px',
  },
  videoItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '12px 14px',
    borderRadius: 10,
    border: '1px solid transparent',
    marginBottom: 8,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  videoName: {
    fontSize: 14,
    fontWeight: 600,
    color: 'var(--text-pure)',
    overflow: 'hidden',
    whiteSpace: 'nowrap',
    textOverflow: 'ellipsis',
  },
  videoMeta: {
    fontSize: 11,
    color: 'var(--text-muted)',
    marginTop: 4,
  },
  deleteBtn: {
    background: 'rgba(255, 0, 85, 0.1)',
    border: '1px solid rgba(255, 0, 85, 0.2)',
    color: 'var(--accent-pink)',
    cursor: 'pointer',
    fontSize: 12,
    padding: '4px 8px',
    borderRadius: 6,
    transition: 'all 0.15s',
    flexShrink: 0,
  },
  clearBtn: {
    background: 'rgba(255, 255, 255, 0.03)',
    border: '1px solid var(--border-light)',
    color: 'var(--text-pure)',
    borderRadius: 8,
    padding: '6px 14px',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    transition: 'all 0.15s',
  },
  chatArea: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    background: 'transparent',
  },
  chatHeader: {
    padding: '16px 24px',
    borderBottom: '1px solid var(--border-subtle)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 60,
    gap: 12,
    background: 'var(--bg-card)',
    backdropFilter: 'blur(10px)',
  },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: '30px 10% 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 40,
  },
  msgRow: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 16,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: '50%',
    background: 'var(--bg-panel)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 18,
    flexShrink: 0,
    border: '1px solid var(--border-light)',
    marginTop: 2,
  },
  bubble: {
    padding: '16px 20px',
    borderRadius: 20,
    border: '1px solid',
    fontSize: 15,
    lineHeight: 1.6,
    color: 'var(--text-pure)',
  },
  bubbleText: {
    wordBreak: 'break-word',
  },
  sources: {
    marginTop: 12,
    paddingTop: 12,
    borderTop: '1px solid var(--border-light)',
  },
  sourceItem: {
    fontSize: 12,
    color: 'var(--text-muted)',
    marginTop: 8,
    padding: '8px 12px',
    background: 'rgba(0, 0, 0, 0.3)',
    borderRadius: 8,
    borderLeft: '2px solid var(--accent-cyan)',
    lineHeight: 1.5,
  },
  scoreTag: {
    marginLeft: 6,
    background: 'rgba(0, 240, 255, 0.1)',
    color: 'var(--accent-cyan)',
    padding: '2px 6px',
    borderRadius: 4,
    fontSize: 10,
    fontWeight: 700,
  },
  inputBar: {
    padding: '10px 10% 30px',
    background: 'transparent',
  },
  noVideoWarning: {
    fontSize: 12,
    color: 'var(--accent-pink)',
    marginBottom: 12,
    padding: '8px 16px',
    background: 'rgba(255, 0, 85, 0.1)',
    borderRadius: 8,
    borderLeft: '3px solid var(--accent-pink)',
  },
  inputRow: {
    display: 'flex',
    gap: 12,
    alignItems: 'flex-end',
  },
  textarea: {
    flex: 1,
    background: 'rgba(255, 255, 255, 0.03)',
    border: '1px solid var(--border-light)',
    borderRadius: 16,
    color: 'var(--text-pure)',
    fontSize: 15,
    padding: '16px 60px 16px 20px',
    resize: 'none',
    outline: 'none',
    lineHeight: 1.5,
    fontFamily: 'inherit',
    transition: 'all 0.2s',
    backdropFilter: 'blur(10px)',
  },
  sendBtn: {
    background: 'var(--gradient-neon)',
    border: 'none',
    borderRadius: '50%',
    color: '#000',
    fontSize: 20,
    width: 50,
    height: 50,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.2s',
    flexShrink: 0,
    boxShadow: 'var(--shadow-neon)',
  },
  chipBtn: {
    background: 'rgba(0, 240, 255, 0.05)',
    border: '1px solid rgba(0, 240, 255, 0.2)',
    color: 'var(--accent-cyan)',
    borderRadius: 100,
    padding: '8px 16px',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.15s',
    whiteSpace: 'nowrap',
  },
  toutBanner: {
    position: 'relative',
    background: 'var(--bg-card)',
    border: '1px solid var(--border-light)',
    borderRadius: 'var(--radius-lg)',
    padding: '48px 40px',
    textAlign: 'center',
    overflow: 'hidden',
    boxShadow: 'var(--shadow-deep)',
    backdropFilter: 'blur(20px)',
  },
  toutGlow: {
    position: 'absolute',
    top: '-50%',
    left: '-20%',
    width: '140%',
    height: '200%',
    background: 'var(--gradient-glow)',
    pointerEvents: 'none',
    zIndex: -1,
  },
  badgeSuccess: {
    display: 'inline-block',
    background: 'rgba(0, 255, 136, 0.1)',
    color: '#00FF88',
    border: '1px solid rgba(0, 255, 136, 0.2)',
    padding: '4px 12px',
    borderRadius: '100px',
    fontSize: 12,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  uploadBtnLarge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    background: 'var(--gradient-neon)',
    color: '#000',
    border: 'none',
    borderRadius: 'var(--radius-pill)',
    padding: '14px 28px',
    fontSize: 15,
    fontWeight: 700,
    cursor: 'pointer',
    boxShadow: 'var(--shadow-neon)',
    transition: 'transform 0.2s, box-shadow 0.2s',
  },
}

