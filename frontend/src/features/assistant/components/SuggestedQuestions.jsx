import React from 'react';
import { useAuth } from '../../../context/AuthContext';

// Starter prompts shown on the empty chat screen. Super Admins see
// organization-wide prompts (each maps to an SA-only assistant tool); every
// other role keeps the learner-oriented defaults.
const DEFAULT_SUGGESTIONS = [
  'How am I performing overall?',
  'What should I study today?',
  'What sessions do I have coming up?',
  'How did I do on my last quiz?',
];

const SUPERADMIN_SUGGESTIONS = [
  'Give me a platform overview',
  'List all companies and their status',
  'Which batches are currently active?',
];

function suggestionsForRole(role) {
  return role === 'superadmin' ? SUPERADMIN_SUGGESTIONS : DEFAULT_SUGGESTIONS;
}

export default function SuggestedQuestions({ onPick, disabled }) {
  const { user } = useAuth();
  const suggestions = suggestionsForRole(user?.role?.toLowerCase());

  return (
    <div className="mt-4 flex w-full flex-col gap-1.5">
      {suggestions.map((q) => (
        <button
          key={q}
          type="button"
          disabled={disabled}
          onClick={() => onPick(q)}
          className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-left text-xs text-[var(--text-main)] transition hover:border-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] disabled:opacity-50"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
