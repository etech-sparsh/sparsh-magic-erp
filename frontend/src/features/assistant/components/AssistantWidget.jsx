import React, { useState, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { MessageCircle, X } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import ChatWindow from './ChatWindow';

/**
 * Global floating assistant. Mounted once in App.jsx; renders nothing when the
 * user is logged out, so it appears on every authenticated page but not /login.
 * Supports free-flow drag & drop positioning anywhere on screen.
 */
export default function AssistantWidget() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const isDraggingRef = useRef(false);

  if (!user) return null;

  return (
    <motion.div
      drag
      dragMomentum={false}
      dragElastic={0.05}
      onDragStart={() => {
        isDraggingRef.current = true;
      }}
      onDragEnd={() => {
        setTimeout(() => {
          isDraggingRef.current = false;
        }, 150);
      }}
      className="fixed bottom-6 right-6 z-[9999] flex flex-col items-end gap-3 cursor-grab active:cursor-grabbing select-none"
      style={{ touchAction: 'none' }}
    >
      <AnimatePresence>
        {open && (
          <motion.div
            key="assistant-panel"
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className={
              expanded
                ? 'h-[calc(100vh-8rem)] w-[min(900px,calc(100vw-2rem))] shadow-2xl rounded-2xl overflow-hidden'
                : 'h-[min(620px,calc(100vh-8rem))] w-[min(400px,calc(100vw-2rem))] shadow-2xl rounded-2xl overflow-hidden'
            }
          >
            <ChatWindow
              onClose={() => setOpen(false)}
              expanded={expanded}
              onToggleExpand={() => setExpanded((e) => !e)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        type="button"
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.92 }}
        onClick={() => {
          if (!isDraggingRef.current) {
            setOpen((o) => !o);
          }
        }}
        title={open ? 'Close assistant (Drag to move)' : 'Ask Sparsh (Drag to move)'}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--accent-indigo)] text-white shadow-2xl hover:opacity-90 relative border-2 border-white/20"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={open ? 'close' : 'open'}
            initial={{ rotate: -90, opacity: 0 }}
            animate={{ rotate: 0, opacity: 1 }}
            exit={{ rotate: 90, opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            {open ? <X size={22} /> : <MessageCircle size={22} />}
          </motion.span>
        </AnimatePresence>
      </motion.button>
    </motion.div>
  );
}
