import React, { useState, useEffect, useCallback } from 'react';
import {
  Building2, Users, Briefcase, GraduationCap, CalendarDays, Layers, BookOpen,
  ListTodo, CheckCircle2, Clock, Award, Percent,
} from 'lucide-react';
import { getEnterpriseOverview } from '../../services/reportApi';
import { motion } from 'framer-motion';

const Kpi = ({ label, value, icon: Icon, delay }) => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }}
    className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">{label}</span>
    </div>
    <p className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</p>
  </motion.div>
);

// Period-scoped KPI summary — reuses GET /reports/enterprise-overview. Cards only, no charts.
const SummaryCards = ({ params }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getEnterpriseOverview(params));
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
  }, [params]);

  useEffect(() => { load(); }, [load]);

  if (loading && !data) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
        {Array.from({ length: 14 }).map((_, i) => <div key={i} className="h-[86px] rounded-2xl bg-[var(--input-bg)] animate-pulse" />)}
      </div>
    );
  }
  if (!data) return null;

  const cards = [
    { label: 'Companies', value: data.totalCompanies, icon: Building2 },
    { label: 'Employees', value: data.totalUsers, icon: Users },
    { label: 'Coaches', value: data.totalCoaches, icon: Briefcase },
    { label: 'Learners', value: data.totalLearners, icon: GraduationCap },
    { label: 'Sessions', value: data.totalSessions, icon: CalendarDays },
    { label: 'Active Batches', value: data.activeBatches, icon: Layers },
    { label: 'Active Courses', value: data.activeCourses, icon: BookOpen },
    { label: 'Total Tasks', value: data.totalTasks, icon: ListTodo },
    { label: 'Completed', value: data.completedTasks, icon: CheckCircle2 },
    { label: 'Pending', value: data.pendingTasks, icon: Clock },
    { label: 'Avg Assessment', value: data.avgAssessmentScore != null ? `${data.avgAssessmentScore}%` : '—', icon: Award },
    { label: 'Attendance %', value: data.attendanceRate != null ? `${data.attendanceRate}%` : '—', icon: CalendarDays },
    { label: 'Completion %', value: data.completionRate != null ? `${data.completionRate}%` : '—', icon: Percent },
    { label: 'Performance', value: data.avgPerformanceScore, icon: Award },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
      {cards.map((c, i) => <Kpi key={c.label} {...c} delay={Math.min(i * 0.02, 0.25)} />)}
    </div>
  );
};

export default SummaryCards;
