import React, { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';
import SuggestedQuestions from './SuggestedQuestions';

export default function MessageList({ messages, streaming, activeTool, onPickSuggestion, onEdit, onDownloadPdf }) {
  const endRef = useRef(null);
  const { user } = useAuth();
  const isSuperAdmin = user?.role?.toLowerCase() === 'superadmin';

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, activeTool]);

  // Whether the last assistant message is still empty (so show a typing row).
  const last = messages[messages.length - 1];
  const showTyping = streaming && last && last.role === 'assistant' && !last.content;

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-5 py-6 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
          <Sparkles size={22} />
        </div>
        <p className="mt-2 text-sm font-medium text-[var(--text-main)]">Ask Sparsh anything</p>
        <p className="text-xs text-[var(--text-muted)]">
          {isSuperAdmin
            ? 'Platform stats, companies, batches, and users.'
            : 'Your sessions, quiz scores, progress, or what to study next.'}
        </p>
        <SuggestedQuestions onPick={onPickSuggestion} disabled={streaming} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 px-3 py-3">
      {messages.map((m) => (
        <MessageBubble key={m.id} message={m} onEdit={onEdit} onDownloadPdf={onDownloadPdf} disabled={streaming} />
      ))}
      {showTyping && (
        <div className="pl-9">
          <TypingIndicator activeTool={activeTool} />
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
