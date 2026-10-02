import React, { useState, useEffect, useRef } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  MessageSquare, X, Send, Bot, Loader2, Sparkles,
  FolderPlus, Trash2, FileText, BarChart2
} from 'lucide-react';
import api from '../services/api';


const MediaChatbot = ({
  currentFolder,
  onFilterChange,
  onRefreshFiles,
  onFolderCreated
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [history, setHistory] = useState([
    {
      role: 'assistant',
      content: 'Hi! I am your Media Library AI assistant. Ask me to search, organize, tag, or delete files, create folders, or show storage insights!'
    }
  ]);
  const [loading, setLoading] = useState(false);
  const [localNotification, setLocalNotification] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (localNotification) {
      const timer = setTimeout(() => setLocalNotification(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [localNotification]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [history, isOpen]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!message.trim() || loading) return;

    const userMsg = message.trim();
    setMessage('');
    setHistory((prev) => [...prev, { role: 'user', content: userMsg }]);
    setLoading(true);

    try {
      const responseHistory = history.map((h) => ({ role: h.role, content: h.content }));
      
      const { data } = await api.post('/media/ai/chat', {
        message: userMsg,
        history: responseHistory,
        current_folder: currentFolder
      });

      setHistory((prev) => [...prev, { role: 'assistant', content: data.content }]);

      // Handle frontend actions suggested by AI Function calling
      if (data.action === 'FILTER' && data.action_data) {
        onFilterChange(data.action_data);
      } else if (data.action === 'CREATE_FOLDER' && data.action_data) {
        if (onFolderCreated) onFolderCreated(data.action_data);
      } else if (data.action === 'REFRESH_FILES') {
        if (onRefreshFiles) onRefreshFiles();
      } else if (data.action === 'DUPLICATES' && data.action_data) {
        setLocalNotification({ type: 'success', message: 'Potential duplicates found. Check the chat for details.' });
      }
    } catch (err) {
      setLocalNotification({ type: 'error', message: err.response?.data?.detail || 'Failed to send message' });
      setHistory((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error executing your command. Please try again.' }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const executeQuickCommand = (commandText) => {
    setMessage(commandText);
  };

  const isDraggingRef = useRef(false);

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
      className="fixed bottom-6 right-6 z-50 flex flex-col items-end cursor-grab active:cursor-grabbing select-none"
      style={{ touchAction: 'none' }}
    >
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            className="w-[350px] sm:w-[420px] h-[520px] bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl flex flex-col overflow-hidden mb-4"
          >
            {/* Header */}
            <div className="p-4 bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles size={18} className="text-amber-300 animate-pulse" />
                <span className="font-bold text-sm tracking-wide">Media AI Assistant</span>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 rounded-lg hover:bg-black/10 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {/* Local Notification Banner */}
            <AnimatePresence>
              {localNotification && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden"
                >
                  <div className={`px-4 py-2 text-[10px] font-semibold flex items-center justify-between ${
                    localNotification.type === 'error' ? 'bg-red-500/10 text-red-500' : 'bg-emerald-500/10 text-emerald-500'
                  }`}>
                    <span className="truncate pr-2">{localNotification.message}</span>
                    <button onClick={() => setLocalNotification(null)} className="hover:opacity-70">
                      <X size={12} />
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Chat Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {history.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex gap-2.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {msg.role !== 'user' && (
                    <div className="p-1.5 rounded-lg bg-[var(--input-bg)] text-[var(--text-main)] h-fit">
                      <Bot size={16} />
                    </div>
                  )}
                  <div
                    className={`max-w-[75%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed ${
                      msg.role === 'user'
                        ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] rounded-tr-none'
                        : 'bg-[var(--input-bg)] text-[var(--text-main)] rounded-tl-none border border-[var(--border)]'
                    }`}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex gap-2.5 justify-start">
                  <div className="p-1.5 rounded-lg bg-[var(--input-bg)] text-[var(--text-main)] h-fit">
                    <Bot size={16} />
                  </div>
                  <div className="bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)] rounded-2xl rounded-tl-none px-3.5 py-2.5 text-xs flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" /> Thinking...
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Suggested / Quick Commands */}
            <div className="px-4 py-2 border-t border-[var(--border)] bg-[var(--input-bg)] flex gap-2 overflow-x-auto whitespace-nowrap scrollbar-none">
              <button
                onClick={() => executeQuickCommand('Show storage insights')}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-[var(--border)] text-[10px] font-semibold text-[var(--text-main)] bg-[var(--bg-card)] hover:border-[var(--sidebar-active-bg)] transition-colors"
              >
                <BarChart2 size={10} /> Insights
              </button>
              <button
                onClick={() => executeQuickCommand('Find duplicate files')}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-[var(--border)] text-[10px] font-semibold text-[var(--text-main)] bg-[var(--bg-card)] hover:border-[var(--sidebar-active-bg)] transition-colors"
              >
                <Trash2 size={10} /> Find Duplicates
              </button>
              <button
                onClick={() => executeQuickCommand('Move all PDFs to Documents folder')}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-[var(--border)] text-[10px] font-semibold text-[var(--text-main)] bg-[var(--bg-card)] hover:border-[var(--sidebar-active-bg)] transition-colors"
              >
                <FolderPlus size={10} /> Organize PDFs
              </button>
              <button
                onClick={() => executeQuickCommand('Show latest uploaded videos')}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-[var(--border)] text-[10px] font-semibold text-[var(--text-main)] bg-[var(--bg-card)] hover:border-[var(--sidebar-active-bg)] transition-colors"
              >
                <FileText size={10} /> Recent Videos
              </button>
            </div>

            {/* Input Form */}
            <form onSubmit={handleSend} className="p-3 border-t border-[var(--border)] flex gap-2">
              <input
                type="text"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Ask AI to search, move, tag or delete files..."
                className="flex-1 px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-xs text-[var(--text-main)] focus:outline-none focus:ring-1 focus:ring-[var(--sidebar-active-bg)]"
              />
              <button
                type="submit"
                disabled={!message.trim() || loading}
                className="p-2 rounded-xl bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                <Send size={14} />
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Floating Button */}
      <button
        onClick={() => {
          if (!isDraggingRef.current) {
            setIsOpen(!isOpen);
          }
        }}
        title={isOpen ? 'Close assistant (Drag to move)' : 'Media AI Assistant (Drag to move)'}
        className="h-14 w-14 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-[0_4px_20px_rgba(99,102,241,0.4)] hover:shadow-[0_6px_25px_rgba(99,102,241,0.6)] hover:scale-105 active:scale-95 transition-all duration-300 flex items-center justify-center relative overflow-hidden group border-2 border-white/20"
      >
        <div className="absolute inset-0 bg-white/20 scale-0 group-hover:scale-150 transition-transform duration-500 rounded-full" />
        <Sparkles size={22} className="absolute inset-0 m-auto text-amber-200 opacity-0 group-hover:opacity-100 group-hover:rotate-12 transition-all duration-300" />
        <Bot size={24} className="group-hover:opacity-0 group-hover:-translate-y-2 transition-all duration-300 relative z-10" />
      </button>
    </motion.div>
  );
};

export default MediaChatbot;
