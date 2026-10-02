import React, { useRef, useState } from 'react';
import { Send, Square, Mic, Paperclip } from 'lucide-react';
import useSpeechRecognition from '../hooks/useSpeechRecognition';
import AttachmentPreview from './AttachmentPreview';

export default function ChatInput({
  onSend,
  onCancel,
  streaming,
  disabled,
  // Attachment wiring (optional — chat works text-only without these).
  attachmentItems = [],
  onAddFiles,
  onRemoveAttachment,
  onRetryAttachment,
}) {
  const [value, setValue] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  // Text already committed before the current dictation began.
  const baseRef = useRef('');

  const attachmentsEnabled = typeof onAddFiles === 'function';
  const hasPending = attachmentItems.some(
    (it) => it.status === 'uploading' || it.status === 'processing',
  );
  const hasReady = attachmentItems.some((it) => it.status === 'completed');

  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  };

  const { supported: micSupported, listening, toggle: toggleMic } = useSpeechRecognition({
    onResult: ({ finalText, interimText }) => {
      const base = baseRef.current;
      if (finalText) {
        baseRef.current = `${base}${finalText} `;
      }
      const spoken = finalText || interimText;
      const next = `${base}${spoken}${finalText ? ' ' : ''}`;
      setValue(next);
      requestAnimationFrame(resize);
    },
  });

  const handleMic = () => {
    if (!listening) baseRef.current = value ? `${value} ` : '';
    toggleMic();
  };

  // Can submit if there's text or at least one ready attachment, and nothing is
  // still uploading/processing.
  const canSubmit = (value.trim() || hasReady) && !hasPending && !streaming && !disabled;

  const submit = () => {
    if (!canSubmit) return;
    if (listening) toggleMic();
    onSend(value.trim());
    setValue('');
    baseRef.current = '';
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const autoGrow = (e) => {
    setValue(e.target.value);
    // Keep the dictation base in sync with manual edits.
    baseRef.current = e.target.value ? `${e.target.value} ` : '';
    resize();
  };

  const pickFiles = () => fileInputRef.current?.click();

  const onFilesPicked = (e) => {
    if (e.target.files?.length) onAddFiles(e.target.files);
    e.target.value = ''; // allow re-selecting the same file
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (!attachmentsEnabled) return;
    if (e.dataTransfer?.files?.length) onAddFiles(e.dataTransfer.files);
  };

  const onDragOver = (e) => {
    if (!attachmentsEnabled) return;
    e.preventDefault();
    if (!dragOver) setDragOver(true);
  };

  const onDragLeave = (e) => {
    if (e.currentTarget.contains(e.relatedTarget)) return;
    setDragOver(false);
  };

  return (
    <div
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      className={`relative border-t bg-[var(--bg-card)] ${
        dragOver ? 'border-[var(--accent-indigo)]' : 'border-[var(--border)]'
      }`}
    >
      {dragOver && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-b-2xl border-2 border-dashed border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]/60 text-sm font-medium text-[var(--accent-indigo)]">
          Drop files to attach
        </div>
      )}

      {attachmentsEnabled && (
        <AttachmentPreview
          items={attachmentItems}
          onRemove={onRemoveAttachment}
          onRetry={(lid) => onRetryAttachment?.(lid)}
        />
      )}

      <div className="flex items-end gap-2 p-2.5">
        {attachmentsEnabled && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={onFilesPicked}
            />
            <button
              type="button"
              onClick={pickFiles}
              disabled={disabled || streaming}
              title="Attach files"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-40"
            >
              <Paperclip size={15} />
            </button>
          </>
        )}

        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={autoGrow}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={listening ? 'Listening… speak now' : 'Ask about your sessions, scores, progress…'}
          className="max-h-[120px] flex-1 resize-none rounded-xl border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text-main)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-indigo)] disabled:opacity-60"
        />
        {micSupported && (
          <button
            type="button"
            onClick={handleMic}
            disabled={disabled || streaming}
            title={listening ? 'Stop voice input' : 'Speak'}
            className={
              listening
                ? 'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-red,#ef4444)] text-white animate-pulse'
                : 'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-40'
            }
          >
            <Mic size={15} />
          </button>
        )}
        {streaming ? (
          <button
            type="button"
            onClick={onCancel}
            title="Stop"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--bg-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] border border-[var(--border)]"
          >
            <Square size={15} />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            title={hasPending ? 'Waiting for uploads…' : 'Send'}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo)] text-white transition hover:opacity-90 disabled:opacity-40"
          >
            <Send size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
