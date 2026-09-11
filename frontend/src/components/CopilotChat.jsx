/**
 * AIVOA Copilot — the conversational panel.
 *
 * The operator never types into the form directly; they talk to the copilot
 * and it fills the form. So this panel is the primary input surface, and the
 * form on the left is the reviewable result.
 */
import { useEffect, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'

import {
  addUserMessage,
  fetchGreeting,
  selectChatDegraded,
  selectIsThinking,
  selectMessages,
  sendFile,
  sendMessage,
} from '../features/chat/chatSlice'
import { selectAiHealth } from '../features/meta/metaSlice'
import { formatBytes } from '../utils/format'

const ACCEPT = '.pdf,.eml,.txt,.md,.png,.jpg,.jpeg,.webp'

function FlaskIcon() {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" fill="none" aria-hidden="true">
      <path
        d="M9 3h6M10 3v6.2L5.2 17A2 2 0 0 0 6.9 20h10.2a2 2 0 0 0 1.7-3L14 9.2V3"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M7.5 14h9" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  )
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
      <path
        d="M13 2 4.5 13H11l-1 9 8.5-11H12l1-9Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
      <path
        d="m5 12.5 4.5 4.5L19 7"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
      <circle cx="12" cy="8" r="3.4" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M4.8 20a7.2 7.2 0 0 1 14.4 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

function ClipIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" aria-hidden="true">
      <path
        d="M20 11.5 12.3 19a4.6 4.6 0 0 1-6.5-6.5l7.7-7.6a3 3 0 0 1 4.3 4.3l-7.7 7.6a1.4 1.4 0 0 1-2-2l7.1-7"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
      <path
        d="m5 12.5 4.5 4.5L19 7"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function Message({ message }) {
  if (message.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">
          {message.attachment && (
            <div className="msg-attachment">
              <ClipIcon />
              <span>{message.attachment.name}</span>
              <span className="msg-attachment-size">
                {formatBytes(message.attachment.size)}
              </span>
            </div>
          )}
          {message.content}
        </div>
        <div className="msg-avatar msg-avatar-user">
          <UserIcon />
        </div>
      </div>
    )
  }

  const tone = message.isError
    ? 'is-error'
    : message.toolCalled
      ? 'is-tool'
      : message.isGreeting
        ? 'is-greeting'
        : ''

  return (
    <div className="msg msg-assistant">
      <div className={`msg-avatar msg-avatar-ai ${tone}`}>
        {message.toolCalled ? <CheckIcon /> : <SparkIcon />}
      </div>
      <div className="msg-bubble">
        {message.content}
        {message.toolCalled && (
          <div className="msg-meta">
            <span className="tool-chip">
              <SparkIcon /> {message.toolCalled}
            </span>
            {message.degraded && <span className="tool-chip is-warn">rule-based</span>}
            {message.latencyMs != null && (
              <span className="msg-latency">{(message.latencyMs / 1000).toFixed(1)}s</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function CopilotChat() {
  const dispatch = useDispatch()
  const messages = useSelector(selectMessages)
  const isThinking = useSelector(selectIsThinking)
  const degraded = useSelector(selectChatDegraded)
  const aiHealth = useSelector(selectAiHealth)

  const [draft, setDraft] = useState('')
  const [isOver, setIsOver] = useState(false)
  const fileRef = useRef(null)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    dispatch(fetchGreeting())
  }, [dispatch])

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, isThinking])

  const submit = () => {
    const text = draft.trim()
    if (!text || isThinking) return
    dispatch(addUserMessage({ text }))
    dispatch(sendMessage(text))
    setDraft('')
  }

  const submitFile = (file) => {
    if (!file || isThinking) return
    dispatch(
      addUserMessage({
        text: `Uploaded ${file.name} for processing.`,
        attachment: { name: file.name, size: file.size },
      }),
    )
    dispatch(sendFile(file))
  }

  const onKeyDown = (event) => {
    // Enter sends; Shift+Enter makes a new line, as in any chat client.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const healthy = aiHealth?.models_available !== false

  return (
    <section
      className={`copilot-chat${isOver ? ' is-dropping' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setIsOver(true)
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setIsOver(false)
        submitFile(event.dataTransfer.files?.[0])
      }}
    >
      <header className="chat-head">
        <span className="chat-head-icon">
          <FlaskIcon />
        </span>
        <div className="chat-head-text">
          <h2>AIVOA Copilot</h2>
          <p>Drop complaint files or paste text below.</p>
        </div>
        <span
          className={`chat-status-dot${isThinking ? ' is-busy' : ''}${
            healthy ? '' : ' is-down'
          }`}
          title={aiHealth?.message ?? ''}
        />
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((message) => (
          <Message key={message.id} message={message} />
        ))}

        {isThinking && (
          <div className="msg msg-assistant">
            <div className="msg-avatar msg-avatar-ai">
              <SparkIcon />
            </div>
            <div className="msg-bubble is-thinking">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}

        {isOver && (
          <div className="chat-drop-hint">Release to send this file to the copilot</div>
        )}
      </div>

      {degraded && (
        <div className="chat-degraded">
          Running on deterministic rules — the language model is unavailable, so
          results are labelled rule-based.
        </div>
      )}

      <div className="chat-input-row">
        <div className="chat-input">
          <button
            className="chat-attach"
            onClick={() => fileRef.current?.click()}
            disabled={isThinking}
            title="Attach a PDF or email"
            type="button"
          >
            <ClipIcon />
          </button>
          <textarea
            ref={inputRef}
            rows={1}
            value={draft}
            placeholder="Type a message or paste a complaint..."
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            disabled={isThinking}
          />
          <button
            className="chat-send"
            onClick={submit}
            disabled={isThinking || !draft.trim()}
            title="Send"
            type="button"
          >
            <SendIcon />
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(event) => {
              submitFile(event.target.files?.[0])
              event.target.value = ''
            }}
          />
        </div>
        <div className="chat-foot">Powered by LangGraph</div>
      </div>
    </section>
  )
}
