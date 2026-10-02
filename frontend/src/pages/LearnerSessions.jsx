import React, { useState, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { 
    PlayCircle, CalendarDays, Clock, Video, 
    Building2, LayoutGrid, CheckCircle, ChevronRight, 
    Search, Filter, Activity, Sparkles
} from 'lucide-react';
import { Link } from 'react-router-dom';

const LearnerSessions = () => {
    useAuth();
    const [sessions, setSessions] = useState([]);
    const [batches, setBatches] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [filterStatus, setFilterStatus] = useState('all'); // all, upcoming, past

    const fetchData = async () => {
        setLoading(true);
        try {
            const [evRes, bRes] = await Promise.all([
                api.get('/calendar/events'),
                api.get('/batches')
            ]);
            
            // Filter only training sessions (type: event) that are assigned to the user
            // The backend already filters by user assignment, so we just filter by type
            const allSessions = evRes.data
                .filter(e => e.type === 'event')
                .sort((a, b) => new Date(a.start) - new Date(b.start));
            
            setSessions(allSessions);
            setBatches(bRes.data);
        } catch (err) {
            console.error("Error fetching sessions:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, []);

    const formatIST = (dateStr) => {
        if (!dateStr) return "";
        return new Date(dateStr).toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short',
            hour: '2-digit', minute: '2-digit', hour12: true
        });
    };

    const isLive = (start, end) => {
        const now = new Date();
        const s = new Date(start);
        const e = end ? new Date(end) : new Date(s.getTime() + 60 * 60 * 1000);
        return now >= s && now <= e;
    };

    const filteredSessions = sessions.filter(s => {
        const matchesSearch = s.title.toLowerCase().includes(searchTerm.toLowerCase());
        const isFuture = new Date(s.start) >= new Date();
        
        if (filterStatus === 'upcoming') return matchesSearch && isFuture;
        if (filterStatus === 'past') return matchesSearch && !isFuture;
        return matchesSearch;
    });

    const nextSession = sessions.find(s => new Date(s.start) >= new Date());

    return (
        <div className="min-h-screen bg-[var(--bg-main)] p-4 md:p-8 space-y-8 pb-20">
            {/* ─── Header ─── */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div className="space-y-1">
                    <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight flex items-center gap-3">
                        <PlayCircle size={32} className="text-[var(--accent-indigo)]" />
                        My Training Journey
                    </h1>
                    <p className="text-[13px] text-[var(--text-muted)] font-bold italic tracking-wide">
                        Accelerate your growth through structured operational sessions.
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    <div className="relative group">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent-indigo)] transition-colors" size={16} />
                        <input 
                            type="text" 
                            placeholder="Search sessions..." 
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl py-2.5 pl-10 pr-4 text-[13px] font-black outline-none focus:ring-2 focus:ring-[var(--accent-indigo)]/20 focus:border-[var(--accent-indigo)] transition-all w-64 shadow-sm"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>
                </div>
            </div>

            {loading ? (
                <div className="flex flex-col items-center justify-center py-40 space-y-4">
                    <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
                    <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em]">Synchronizing Curriculum...</p>
                </div>
            ) : (
                <>
                    {/* ─── Featured Next Session ─── */}
                    {nextSession && (
                        <motion.div 
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="relative overflow-hidden group"
                        >
                            <div className="absolute inset-0 bg-gradient-to-r from-indigo-600/10 to-purple-600/10 rounded-[40px] border border-indigo-500/20" />
                            <div className="relative bg-[var(--bg-card)] p-8 rounded-[40px] border border-[var(--border)] shadow-2xl flex flex-col md:flex-row items-center gap-8">
                                <div className="w-20 h-20 md:w-32 md:h-32 rounded-[32px] bg-indigo-50 flex items-center justify-center text-indigo-600 shrink-0 shadow-inner">
                                    <Sparkles size={48} className="animate-pulse" />
                                </div>
                                <div className="flex-1 space-y-4 text-center md:text-left">
                                    <div className="flex flex-wrap items-center justify-center md:justify-start gap-3">
                                        <span className="px-4 py-1.5 bg-indigo-600 text-white text-[10px] font-black uppercase tracking-widest rounded-full shadow-lg shadow-indigo-200">Next Priority Session</span>
                                        {isLive(nextSession.start, nextSession.end) && (
                                            <span className="px-4 py-1.5 bg-emerald-500 text-white text-[10px] font-black uppercase tracking-widest rounded-full animate-bounce shadow-lg shadow-emerald-200 flex items-center gap-2">
                                                <div className="w-1.5 h-1.5 rounded-full bg-white animate-ping" /> LIVE NOW
                                            </span>
                                        )}
                                    </div>
                                    <h2 className="text-3xl md:text-4xl font-black text-[var(--text-main)] tracking-tighter">{nextSession.title}</h2>
                                    <div className="flex flex-wrap items-center justify-center md:justify-start gap-6 text-[14px] font-black text-[var(--text-muted)]">
                                        <div className="flex items-center gap-2"><CalendarDays size={18} className="text-indigo-500"/> {formatIST(nextSession.start)}</div>
                                        <div className="flex items-center gap-2"><Building2 size={18} className="text-indigo-500"/> {batches.find(b => b._id === nextSession.extendedProps?.batch_id)?.name || "Main Batch"}</div>
                                    </div>
                                </div>
                                <div className="shrink-0 flex flex-col gap-3 w-full md:w-auto">
                                    {(nextSession.extendedProps?.status === 'completed' || new Date(nextSession.end || nextSession.start) < new Date()) ? (
                                        <Link to={`/sessions/${nextSession.id}`} 
                                           className="px-10 py-5 bg-[var(--accent-indigo)] text-white rounded-[24px] text-[14px] font-black uppercase tracking-widest flex items-center justify-center gap-3 shadow-xl shadow-indigo-500/30 hover:scale-105 active:scale-95 transition-all">
                                            <Activity size={20} /> View Details
                                        </Link>
                                    ) : (
                                        nextSession.extendedProps?.meeting_link ? (
                                            <a href={nextSession.extendedProps.meeting_link} target="_blank" rel="noreferrer" 
                                               className="px-10 py-5 bg-[var(--accent-indigo)] text-white rounded-[24px] text-[14px] font-black uppercase tracking-widest flex items-center justify-center gap-3 shadow-xl shadow-indigo-500/30 hover:scale-105 active:scale-95 transition-all">
                                                <Video size={20} /> Join Experience
                                            </a>
                                        ) : (
                                            <button disabled className="px-10 py-5 bg-gray-100 text-gray-400 rounded-[24px] text-[14px] font-black uppercase tracking-widest cursor-not-allowed">
                                                Link Pending
                                            </button>
                                        )
                                    )}
                                    <Link to="/calendar" className="text-[11px] font-black text-center text-[var(--accent-indigo)] uppercase tracking-widest hover:underline">View in Schedule Architect</Link>
                                </div>
                            </div>
                        </motion.div>
                    )}

                    {/* ─── Grid Controls ─── */}
                    <div className="flex items-center justify-between pt-8 border-t border-[var(--border)]">
                        <div className="flex bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-2xl shadow-sm">
                            {['all', 'upcoming', 'past'].map(st => (
                                <button 
                                    key={st}
                                    onClick={() => setFilterStatus(st)}
                                    className={`px-6 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${filterStatus === st ? 'bg-[var(--accent-indigo)] text-white shadow-lg' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}
                                >
                                    {st === 'all' ? 'Every Session' : st === 'upcoming' ? 'Upcoming' : 'Legacy List'}
                                </button>
                            ))}
                        </div>
                        <p className="hidden md:block text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Showing {filteredSessions.length} total entries</p>
                    </div>

                    {/* ─── Sessions Grid ─── */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 pb-20">
                        {filteredSessions.map((session, idx) => {
                            const isUpcoming = new Date(session.start) >= new Date();
                            const isCurrent = isLive(session.start, session.end);
                            
                            return (
                                <motion.div 
                                    key={session.id}
                                    initial={{ opacity: 0, scale: 0.95 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    transition={{ delay: idx * 0.05 }}
                                    className="bg-[var(--bg-card)] rounded-[32px] border border-[var(--border)] overflow-hidden shadow-xl hover:shadow-2xl hover:border-[var(--accent-indigo)]/30 transition-all flex flex-col group h-full"
                                >
                                    <div className="p-6 space-y-5 flex-1">
                                        <div className="flex items-center justify-between">
                                            <div className={`p-3 rounded-2xl ${isUpcoming ? 'bg-indigo-50 text-indigo-600' : 'bg-gray-100 text-gray-500'}`}>
                                                <Activity size={20} />
                                            </div>
                                            {isCurrent ? (
                                                <div className="flex items-center gap-1.5 px-3 py-1 bg-emerald-50 text-emerald-600 rounded-lg text-[9px] font-black uppercase tracking-widest animate-pulse border border-emerald-100">Live</div>
                                            ) : (
                                                <div className={`px-3 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest border ${isUpcoming ? 'bg-amber-50 text-amber-600 border-amber-100' : 'bg-gray-50 text-gray-400 border-gray-100'}`}>
                                                    {isUpcoming ? 'Scheduled' : 'Completed'}
                                                </div>
                                            )}
                                        </div>

                                        <div className="space-y-1">
                                            <h3 className="text-xl font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors leading-tight">
                                                {session.title}
                                            </h3>
                                            <p className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-1.5">
                                                <Building2 size={12} /> {batches.find(b => b._id === session.extendedProps?.batch_id)?.name || "General Batch"}
                                            </p>
                                        </div>

                                        <div className="space-y-3 pt-2">
                                            <div className="flex items-center gap-3 text-[12px] font-black text-[var(--text-main)]">
                                                <CalendarDays size={14} className="text-gray-400" />
                                                {formatIST(session.start).split(',')[0]}
                                            </div>
                                            <div className="flex items-center gap-3 text-[12px] font-black text-[var(--text-main)]">
                                                <Clock size={14} className="text-gray-400" />
                                                {session.allDay ? 'Full Day Operation' : formatIST(session.start).split(',')[1]}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="p-4 bg-[var(--table-header-bg)] border-t border-[var(--border)] flex gap-2">
                                        {(session.extendedProps?.status === 'completed' || !isUpcoming) ? (
                                            <Link 
                                                to={`/sessions/${session.id}`}
                                                className="flex-1 py-3 bg-[var(--accent-indigo)] text-white rounded-2xl text-[10px] font-black uppercase tracking-widest text-center shadow-lg shadow-indigo-100 hover:scale-[1.02] transition-all flex items-center justify-center gap-2"
                                            >
                                                <Activity size={14} /> View Details
                                            </Link>
                                        ) : (
                                            session.extendedProps?.meeting_link ? (
                                                <a 
                                                    href={session.extendedProps.meeting_link} 
                                                    target="_blank" 
                                                    rel="noreferrer"
                                                    className="flex-1 py-3 bg-[var(--accent-indigo)] text-white rounded-2xl text-[10px] font-black uppercase tracking-widest text-center shadow-lg shadow-indigo-100 hover:scale-[1.02] transition-all flex items-center justify-center gap-2"
                                                >
                                                    <Video size={14} /> Join Now
                                                </a>
                                            ) : (
                                                <div className="flex-1 py-3 bg-gray-50 text-gray-400 rounded-2xl text-[10px] font-black uppercase tracking-widest text-center border border-dashed border-gray-200">
                                                    Link TBA
                                                </div>
                                            )
                                        )}
                                        <Link 
                                            to="/calendar" 
                                            className="p-3 bg-white border border-[var(--border)] text-[var(--text-muted)] rounded-2xl hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] transition-all"
                                        >
                                            <CalendarDays size={16} />
                                        </Link>
                                    </div>
                                </motion.div>
                            )
                        })}

                        {filteredSessions.length === 0 && (
                            <div className="col-span-full py-32 flex flex-col items-center justify-center bg-[var(--bg-card)] rounded-[40px] border border-dashed border-[var(--border)] space-y-4 shadow-inner">
                                <div className="w-20 h-20 rounded-full bg-gray-50 flex items-center justify-center text-gray-300">
                                    <Activity size={40} />
                                </div>
                                <div className="text-center">
                                    <h3 className="text-[14px] font-black text-[var(--text-main)] uppercase tracking-widest">No curriculum entries found</h3>
                                    <p className="text-[12px] text-[var(--text-muted)] font-medium">Try adjusting your filters or search terms.</p>
                                </div>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default LearnerSessions;
