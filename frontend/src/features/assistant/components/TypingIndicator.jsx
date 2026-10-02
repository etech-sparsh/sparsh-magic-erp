import React from 'react';
import { Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';

/**
 * Shown while the assistant is processing. When a tool is running, surfaces its
 * name so the user sees real activity ("Looking up your sessions…").
 */
const TOOL_LABELS = {
  get_my_profile: 'Reading your profile',
  get_my_sessions: 'Looking up your sessions',
  get_latest_quiz_result: 'Fetching your latest quiz',
  analyze_student_performance: 'Analyzing your performance',
  get_subject_wise_scores: 'Crunching subject scores',
  get_learning_progress: 'Checking your progress',
  recommend_study_plan: 'Building your study plan',
  search_knowledge: 'Searching the knowledge base',
};

export default function TypingIndicator({ activeTool }) {
  const label = activeTool ? TOOL_LABELS[activeTool] || 'Working' : null;

  return (
    <div className="flex items-center gap-2 px-1 py-1 text-[var(--text-muted)]">
      {label ? (
        <>
          <Loader2 size={14} className="animate-spin" />
          <span className="text-xs">{label}…</span>
        </>
      ) : (
        <div className="flex items-center gap-1">
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className="h-1.5 w-1.5 rounded-full bg-[var(--text-muted)]"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1, repeat: Infinity, delay: i * 0.18 }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
