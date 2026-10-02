import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
    Send, Sparkles, Bot, User, ArrowLeft, 
    MessageSquare, RefreshCcw, HelpCircle, 
    Command, Database, ShieldCheck, Plus, ChevronLeft,
    Search, MoreVertical, Trash2, Edit, MessageCircle,
    Terminal, Zap, Info, X, FileText, Image as ImageIcon
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
const GptChat = () => {
    const { id, sessionId } = useParams();
    const navigate = useNavigate();
    useAuth();
    const { showSuccess, showError } = useNotification();
    
    const [sessions, setSessions] = useState([]);
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [sidebarLoading, setSidebarLoading] = useState(true);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [search, setSearch] = useState('');
    const [editingIdx, setEditingIdx] = useState(null);
    const [editInput, setEditInput] = useState('');
    const [uploading, setUploading] = useState(false);
    const [attachments, setAttachments] = useState([]);
    const scrollRef = useRef(null);
    const abortControllerRef = useRef(null);
    const fileInputRef = useRef(null);
    const textareaRef = useRef(null);

    // ... existing fetch functions ...
    const fetchProjectDetails = async () => {
        try {
            const res = await api.get(`/gpt/projects/${id}`);
            setProject(res.data);
        } catch (err) {
            console.error("Fetch project details error:", err);
        }
    };

    const fetchSessions = async () => {
        try {
            setSidebarLoading(true);
            const res = await api.get(`/gpt/chat/${id}/sessions`);
            setSessions(res.data);
        } catch (err) {
            console.error("Sidebar sessions fetch error:", err);
        } finally {
            setSidebarLoading(false);
        }
    };

    const fetchSessionHistory = async () => {
        if (!sessionId) {
            setMessages([]);
            setAttachments([]);
            setLoading(false);
            return;
        }
        try {
            setLoading(true);
            const res = await api.get(`/gpt/chat/sessions/${sessionId}/history`);
            setMessages(res.data.messages || []);
            setAttachments(res.data.attachments || []);
        } catch (err) {
            console.error("Session history fetch error:", err);
            setMessages([]);
            setAttachments([]);
        } finally {
            setLoading(false);
        }
    };

    const fetchAttachments = async (sId = sessionId) => {
        if (!sId) return;
        try {
            const res = await api.get(`/gpt/chat/sessions/${sId}/attachments`);
            setAttachments(res.data.attachments || []);
        } catch (err) {
            console.error("Attachments fetch error:", err);
        }
    };

    const handleRemoveAttachment = async (name) => {
        try {
            await api.delete(`/gpt/chat/sessions/${sessionId}/attachments`, { params: { name } });
            setAttachments(prev => prev.filter(a => a.name !== name));
            showSuccess(`Removed ${name}`);
        } catch (err) {
            showError("Couldn't remove file");
        }
    };

    const handleDeleteSession = async (sId, e) => {
        e.stopPropagation();
        try {
            await api.delete(`/gpt/chat/sessions/${sId}`);
            if (sessionId === sId) navigate(`/gpt/chat/${id}`);
            showSuccess("Chat history deleted");
            fetchSessions();
        } catch (err) {
            showError("Delete failed");
        }
    };

    const handleStopGeneration = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            setSending(false);
            // Optionally add a note to the chat that it was stopped
        }
    };

    const handleFileUpload = async (e) => {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;

        // Mirror handleSend: create a session on the fly, so attaching a file
        // FIRST in a fresh chat works instead of silently doing nothing.
        let currentSessionId = sessionId;
        if (!currentSessionId) {
            try {
                const res = await api.post(`/gpt/chat/${id}/session`);
                currentSessionId = res.data.id;
            } catch (err) {
                showError("Couldn't start a chat session for the upload");
                return;
            }
        }

        setUploading(true);
        const succeeded = [];
        const failed = [];

        // Upload each file independently so one bad file doesn't block the rest.
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            try {
                await api.post(`/gpt/chat/sessions/${currentSessionId}/upload`, formData);
                succeeded.push(file.name);
                if (sessionId) {
                    const sysMsg = { role: 'assistant', content: `📎 Knowledge indexed: **${file.name}** is now available in this session.`, timestamp: new Date(), system: true };
                    setMessages(prev => [...prev, sysMsg]);
                }
            } catch (err) {
                console.error(`Upload failed for ${file.name}`, err);
                failed.push(file.name);
            }
        }

        setUploading(false);
        // Reset the input so re-selecting the same file(s) fires onChange again.
        if (fileInputRef.current) fileInputRef.current.value = '';

        if (succeeded.length) {
            showSuccess(succeeded.length === 1
                ? "File indexed successfully"
                : `${succeeded.length} files indexed successfully`);
        }
        if (failed.length) {
            showError(`Failed to index: ${failed.join(', ')}`);
        }

        // Refresh the attached-files preview for the active session.
        if (succeeded.length) fetchAttachments(currentSessionId);

        // Fresh chat: enter the session we just created so the uploads are used.
        if (!sessionId && succeeded.length) {
            navigate(`/gpt/chat/${id}/${currentSessionId}`);
            fetchSessions();
        }
    };

    const handleRethink = async (index, content) => {
        if (!sessionId || sending) return;
        setSending(true);
        setEditingIdx(null);
        
        try {
            const res = await api.patch(`/gpt/chat/sessions/${sessionId}/rethink`, { index, content });
            setMessages(res.data.messages);
        } catch (err) {
            console.error(err);
        } finally {
            setSending(false);
        }
    };

    useEffect(() => {
        if (id) {
            fetchProjectDetails();
            fetchSessions();
        }
    }, [id]);

    useEffect(() => {
        if (sessionId) {
            fetchSessionHistory();
        } else {
            setMessages([]);
            setLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
            if (textareaRef.current.scrollHeight > 200) {
                textareaRef.current.style.overflowY = 'auto';
            } else {
                textareaRef.current.style.overflowY = 'hidden';
            }
        }
    }, [input]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, sending]);

    const handleNewChat = async () => {
        try {
            const res = await api.post(`/gpt/chat/${id}/session`);
            navigate(`/gpt/chat/${id}/${res.data.id}`);
            fetchSessions(); 
        } catch (err) {
            console.error("New chat creation failed:", err);
        }
    };

    const handleSend = async (msgOverride) => {
        const message = msgOverride || input;
        if (!message.trim() || sending || !id) return;

        let currentSessionId = sessionId;
        if (!currentSessionId) {
            try {
                const res = await api.post(`/gpt/chat/${id}/session`);
                currentSessionId = res.data.id;
            } catch (err) {
                console.error(err);
                return;
            }
        }

        const userMsg = { role: 'user', content: message, timestamp: new Date() };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setSending(true);

        const controller = new AbortController();
        abortControllerRef.current = controller;

        try {
            const res = await api.post(`/gpt/chat/sessions/${currentSessionId}/respond`, { message }, {
                signal: controller.signal
            });
            const aiMsg = { role: 'assistant', content: res.data.answer, timestamp: new Date() };
            setMessages(prev => [...prev, aiMsg]);
            
            if (!sessionId) {
                navigate(`/gpt/chat/${id}/${currentSessionId}`, { replace: true });
                fetchSessions();
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                console.log("Chat generation stopped by user.");
            } else {
                console.error(err);
                const errAiMsg = { role: 'assistant', content: "I'm sorry, I encountered a temporary issue. Please check your connection.", error: true };
                setMessages(prev => [...prev, errAiMsg]);
            }
        } finally {
            setSending(false);
            abortControllerRef.current = null;
        }
    };

    const filteredSessions = sessions.filter(s => 
        s.title.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="fixed inset-0 top-[72px] left-[72px] flex bg-[var(--bg-main)] overflow-hidden">
            <input
                type="file"
                ref={fileInputRef}
                className="hidden"
                onChange={handleFileUpload}
                multiple
            />
            
            {/* 1. Left Sidebar: Support Engine Chats */}
            <div className="w-[320px] h-full bg-[var(--bg-card)] border-r border-[var(--border)] flex flex-col shrink-0">
                {/* Sidebar Header */}
                <div className="p-4 flex items-center justify-between border-b border-[var(--border)]">
                    <div className="flex items-center gap-3">
                        <button onClick={() => navigate('/gpt')} className="p-2 hover:bg-[var(--input-bg)] rounded-xl transition-all">
                             <ChevronLeft size={18} className="text-[var(--text-muted)]" />
                        </button>
                        <h2 className="text-sm font-black text-[var(--text-main)] tracking-tight uppercase italic">{project?.title || "Support Engine"}</h2>
                    </div>
                </div>

                {/* New Chat Button */}
                <div className="p-4">
                    <button 
                        onClick={handleNewChat}
                        className="w-full h-11 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white rounded-2xl flex items-center justify-center gap-2 font-black text-[11px] uppercase tracking-widest transition-all active:scale-95 shadow-sm"
                    >
                        <Plus size={16} /> New Chat
                    </button>
                </div>

                {/* Search Sidebar */}
                <div className="px-4 pb-2">
                    <div className="relative group">
                        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent-indigo)] transition-colors" />
                        <input 
                            type="text"
                            placeholder="Search chats..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            className="w-full h-9 pl-9 pr-4 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[11px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-all placeholder:text-[var(--text-muted)]/50"
                        />
                    </div>
                </div>

                {/* Session List */}
                <div className="flex-1 overflow-y-auto no-scrollbar p-2 space-y-1">
                    {sidebarLoading ? (
                        [1,2,3,4,5].map(i => (
                            <div key={i} className="h-12 w-full bg-[var(--input-bg)] animate-pulse rounded-xl" />
                        ))
                    ) : filteredSessions.length > 0 ? (
                        filteredSessions.map(s => (
                            <div key={s.id} className="relative group">
                                <button
                                    onClick={() => navigate(`/gpt/chat/${id}/${s.id}`)}
                                    className={`w-full flex items-center gap-3 p-3 rounded-xl transition-all ${sessionId === s.id ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'hover:bg-[var(--input-bg)] text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                                >
                                    <MessageSquare size={16} className={sessionId === s.id ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] group-hover:text-[var(--text-main)]'} />
                                    <span className="text-[13px] font-bold truncate text-left flex-1">{s.title}</span>
                                    {sessionId === s.id && <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-indigo)] shadow-[0_0_8px_var(--accent-indigo)]" />}
                                </button>
                                <button 
                                    onClick={(e) => handleDeleteSession(s.id, e)}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 opacity-0 group-hover:opacity-100 hover:text-red-500 transition-all"
                                >
                                    <Trash2 size={12} />
                                </button>
                            </div>
                        ))
                    ) : (
                        <div className="p-4 text-center text-[10px] uppercase font-black tracking-widest text-[var(--text-muted)] opacity-50">
                             No Chats Found
                        </div>
                    )}
                </div>

                {/* Sidebar Bottom: Bot Info */}
                <div className="p-4 border-t border-[var(--border)]">
                    <div className="p-3 bg-[var(--input-bg)] rounded-2xl flex items-center justify-between border border-[var(--border)]">
                        <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-[var(--accent-indigo)] text-white flex items-center justify-center font-black text-[10px]">
                                {project?.title?.charAt(0) || 'S'}
                            </div>
                            <div className="flex flex-col">
                                <span className="text-[11px] font-black text-[var(--text-main)] truncate max-w-[120px]">{project?.title || 'Support Admin'}</span>
                                <span className="text-[9px] font-black text-[var(--accent-green)] uppercase tracking-widest">Open</span>
                            </div>
                        </div>
                        <div className="flex items-center gap-1">
                             <div className="w-2 h-2 rounded-full bg-[var(--accent-green)] animate-pulse"></div>
                        </div>
                    </div>
                </div>
            </div>

            {/* 2. Main Chat Area */}
            <div className="flex-1 flex flex-col relative bg-[var(--bg-main)]">
                
                {id && project ? (
                    <>
                        {/* Message List */}
                        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-6 no-scrollbar scroll-smooth">
                            {messages.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-2xl mx-auto">
                                    <motion.div 
                                        initial={{ scale: 0.8, opacity: 0 }}
                                        animate={{ scale: 1, opacity: 1 }}
                                        className="w-20 h-20 rounded-[32px] bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100 flex items-center justify-center shadow-xl text-[var(--accent-indigo)]"
                                    >
                                        <Bot size={40} />
                                    </motion.div>
                                    <div className="space-y-1">
                                        <h2 className="text-2xl font-black text-[var(--text-main)] tracking-tighter uppercase italic">{project.title}</h2>
                                        <div className="flex justify-center pt-1 pb-3">
                                             <span className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 text-emerald-600 border border-emerald-100 rounded-full text-[10px] font-black uppercase tracking-widest leading-none shadow-sm shadow-emerald-50">
                                                 <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> Sparsh AI Online
                                             </span>
                                        </div>
                                        <p className="text-[12px] font-bold text-[var(--text-muted)] max-w-md mx-auto leading-relaxed uppercase tracking-wider opacity-60">
                                            {project.description || "I'm your specialized AI agent, ready to assist with deep insights from your data."}
                                        </p>
                                    </div>
                                    
                                    <div className="flex flex-wrap items-center justify-center gap-3 pt-6">
                                        {project.conversation_starters?.map((starter, i) => (
                                            <button 
                                                key={i} 
                                                onClick={() => handleSend(starter)}
                                                className="px-4 py-2.5 bg-white border border-[var(--border)] rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-all active:scale-95 shadow-sm"
                                            >
                                                {starter}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            ) : (
                                <div className="max-w-4xl mx-auto space-y-6">
                                    {messages.map((m, idx) => (
                                        <motion.div 
                                            key={idx}
                                            initial={{ opacity: 0, y: 10 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            className={`flex items-start gap-4 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}
                                        >
                                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 shadow-sm ${m.role === 'user' ? 'bg-[var(--accent-indigo)] text-white' : 'bg-white border border-[var(--border)] text-[var(--accent-indigo)]'}`}>
                                                {m.role === 'user' ? <User size={14} /> : <Bot size={14} />}
                                            </div>
                                            <div className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'} max-w-[85%] group/msg ${editingIdx === idx ? 'w-full' : ''}`}>
                                                {editingIdx === idx ? (
                                                    <div className="w-full min-w-[300px] md:min-w-[600px] max-w-full space-y-2">
                                                        <textarea 
                                                            value={editInput}
                                                            onChange={e => {
                                                                setEditInput(e.target.value);
                                                                e.target.style.height = 'auto';
                                                                e.target.style.height = `${Math.min(e.target.scrollHeight, 400)}px`;
                                                            }}
                                                            ref={(el) => {
                                                                if (el && !el.dataset.initialized) {
                                                                    el.style.height = 'auto';
                                                                    el.style.height = `${Math.min(el.scrollHeight, 400)}px`;
                                                                    el.dataset.initialized = 'true';
                                                                }
                                                            }}
                                                            className="w-full bg-[var(--input-bg)] border border-[var(--accent-indigo)] rounded-2xl p-4 text-[13px] font-bold text-[var(--text-main)] outline-none resize-none no-scrollbar leading-relaxed focus:ring-4 focus:ring-[var(--accent-indigo-bg)] transition-shadow"
                                                            style={{ minHeight: '60px' }}
                                                        />
                                                        <div className="flex gap-2 justify-end">
                                                            <button onClick={() => setEditingIdx(null)} className="px-3 py-1.5 text-[10px] font-black uppercase text-[var(--text-muted)]">Cancel</button>
                                                            <button onClick={() => handleRethink(idx, editInput)} className="px-4 py-1.5 bg-[var(--accent-indigo)] text-white text-[10px] font-black uppercase rounded-lg">Update & Rethink</button>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className={`relative p-4 rounded-2xl text-[13px] leading-relaxed font-bold shadow-sm transition-all ${m.role === 'user' ? 'bg-[var(--accent-indigo)] text-white' : m.system ? 'bg-amber-50/50 border border-amber-100 text-amber-700 italic' : 'bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)]'}`}>
                                                        {m.role === 'assistant' && !m.system ? (
                                                            <div className="prose prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-[var(--bg-main)] prose-pre:border-none prose-a:text-[var(--accent-indigo)] prose-strong:text-[var(--text-main)] overflow-x-auto">
                                                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                                    {m.content}
                                                                </ReactMarkdown>
                                                            </div>
                                                        ) : (
                                                            <div className="whitespace-pre-wrap">{m.content}</div>
                                                        )}
                                                        {m.role === 'user' && !sending && (
                                                            <button 
                                                                onClick={() => { setEditingIdx(idx); setEditInput(m.content); }}
                                                                className="absolute -left-10 top-1/2 -translate-y-1/2 p-2 opacity-0 group-hover/msg:opacity-100 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all"
                                                            >
                                                                <Edit size={14} />
                                                            </button>
                                                        )}
                                                    </div>
                                                )}
                                                <span className="text-[8px] font-black uppercase text-[var(--text-muted)] tracking-[0.2em] mt-2 opacity-60">
                                                    {m.role === 'user' ? 'Author' : m.system ? 'System Log' : `${project.title} Engine`}
                                                </span>
                                            </div>
                                        </motion.div>
                                    ))}
                                    {sending && (
                                        <div className="flex items-start gap-4">
                                            <div className="w-8 h-8 rounded-lg bg-white border border-[var(--border)] text-[var(--accent-indigo)] flex items-center justify-center animate-pulse">
                                                <Bot size={14} />
                                            </div>
                                            <div className="flex flex-col gap-3">
                                                 <div className="flex gap-1.5 mt-3">
                                                    <div className="w-1.5 h-1.5 bg-[var(--accent-indigo)] rounded-full animate-bounce duration-700"></div>
                                                    <div className="w-1.5 h-1.5 bg-[var(--accent-indigo)] rounded-full animate-bounce duration-700 delay-150"></div>
                                                    <div className="w-1.5 h-1.5 bg-[var(--accent-indigo)] rounded-full animate-bounce duration-700 delay-300"></div>
                                                </div>
                                                <button 
                                                    onClick={handleStopGeneration}
                                                    className="w-fit px-3 py-1.5 border border-red-100 bg-red-50 text-red-500 rounded-lg text-[9px] font-black uppercase tracking-widest flex items-center gap-2 hover:bg-red-500 hover:text-white transition-all active:scale-95 shadow-sm"
                                                >
                                                    < Zap size={12} fill="currentColor" /> Stop Thinking
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Chat Input Container */}
                        <div className="px-6 py-4 shrink-0 max-w-4xl w-full mx-auto">
                            {/* Attached files preview */}
                            {attachments.length > 0 && (
                                <div className="flex flex-wrap gap-2 mb-3">
                                    {attachments.map((att) => (
                                        <div
                                            key={att.name}
                                            className="group/att flex items-center gap-2 pl-2 pr-1.5 py-1.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl max-w-[220px]"
                                            title={att.name}
                                        >
                                            <span className="w-6 h-6 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0">
                                                {att.has_image ? <ImageIcon size={13} /> : <FileText size={13} />}
                                            </span>
                                            <span className="text-[11px] font-bold text-[var(--text-main)] truncate">{att.name}</span>
                                            <button
                                                type="button"
                                                onClick={() => handleRemoveAttachment(att.name)}
                                                className="w-5 h-5 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-colors shrink-0"
                                                title="Remove file"
                                            >
                                                <X size={13} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                            <form
                                onSubmit={(e) => { e.preventDefault(); handleSend(); }}
                                className="relative group flex items-center gap-2"
                            >
                                <div className="relative flex-1">
                                    <div className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] flex items-center gap-1">
                                        <button 
                                            type="button" 
                                            disabled={uploading}
                                            onClick={() => fileInputRef.current?.click()}
                                            className="p-1 hover:text-[var(--accent-indigo)] transition-colors"
                                        >
                                            {uploading ? <RefreshCcw size={16} className="animate-spin" /> : <Plus size={18} />}
                                        </button>
                                    </div>
                                    <textarea 
                                        ref={textareaRef}
                                        value={input}
                                        onChange={e => setInput(e.target.value)}
                                        onKeyDown={e => {
                                            if (e.key === 'Enter' && !e.shiftKey) {
                                                e.preventDefault();
                                                handleSend();
                                            }
                                        }}
                                        disabled={sending}
                                        rows={1}
                                        placeholder={`Consult ${project.title} Engine...`}
                                        className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl py-3.5 pl-12 pr-12 text-[13px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] focus:ring-4 focus:ring-[var(--accent-indigo-bg)] transition-shadow shadow-sm placeholder:text-[var(--text-muted)]/50 resize-none no-scrollbar leading-relaxed"
                                    />
                                    <button 
                                        type="submit" 
                                        disabled={sending || !input.trim()}
                                        className={`absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-xl flex items-center justify-center transition-all ${input.trim() ? 'bg-[var(--accent-indigo)] text-white shadow-lg shadow-indigo-100 active:scale-95' : 'bg-transparent text-[var(--text-muted)] opacity-50'}`}
                                    >
                                        <Send size={18} />
                                    </button>
                                </div>
                            </form>
                            <p className="text-center text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider mt-3 opacity-40">
                                Neural Engine can error. Independent verification advised.
                            </p>
                        </div>
                    </>
                ) : loading ? (
                    <div className="h-full flex flex-col items-center justify-center space-y-4">
                        <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                        <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Initializing Engine...</span>
                    </div>
                ) : (
                    <div className="h-full flex flex-col items-center justify-center text-center space-y-6">
                        <div className="w-24 h-24 rounded-[40px] bg-indigo-50 text-[var(--accent-indigo)] flex items-center justify-center shadow-inner">
                            <Sparkles size={48} />
                        </div>
                        <div className="space-y-1">
                            <h2 className="text-3xl font-black text-[var(--text-main)] tracking-tight uppercase italic">Neural Engine Error</h2>
                            <p className="text-[12px] font-bold text-[var(--text-muted)] max-w-sm mx-auto uppercase tracking-widest opacity-60 leading-relaxed">
                                The specified knowledge base could not be initialized. Please return to the hub and select a valid project.
                            </p>
                        </div>
                        <button 
                            onClick={() => navigate('/gpt')}
                            className="px-6 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl text-[11px] font-black uppercase tracking-widest flex items-center gap-2 hover:bg-white transition-all shadow-sm"
                        >
                            <ChevronLeft size={14} /> Back to Hub
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
};

export default GptChat;
