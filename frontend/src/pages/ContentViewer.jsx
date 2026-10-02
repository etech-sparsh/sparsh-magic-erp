import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { 
    ArrowLeft, 
    MessageSquare, 
    FileText, 
    StickyNote, 
    Send, 
    Eye, 
    Users, 
    Sparkles, 
    Clock, 
    Download, 
    AlertCircle, 
    ChevronRight
} from 'lucide-react';
import {  AnimatePresence , motion } from 'framer-motion';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

const ContentViewer = () => {
    const { sessionId, resourceId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const [loading, setLoading] = useState(true);
    const [resource, setResource] = useState(null);
    const [activeTab, setActiveTab] = useState('AI'); // AI, Transcript
    const [chatInput, setChatInput] = useState('');
    const [chatHistory, setChatHistory] = useState([]);
    const [askingAI, setAskingAI] = useState(false);
    
    // Analytics & Heartbeat
    const [watchSessionId, setWatchSessionId] = useState(null);
    const [showAnalytics, setShowAnalytics] = useState(false);
    const [analyticsMode, setAnalyticsMode] = useState('unique'); // 'unique' or 'full'
    const [analytics, setAnalytics] = useState(null);
    const [loadingAnalytics, setLoadingAnalytics] = useState(false);
    
    const videoRef = useRef(null);

    useEffect(() => {
        fetchResourceDetails();
        trackView();
    }, [resourceId]);

    const fetchResourceDetails = async () => {
        try {
            const res = await api.get(`/calendar/events/${sessionId}/resources/${resourceId}`);
            setResource(res.data);
        } catch (err) {
            console.error("Error fetching resource:", err);
        } finally {
            setLoading(false);
        }
    };

    const trackView = async () => {
        try {
            const res = await api.post(`/calendar/events/${sessionId}/resources/${resourceId}/view`);
            if (res.data.watch_session_id) {
                setWatchSessionId(res.data.watch_session_id);
            }
        } catch (err) {
            console.error("Error tracking view:", err);
        }
    };

    // ─── Heartbeat Mechanism ───
    useEffect(() => {
        if (!watchSessionId || !videoRef.current) return;

        const interval = setInterval(() => {
            const isPlaying = videoRef.current && !videoRef.current.paused && !videoRef.current.ended;
            if (isPlaying) {
                api.post(`/calendar/events/${sessionId}/resources/${resourceId}/watch-time`, {
                    watch_session_id: watchSessionId,
                    seconds: 5
                }).catch(() => {}); // Silent fail
            }
        }, 5000);

        return () => clearInterval(interval);
    }, [watchSessionId]);

    const fetchAnalytics = async (mode = 'unique') => {
        if (!['superadmin', 'admin', 'coach', 'staff'].includes(user?.role)) return;
        setAnalyticsMode(mode);
        setLoadingAnalytics(true);
        try {
            const res = await api.get(`/calendar/events/${sessionId}/resources/${resourceId}/analytics`);
            setAnalytics(res.data);
            setShowAnalytics(true);
        } catch (err) {
            console.error("Error fetching analytics:", err);
        } finally {
            setLoadingAnalytics(false);
        }
    };

    const handleAskAI = async (e) => {
        e.preventDefault();
        if (!chatInput.trim()) return;

        const userMsg = chatInput;
        setChatInput('');
        setChatHistory(prev => [...prev, { role: 'user', content: userMsg }]);
        setAskingAI(true);

        try {
            const res = await api.post(`/calendar/events/${sessionId}/resources/${resourceId}/chat`, {
                question: userMsg
            });
            setChatHistory(prev => [...prev, { role: 'ai', content: res.data.answer }]);
        } catch (err) {
            setChatHistory(prev => [...prev, { role: 'ai', content: "Sorry, I'm having trouble connecting right now." }]);
        } finally {
            setAskingAI(false);
        }
    };

    const seekToTimestamp = (timestamp) => {
        // Simple regex or similar to find timestamps like 12:34
        if (videoRef.current) {
            // This is just a placeholder logic to show how it would work
            // Actual implementation would need timestamp markers in the transcript
            // videoRef.current.currentTime = seconds;
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-[var(--bg-main)]">
                <div className="w-12 h-12 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
            </div>
        );
    }

    if (!resource) {
        return (
            <div className="flex flex-col items-center justify-center min-h-screen bg-[var(--bg-main)] text-[var(--text-muted)] p-4">
                <AlertCircle size={64} className="mb-4 opacity-20" />
                <h2 className="text-2xl font-black mb-2">Resource Not Found</h2>
                <button onClick={() => navigate(-1)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl font-bold">Go Back</button>
            </div>
        );
    }

    const isVideo = resource.file_type?.startsWith('video/') || resource.system_type === 'video';
    const isAudio = resource.file_type?.startsWith('audio/') || resource.system_type === 'audio';
    const isPDF = resource.file_type === 'application/pdf' || resource.system_type === 'pdf' || resource.url?.toLowerCase().endsWith('.pdf');
    const isImage = resource.file_type?.startsWith('image/') || ['jpg', 'jpeg', 'png', 'svg', 'webp'].some(ext => resource.url?.toLowerCase().endsWith(`.${ext}`));
    const isDoc = !isVideo && !isAudio && !isPDF && !isImage;

    return (
        <div className="min-h-screen bg-[var(--bg-main)] flex flex-col lg:flex-row">
            
            {/* Left Section: Content Player */}
            <div className="flex-1 overflow-y-auto no-scrollbar p-6 lg:p-10 space-y-8">
                <div className="flex items-center justify-between mb-2">
                    <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors font-bold text-sm">
                        <ArrowLeft size={18} /> Back to Session
                    </button>
                    <div className="px-3 py-1 bg-[var(--input-bg)] border border-[var(--border)] rounded-full text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        {resource.system_type} Mode
                    </div>
                </div>

                {/* Media Container */}
                <div className="bg-black rounded-[32px] overflow-hidden shadow-2xl aspect-video flex items-center justify-center relative group">
                    {isVideo ? (
                        <video 
                            ref={videoRef}
                            src={resource.url} 
                            controls 
                            crossOrigin="anonymous"
                            controlsList="nodownload"
                            onContextMenu={(e) => e.preventDefault()}
                            className="w-full h-full object-contain"
                        />
                    ) : isAudio ? (
                        <div className="w-full h-full flex flex-col items-center justify-center space-y-6 bg-gradient-to-br from-gray-900 to-black p-10">
                            <div className="w-24 h-24 rounded-full bg-[var(--accent-indigo)] flex items-center justify-center shadow-lg shadow-indigo-500/20">
                                <Sparkles size={40} className="text-white animate-pulse" />
                            </div>
                            <audio 
                                ref={videoRef} 
                                src={resource.url} 
                                controls 
                                crossOrigin="anonymous" 
                                controlsList="nodownload"
                                onContextMenu={(e) => e.preventDefault()}
                                className="w-full max-w-md accent-indigo-500" 
                            />
                        </div>
                    ) : isPDF ? (
                        <iframe 
                            src={`${resource.url}#toolbar=0`} 
                            className="w-full h-full border-0"
                            title={resource.name}
                        />
                    ) : isImage ? (
                        <img 
                            src={resource.url} 
                            alt={resource.name}
                            className="w-full h-full object-contain"
                        />
                    ) : (
                        <div className="text-white flex flex-col items-center gap-4 p-10 text-center">
                            <FileText size={80} className="opacity-20" />
                            <p className="font-black text-xl uppercase tracking-widest">{resource.name}</p>
                            <p className="text-[11px] font-bold text-gray-400 max-w-sm">
                                This file type ({resource.file_type || 'Unknown'}) is being analyzed by Sparsh AI. 
                                Use the Knowledge Companion on the right to interact with its contents.
                            </p>
                            <a 
                                href={resource.url} 
                                target="_blank" 
                                rel="noreferrer" 
                                className="mt-4 px-8 py-3 bg-[var(--accent-indigo)] text-white rounded-full font-black text-xs uppercase shadow-lg shadow-indigo-500/20 active:scale-95 transition-all"
                            >
                                Open in New Tab
                            </a>
                        </div>
                    )}
                </div>

                {/* Meta Info */}
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 pb-20">
                    <div className="space-y-4 max-w-2xl">
                        <h1 className="text-xl md:text-2xl font-black text-[var(--text-main)] tracking-tight leading-tight">{resource.name}</h1>
                        <div className="space-y-2">
                            <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Description</label>
                            <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
                                No specific description provided for this resource. Use the AI Companion to summarize and understand the core topics discussed.
                            </p>
                        </div>
                    </div>

                    {['superadmin', 'admin', 'coach', 'staff'].includes(user?.role) && (
                        <div className="flex gap-4">
                            <div 
                                onClick={() => fetchAnalytics('full')}
                                className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl flex items-center gap-4 shadow-sm min-w-[140px] cursor-pointer hover:border-[var(--accent-indigo)] transition-all active:scale-95"
                            >
                                <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
                                    <Eye size={20} />
                                </div>
                                <div>
                                    <p className="text-[10px] font-black text-gray-400 uppercase">Total Hits</p>
                                    <p className="text-xl font-black">{resource.views || 0}</p>
                                </div>
                            </div>
                            <div 
                                onClick={() => fetchAnalytics('unique')}
                                className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl flex items-center gap-4 shadow-sm min-w-[160px] cursor-pointer hover:border-[var(--accent-indigo)] transition-all active:scale-95"
                            >
                                <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center">
                                    <Users size={20} />
                                </div>
                                <div>
                                    <p className="text-[10px] font-black text-gray-400 uppercase">Unique Viewers</p>
                                    <p className="text-xl font-black">{resource.unique_viewers_count || 1}</p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Right Section: AI Companion & Transcript */}
            <div className="w-full lg:w-[450px] bg-[var(--bg-card)] border-l border-[var(--border)] flex flex-col h-screen overflow-hidden">
                
                {/* Header */}
                <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-[var(--bg-card)]/80 backdrop-blur-md sticky top-0 z-10">
                    <h2 className="text-lg font-black text-[var(--text-main)] flex items-center gap-2">
                        <Sparkles size={20} className="text-[var(--accent-indigo)]" /> AI Companion
                    </h2>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-[var(--border)] px-4 bg-[var(--bg-card)]/30">
                    {['AI', 'Transcript'].map(tab => (
                        <button 
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`px-4 py-4 text-[11px] font-black uppercase tracking-widest relative transition-all ${activeTab === tab ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                        >
                            {tab}
                            {activeTab === tab && (
                                <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--accent-indigo)] rounded-t-full" />
                            )}
                        </button>
                    ))}
                </div>

                {/* Content Area */}
                <div className="flex-1 overflow-y-auto p-6 no-scrollbar">
                    <AnimatePresence mode="wait">
                        {activeTab === 'Transcript' && (
                            <motion.div 
                                initial={{ opacity: 0, x: 10 }} 
                                animate={{ opacity: 1, x: 0 }} 
                                exit={{ opacity: 0, x: -10 }}
                                className="space-y-6"
                            >
                                {resource.transcription ? (
                                    <div className="space-y-4">
                                        <div className="flex items-center gap-2 text-[var(--accent-indigo)] mb-4 bg-[var(--accent-indigo-bg)] p-3 rounded-xl border border-[var(--accent-indigo)]/20 italic text-[12px]">
                                            <Clock size={14} /> AI-generated transcript. Click segments to seek in player.
                                        </div>
                                        <p className="text-[13px] leading-relaxed text-[var(--text-main)] font-medium">
                                            {resource.transcription}
                                        </p>
                                    </div>
                                ) : (
                                    <div className="text-center py-20 text-[var(--text-muted)] opacity-50 space-y-4">
                                        <FileText size={48} className="mx-auto" />
                                        <p className="text-sm font-bold uppercase tracking-widest">No transcript available.</p>
                                    </div>
                                )}
                            </motion.div>
                        )}

                        {activeTab === 'AI' && (
                            <motion.div 
                                initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }}
                                className="space-y-6"
                            >
                                <div className="p-4 bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo)]/10 rounded-[20px] shadow-sm">
                                    <div className="flex items-center gap-2 text-[var(--accent-indigo)] mb-2">
                                        <Sparkles size={16} />
                                        <h4 className="text-[11px] font-black uppercase tracking-widest">Intelligent Assistant</h4>
                                    </div>
                                    <p className="text-[12px] text-[var(--text-muted)] leading-relaxed">
                                        Hello! I've analyzed this session's recording. You can ask me anything about the content, specific topics, or for a summary.
                                    </p>
                                </div>
                                
                                {chatHistory.length > 0 && (
                                    <div className="space-y-6 pt-4">
                                        {chatHistory.map((chat, idx) => (
                                            <div key={idx} className={`flex flex-col ${chat.role === 'user' ? 'items-end' : 'items-start'} space-y-2`}>
                                                <div className={`max-w-[90%] p-4 rounded-2xl text-[13px] font-medium leading-relaxed shadow-sm ${chat.role === 'user' ? 'bg-[var(--accent-indigo)] text-white rounded-tr-none' : 'bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-tl-none'}`}>
                                                    {chat.content}
                                                </div>
                                            </div>
                                        ))}
                                        {askingAI && (
                                            <div className="flex items-center gap-2 text-[var(--text-muted)]">
                                                <div className="flex gap-1">
                                                    <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1 }} className="w-1 h-1 bg-[var(--text-muted)] rounded-full" />
                                                    <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1, delay: 0.2 }} className="w-1 h-1 bg-[var(--text-muted)] rounded-full" />
                                                    <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1, delay: 0.4 }} className="w-1 h-1 bg-[var(--text-muted)] rounded-full" />
                                                </div>
                                                <span className="text-[10px] font-black uppercase tracking-widest">AI is thinking...</span>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {/* Chat Input - Only visible on AI tab */}
                {activeTab === 'AI' && (
                    <div className="p-6 bg-[var(--bg-card)] border-t border-[var(--border)]">
                        <form onSubmit={handleAskAI} className="relative group">
                            <input 
                                value={chatInput}
                                onChange={e => setChatInput(e.target.value)}
                                className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl py-4 pl-5 pr-14 text-sm font-medium focus:border-[var(--accent-indigo)] outline-none transition-all placeholder:text-[var(--text-muted)]"
                                placeholder="Ask AI about this video..."
                                disabled={askingAI}
                            />
                            <button 
                                type="submit"
                                disabled={askingAI}
                                className="absolute right-2 top-2 w-10 h-10 rounded-xl bg-[var(--accent-indigo)] text-white flex items-center justify-center hover:opacity-90 active:scale-95 transition-all shadow-md shadow-indigo-200"
                            >
                                <Send size={18} />
                            </button>
                        </form>
                        <div className="mt-3 flex items-center gap-2 text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider ml-1">
                            <Sparkles size={12} className="text-[var(--accent-indigo)]" /> Powered by Advanced LLM
                        </div>
                    </div>
                )}
            </div>

            {/* Engagement Analytics Modal */}
            <AnimatePresence>
                {showAnalytics && (
                    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
                        <motion.div 
                            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                            onClick={() => setShowAnalytics(false)}
                            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        />
                        <motion.div 
                            initial={{ opacity: 0, scale: 0.95, y: 20 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95, y: 20 }}
                            className="relative w-full max-w-2xl bg-[var(--bg-main)] rounded-[32px] overflow-hidden shadow-2xl border border-[var(--border)]"
                        >
                            <div className="p-8 border-b border-[var(--border)] flex items-center justify-between bg-[var(--bg-card)]">
                                <div>
                                    <h3 className="text-2xl font-black text-[var(--text-main)]">Audience Engagement</h3>
                                    <p className="text-[12px] font-bold text-[var(--text-muted)] uppercase tracking-widest mt-1">Resource: {resource.name}</p>
                                </div>
                                <button onClick={() => setShowAnalytics(false)} className="w-10 h-10 rounded-full bg-[var(--input-bg)] flex items-center justify-center text-[var(--text-muted)] hover:text-red-500 transition-colors">
                                    <ChevronRight className="rotate-90" />
                                </button>
                            </div>

                            <div className="p-8 max-h-[60vh] overflow-y-auto no-scrollbar">
                                <div className="grid grid-cols-2 gap-4 mb-8">
                                    <div className="p-6 rounded-[24px] bg-blue-50/50 border border-blue-100 flex flex-col items-center">
                                        <p className="text-[10px] font-black text-blue-400 uppercase tracking-widest mb-1">Total Hits</p>
                                        <p className="text-3xl font-black text-blue-600">{analytics?.total_views || 0}</p>
                                    </div>
                                    <div className="p-6 rounded-[24px] bg-purple-50/50 border border-purple-100 flex flex-col items-center">
                                        <p className="text-[10px] font-black text-purple-400 uppercase tracking-widest mb-1">Unique Viewers</p>
                                        <p className="text-3xl font-black text-purple-600">{analytics?.unique_viewers_count || 0}</p>
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    <div className="flex items-center justify-between ml-1">
                                        <h4 className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{analyticsMode === 'unique' ? 'Reach (Unique Members)' : 'Impact (Every Hit History)'}</h4>
                                        <div className="flex bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--border)]">
                                            <button onClick={() => setAnalyticsMode('full')} className={`px-3 py-1 text-[9px] font-black uppercase rounded-md transition-all ${analyticsMode === 'full' ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}>Hits</button>
                                            <button onClick={() => setAnalyticsMode('unique')} className={`px-3 py-1 text-[9px] font-black uppercase rounded-md transition-all ${analyticsMode === 'unique' ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}>Unique</button>
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        {(analyticsMode === 'unique' ? analytics?.unique_logs : analytics?.full_logs)?.map((viewer, idx) => (
                                            <div key={idx} className="p-4 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl flex items-center justify-between hover:border-[var(--accent-indigo)] transition-colors group">
                                                <div className="flex items-center gap-4">
                                                    <div className="w-10 h-10 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center font-black text-sm">
                                                        {viewer.user_name?.charAt(0).toUpperCase()}
                                                    </div>
                                                    <div>
                                                        <p className="font-bold text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors">{viewer.user_name}</p>
                                                        <p className="text-[10px] text-[var(--text-muted)] font-bold uppercase tracking-wider">
                                                            {analyticsMode === 'unique' ? 'Last seen: ' : 'Viewed at: '} 
                                                            {new Date(viewer.last_view || viewer.timestamp).toLocaleString(undefined, {
                                                                day: 'numeric', month: 'numeric', year: 'numeric',
                                                                hour: '2-digit', minute: '2-digit', second: '2-digit',
                                                                hour12: true
                                                            })}
                                                        </p>
                                                    </div>
                                                </div>
                                                <div className="text-right">
                                                    <div className="flex items-center gap-1 justify-end text-[var(--accent-indigo)]">
                                                        <Clock size={12} />
                                                        <p className="text-sm font-black">
                                                            {Math.floor((viewer.total_duration || viewer.duration) / 60)}m 
                                                            {(viewer.total_duration || viewer.duration) % 60}s
                                                        </p>
                                                    </div>
                                                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                                        {analyticsMode === 'unique' ? `Across ${viewer.view_count} visits` : 'Session Duration'}
                                                    </p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="p-6 bg-[var(--input-bg)]/50 text-center">
                                <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Tracking active • Data updates in real-time</p>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default ContentViewer;
