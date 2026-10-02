import React, { useState, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
    Activity, BookOpen, CheckCircle2, Trophy, 
    Calendar, Clock, ChevronRight, Filter,
    Download, LayoutDashboard, Brain, Target, X
} from 'lucide-react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

const MyReports = () => {
    useAuth();
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [activeTab, setActiveTab] = useState('overview'); // overview, assessments, activities
    const [selectedQuiz, setSelectedQuiz] = useState(null); // For Review Modal

    useEffect(() => {
        fetchReports();
    }, []);

    const fetchReports = async () => {
        try {
            const res = await api.get('/users/me/reports');
            setData(res.data);
        } catch (err) {
            console.error("Failed to fetch reports:", err);
        } finally {
            setLoading(false);
        }
    };

    if (loading) return (
        <div className="flex items-center justify-center min-h-[400px]">
            <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
        </div>
    );

    const container = {
        hidden: { opacity: 0 },
        show: {
            opacity: 1,
            transition: { staggerChildren: 0.1 }
        }
    };

    const item = {
        hidden: { opacity: 0, y: 10 },
        show: { opacity: 1, y: 0 }
    };

    return (
        <div className="max-w-[1400px] mx-auto space-y-6 pb-10 px-4">
            {/* Header Area - More Compact */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 py-2 border-b border-[var(--border)]">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo)] flex items-center justify-center text-white shadow-lg">
                        <Trophy size={20} />
                    </div>
                    <div>
                        <h1 className="text-2xl font-black text-[var(--text-main)] italic uppercase tracking-tighter leading-none">My Progress <span className="text-[var(--accent-indigo)]">Reports</span></h1>
                        <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mt-1 opacity-70">Learner impact & analytics</p>
                    </div>
                </div>
                
                <div className="flex bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl shadow-sm scale-90 origin-right">
                    {['overview', 'assessments', 'activities'].map(tab => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${activeTab === tab ? 'bg-black text-white shadow-md' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                        >
                            {tab}
                        </button>
                    ))}
                </div>
            </div>

            {/* Stats Overview - Compact Cards */}
            <motion.div 
                variants={container}
                initial="hidden"
                animate="show"
                className="grid grid-cols-2 lg:grid-cols-4 gap-4"
            >
                {[
                    { label: 'Activities', val: data?.stats?.total_activities, icon: Activity, color: 'indigo', meta: 'Participation' },
                    { label: 'Assessments', val: data?.stats?.quizzes_taken, icon: Brain, color: 'purple', meta: 'Knowledge Checks' },
                    { label: 'Passed', val: data?.stats?.quizzes_passed, icon: CheckCircle2, color: 'emerald', meta: 'Excellence' },
                    { label: 'Pass Rate', val: `${data?.stats?.pass_rate}%`, icon: Trophy, color: 'blue', meta: 'Performance' }
                ].map((stat, idx) => (
                    <motion.div key={idx} variants={item} className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-[24px] shadow-sm relative overflow-hidden group">
                        <div className={`absolute top-0 right-0 w-24 h-24 bg-${stat.color}-50/50 rounded-full -mr-12 -mt-12 blur-2xl group-hover:opacity-100 opacity-50 transition-opacity`} />
                        <div className="relative flex items-center gap-4">
                            <div className={`w-10 h-10 shrink-0 rounded-xl bg-${stat.color}-50 text-${stat.color}-600 flex items-center justify-center shadow-sm`}>
                                <stat.icon size={18} />
                            </div>
                            <div>
                                <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest leading-none mb-1">{stat.label}</p>
                                <h3 className="text-xl font-black text-[var(--text-main)]">{stat.val}</h3>
                            </div>
                        </div>
                    </motion.div>
                ))}
            </motion.div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Left Column: Assessment History */}
                {(activeTab === 'overview' || activeTab === 'assessments') && (
                    <motion.div 
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        className={`space-y-4 ${activeTab === 'overview' ? 'lg:col-span-8' : 'lg:col-span-12'}`}
                    >
                        <div className="flex items-center justify-between px-1">
                            <h3 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                <BookOpen size={14} className="text-[var(--accent-indigo)]" />
                                Assessment History
                            </h3>
                        </div>
                        
                        <div className="space-y-3">
                            {data?.assessments?.map((quiz, idx) => (
                                <div 
                                    key={idx} 
                                    onClick={() => setSelectedQuiz(quiz)}
                                    className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-[20px] shadow-sm hover:border-[var(--accent-indigo)] hover:-translate-y-0.5 transition-all group flex items-center justify-between gap-4 cursor-pointer"
                                >
                                    <div className="flex items-center gap-4">
                                        <div className={`w-10 h-10 shrink-0 rounded-xl flex items-center justify-center ${quiz.passed ? 'bg-emerald-50 text-emerald-600' : 'bg-orange-50 text-orange-600'}`}>
                                            <Brain size={18} />
                                        </div>
                                        <div>
                                            <h4 className="font-black text-[var(--text-main)] uppercase text-[12px] group-hover:text-[var(--accent-indigo)] transition-colors line-clamp-1">{quiz.quiz_title}</h4>
                                            <div className="flex items-center gap-3 mt-1 underline-offset-2 decoration-[var(--border)]">
                                                <p className="text-[9px] font-bold text-[var(--text-muted)]">{new Date(quiz.submitted_at).toLocaleDateString()}</p>
                                                <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-tighter ${quiz.passed ? 'bg-emerald-100 text-emerald-700' : 'bg-orange-100 text-orange-700'}`}>
                                                    {quiz.passed ? 'Qualified' : 'Review'}
                                                </span>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-6 pr-1">
                                        <div className="text-right hidden md:block">
                                            <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-0.5">Score</p>
                                            <p className={`text-sm font-black ${quiz.passed ? 'text-emerald-600' : 'text-orange-600'}`}>{quiz.score}/{quiz.total_marks}</p>
                                        </div>
                                        <div className="text-right">
                                            <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-0.5">Result</p>
                                            <p className="text-sm font-black text-[var(--text-main)]">{Math.round(quiz.percentage)}%</p>
                                        </div>
                                        <ChevronRight size={16} className="text-[var(--text-muted)] group-hover:translate-x-1 group-hover:text-[var(--accent-indigo)] transition-transform" />
                                    </div>
                                </div>
                            ))}
                            {(!data?.assessments || data.assessments.length === 0) && (
                                <div className="p-12 text-center bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] border-dashed">
                                    <Brain size={32} className="mx-auto text-[var(--text-muted)] mb-4 opacity-20" />
                                    <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">No assessment data synchronized</p>
                                </div>
                            )}
                        </div>
                    </motion.div>
                )}

                {/* Right Column: Activity Timeline */}
                {(activeTab === 'overview' || activeTab === 'activities') && (
                    <motion.div 
                        initial={{ opacity: 0, x: 10 }}
                        animate={{ opacity: 1, x: 0 }}
                        className={`space-y-4 ${activeTab === 'overview' ? 'lg:col-span-4' : 'lg:col-span-12'}`}
                    >
                        <div className="flex items-center justify-between px-1">
                            <h3 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                <Clock size={14} className="text-orange-500" />
                                Activity Log
                            </h3>
                        </div>

                        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-6 rounded-[24px] shadow-sm relative h-fit max-h-[600px] overflow-y-auto no-scrollbar">
                            <div className="absolute left-9 top-6 bottom-6 w-px bg-[var(--border)] opacity-30" />
                            
                            <div className="space-y-6 relative">
                                {data?.activities?.map((act, idx) => (
                                    <div key={idx} className="flex gap-4 group">
                                        <div className="relative z-10 shrink-0 w-6 h-6 rounded-full bg-[var(--bg-main)] border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] group-hover:border-[var(--accent-indigo)] transition-colors">
                                            <div className="w-1.5 h-1.5 rounded-full bg-[var(--border)] group-hover:bg-[var(--accent-indigo)] transition-colors" />
                                        </div>
                                        <div className="space-y-0.5">
                                            <p className="text-[11px] font-bold text-[var(--text-main)] leading-tight">{act.details}</p>
                                            <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                                {new Date(act.timestamp).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' })}
                                            </p>
                                        </div>
                                    </div>
                                ))}
                                {(!data?.activities || data.activities.length === 0) && (
                                    <p className="text-center py-6 text-[9px] font-black text-[var(--text-muted)] uppercase">No recent logs</p>
                                )}
                            </div>
                        </div>
                    </motion.div>
                )}
            </div>

            {/* Assessment Review Modal - Fixed & Premium */}
            <AnimatePresence>
                {selectedQuiz && (
                    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
                        <motion.div 
                            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                            onClick={() => setSelectedQuiz(null)}
                            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        />
                        <motion.div 
                            initial={{ opacity: 0, scale: 0.95, y: 20 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95, y: 20 }}
                            className="relative w-full max-w-4xl bg-[var(--bg-main)] rounded-[32px] overflow-hidden shadow-2xl border border-[var(--border)] flex flex-col max-h-[85vh]"
                        >
                            {/* Modal Header - Compact */}
                            <div className={`px-8 py-6 border-b border-[var(--border)] flex items-center justify-between ${selectedQuiz.passed ? 'bg-emerald-50/20' : 'bg-orange-50/20'}`}>
                                <div className="flex items-center gap-4">
                                    <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shadow-inner ${selectedQuiz.passed ? 'bg-emerald-100 text-emerald-600' : 'bg-orange-100 text-orange-600'}`}>
                                        <Brain size={24} />
                                    </div>
                                    <div>
                                        <h3 className="text-xl font-black text-[var(--text-main)] uppercase tracking-tighter leading-none">{selectedQuiz.quiz_title}</h3>
                                        <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-widest mt-1">Reviewing Intelligence Node • {new Date(selectedQuiz.submitted_at).toLocaleDateString()}</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-4">
                                    <div className="text-right">
                                        <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-60">Result</p>
                                        <p className={`text-2xl font-black leading-none ${selectedQuiz.passed ? 'text-emerald-600' : 'text-orange-600'}`}>{Math.round(selectedQuiz.percentage)}%</p>
                                    </div>
                                    <button onClick={() => setSelectedQuiz(null)} className="w-10 h-10 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-red-500 transition-colors">
                                        <X size={20} />
                                    </button>
                                </div>
                            </div>

                            {/* Modal Content - Scrollable */}
                            <div className="flex-1 overflow-y-auto p-8 space-y-6 no-scrollbar">
                                <div className="grid grid-cols-3 gap-4">
                                    {[
                                        { label: 'Session Performance', val: `${selectedQuiz.score}/${selectedQuiz.total_marks}`, sub: 'Raw Points' },
                                        { label: 'Certification Status', val: selectedQuiz.passed ? 'Qualified' : 'Restricted', sub: selectedQuiz.passed ? 'Impact Success' : 'Review Required', color: selectedQuiz.passed ? 'emerald' : 'orange' },
                                        { label: 'Evaluation Date', val: new Date(selectedQuiz.submitted_at).toLocaleDateString(), sub: 'Synchronization' }
                                    ].map((box, bIdx) => (
                                        <div key={bIdx} className="p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] text-center">
                                            <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1">{box.label}</p>
                                            <p className={`text-lg font-black ${box.color === 'emerald' ? 'text-emerald-600' : box.color === 'orange' ? 'text-orange-600' : 'text-[var(--text-main)]'}`}>{box.val}</p>
                                            <p className="text-[8px] font-bold text-[var(--text-muted)] uppercase opacity-50 mt-0.5">{box.sub}</p>
                                        </div>
                                    ))}
                                </div>

                                <div className="space-y-4">
                                    <div className="flex items-center gap-2 mb-2">
                                        <div className="h-px flex-1 bg-[var(--border)]" />
                                        <h4 className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.3em] whitespace-nowrap">Core Questions & Feedback</h4>
                                        <div className="h-px flex-1 bg-[var(--border)]" />
                                    </div>

                                    <div className="space-y-3">
                                        {selectedQuiz.responses?.map((res, idx) => (
                                            <div key={idx} className={`p-5 rounded-2xl border transition-all ${res.is_correct ? 'bg-emerald-50/10 border-emerald-100/50' : 'bg-orange-50/10 border-orange-100/50'}`}>
                                                <div className="flex items-start justify-between gap-4 mb-4">
                                                    <div className="flex gap-3">
                                                        <div className={`w-8 h-8 shrink-0 rounded-lg flex items-center justify-center font-black text-[11px] shadow-sm ${res.is_correct ? 'bg-emerald-500 text-white' : 'bg-orange-500 text-white'}`}>{idx + 1}</div>
                                                        <h5 className="text-[13px] font-bold text-[var(--text-main)] leading-snug pt-1.5">{res.question}</h5>
                                                    </div>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pl-11">
                                                    <div className="p-3 bg-[var(--bg-card)] rounded-xl border border-[var(--border)]/60">
                                                        <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1">Your Intelligence Entry</p>
                                                        <p className="text-[12px] font-bold text-[var(--text-main)]">
                                                            {typeof res.user_answer === 'number' ? `Option ${String.fromCharCode(65 + res.user_answer)}` : res.user_answer || 'No response recorded'}
                                                        </p>
                                                    </div>
                                                    <div className="p-3 bg-[var(--bg-card)] rounded-xl border border-[var(--border)]/60 flex items-center justify-between">
                                                        <div>
                                                            <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1">Impact Score</p>
                                                            <p className="text-[12px] font-bold text-[var(--text-main)]">{res.marks_earned} / {res.total_marks}</p>
                                                        </div>
                                                        <div className={`p-1.5 rounded-lg ${res.is_correct ? 'bg-emerald-100 text-emerald-600' : 'bg-orange-100 text-orange-600'}`}>
                                                            {res.is_correct ? <CheckCircle2 size={14} /> : <X size={14} />}
                                                        </div>
                                                    </div>
                                                </div>

                                                {res.feedback && (
                                                    <div className="mt-3 ml-11 p-4 bg-indigo-50/50 rounded-2xl border border-indigo-100/50 relative overflow-hidden group/feedback">
                                                        <div className="absolute top-0 right-0 w-24 h-24 bg-indigo-500/5 rounded-full -mr-12 -mt-12 blur-2xl group-hover/feedback:bg-indigo-500/10 transition-colors" />
                                                        <div className="relative">
                                                            <div className="flex items-center gap-2 mb-2">
                                                                <Brain size={14} className="text-indigo-600" />
                                                                <span className="text-[10px] font-black text-indigo-700 uppercase tracking-widest">AI Evaluator: Reasoning & Suggestions</span>
                                                            </div>
                                                            <p className="text-[12px] font-bold text-indigo-900 leading-relaxed italic border-l-2 border-indigo-200 pl-4 py-1">
                                                                {res.feedback}
                                                            </p>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="p-6 border-t border-[var(--border)] bg-[var(--bg-card)] flex justify-end gap-4">
                                <button 
                                    onClick={() => setSelectedQuiz(null)}
                                    className="px-8 h-12 bg-black text-white rounded-[16px] font-black uppercase text-[11px] tracking-widest hover:scale-105 active:scale-95 transition-all shadow-lg"
                                >
                                    Dismiss Review
                                </button>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default MyReports;
