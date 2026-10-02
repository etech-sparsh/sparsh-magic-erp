import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BookOpen, CheckCircle2, Clock, Users, UserCheck, Award, Percent, Layers,
  Search, ChevronDown, Loader2, GraduationCap, BadgeCheck, CalendarDays,
  UserCog, FileDown, Building2, MoreVertical, Eye, TrendingUp,
} from 'lucide-react';
import { getLmsList, getLmsEmployees, downloadCsv } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

// Attendance-percentage color bands (spec): >=90 green, 75-89 yellow, 60-74 orange, <60 red.
const attColor = (rate) => {
  const r = Number(rate) || 0;
  if (r >= 90) return 'var(--accent-green)';
  if (r >= 75) return '#eab308';       // yellow
  if (r >= 60) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const ATT_STATUS_COLOR = {
  Excellent: 'var(--accent-green)', Good: '#eab308',
  Average: 'var(--accent-orange)', Poor: 'var(--accent-red)',
};

// Color-coded attendance % pill.
const AttPct = ({ value }) => (
  <span className="inline-block px-2 py-0.5 rounded-md text-[11px] font-black"
    style={{ color: attColor(value), background: `color-mix(in srgb, ${attColor(value)} 14%, transparent)` }}>
    {value ?? 0}%
  </span>
);

const Kpi = ({ label, value, icon: Icon }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">{label}</span>
    </div>
    <p className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</p>
  </div>
);

// Column sets rendered per Action → each is a real, focused view of the same live learner data.
const cellCls = 'px-3 py-2 text-[12px] font-bold text-[var(--text-main)]';
const LEARNER_VIEWS = {
  details: {
    label: 'Learner Details', min: 1150,
    cols: ['Learner', 'Company', 'Department', 'Sessions', 'Attended', 'Missed', 'Attendance %', 'Status', 'Completion %', 'Assessment', 'Score'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.email}</span></td>,
      <td key="co" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.company || '—'}</td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="s" className={cellCls}>{e.totalSessions ?? 0}</td>,
      <td key="a" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.sessionsAttended ?? 0}</td>,
      <td key="m" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">{e.sessionsMissed ?? 0}</td>,
      <td key="ap" className="px-3 py-2"><AttPct value={e.attendanceRate} /></td>,
      <td key="st" className="px-3 py-2 text-[11px] font-black" style={{ color: ATT_STATUS_COLOR[e.attendanceStatus] || 'var(--text-muted)' }}>{e.attendanceStatus || '—'}</td>,
      <td key="cr" className={cellCls}>{e.completionRate}%</td>,
      <td key="as" className={cellCls}>{e.avgAssessment}%</td>,
      <td key="sc" className="px-3 py-2 text-[13px] font-black" style={{ color: RATING_COLOR[e.rating] }}>{e.score}</td>,
    ],
  },
  attendance: {
    label: 'Attendance', min: 820,
    cols: ['Learner', 'Company', 'Department', 'Total Sessions', 'Attended', 'Missed', 'Attendance %', 'Status'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.email}</span></td>,
      <td key="co" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.company || '—'}</td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="s" className={cellCls}>{e.totalSessions ?? 0}</td>,
      <td key="a" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.sessionsAttended ?? 0}</td>,
      <td key="m" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">{e.sessionsMissed ?? 0}</td>,
      <td key="ap" className="px-3 py-2"><AttPct value={e.attendanceRate} /></td>,
      <td key="st" className="px-3 py-2 text-[11px] font-black" style={{ color: ATT_STATUS_COLOR[e.attendanceStatus] || 'var(--text-muted)' }}>{e.attendanceStatus || '—'}</td>,
    ],
  },
  progress: {
    label: 'Course Progress', min: 820,
    cols: ['Learner', 'Department', 'Assigned', 'Completed', 'Pending', 'Overdue', 'Completion %'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.email}</span></td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="ag" className={cellCls}>{e.assigned}</td>,
      <td key="cp" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">{e.completed}</td>,
      <td key="pd" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-orange)]">{e.pending}</td>,
      <td key="ov" className="px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">{e.overdue}</td>,
      <td key="cr" className="px-3 py-2"><AttPct value={e.completionRate} /></td>,
    ],
  },
  assessment: {
    label: 'Assessment Report', min: 720,
    cols: ['Learner', 'Company', 'Department', 'Avg Assessment %', 'Score', 'Rating'],
    render: (e) => [
      <td key="n" className={cellCls}>{e.name}<span className="block text-[10px] text-[var(--text-muted)]">{e.email}</span></td>,
      <td key="co" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.company || '—'}</td>,
      <td key="d" className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{e.department}</td>,
      <td key="as" className={cellCls}>{e.avgAssessment}%</td>,
      <td key="sc" className="px-3 py-2 text-[13px] font-black" style={{ color: RATING_COLOR[e.rating] }}>{e.score}</td>,
      <td key="rt" className="px-3 py-2 text-[11px] font-black" style={{ color: RATING_COLOR[e.rating] }}>{e.rating || '—'}</td>,
    ],
  },
};

// Learner rows shown when a course (LMS/batch) is expanded. `mode` selects which real view.
const LearnerRows = ({ courseId, params, mode = 'details' }) => {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    getLmsEmployees(courseId, { ...params, limit: 50 })
      .then((r) => { if (alive) setRows(r.items || []); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, [courseId, params]);

  const view = LEARNER_VIEWS[mode] || LEARNER_VIEWS.details;

  if (rows === null) return <div className="flex items-center gap-2 py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]"><Loader2 size={14} className="animate-spin" /> Loading learners…</div>;
  if (rows.length === 0) return <p className="py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]">No learners in this course.</p>;

  return (
    <div className="bg-[var(--bg-main)] rounded-xl border border-[var(--border)] m-2">
      <div className="px-3 pt-2 text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">{view.label}</div>
      <div className="overflow-x-auto">
        <table className="w-full text-left" style={{ minWidth: view.min }}>
          <thead>
            <tr className="border-b border-[var(--border)]">
              {view.cols.map((h) => (
                <th key={h} className="px-3 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id} className="border-b border-[var(--border)] last:border-0">{view.render(e)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const LmsReport = ({ params }) => {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [viewMode, setViewMode] = useState('details');
  const [menu, setMenu] = useState(null); // { id, x, y } — open Action menu, fixed-positioned
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await getLmsList({ ...params, search, limit: 300 });
      setCourses(res.items || []);
    } catch (e) { setError(true); }
    finally { setLoading(false); }
  }, [params, search]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); setExpanded(null); setMenu(null); }, [params, search]);

  // Open the expanded panel for a course in a specific real-data view.
  const openView = (id, mode) => {
    setViewMode(mode);
    setExpanded((prev) => (prev === id && viewMode === mode ? null : id));
    setMenu(null);
  };

  // Download this course's learner report (real data from the LMS employees API).
  const downloadCourseCsv = async (c) => {
    setMenu(null);
    try {
      const res = await getLmsEmployees(c.id, { ...params, limit: 1000 });
      const headers = ['Learner', 'Email', 'Company', 'Department', 'Total Sessions', 'Attended', 'Missed', 'Attendance %', 'Status', 'Completion %', 'Assessment %', 'Score', 'Rating'];
      const data = (res.items || []).map((e) => [
        e.name, e.email, e.company, e.department, e.totalSessions, e.sessionsAttended, e.sessionsMissed,
        `${e.attendanceRate}%`, e.attendanceStatus, `${e.completionRate}%`, `${e.avgAssessment}%`, e.score, e.rating,
      ]);
      downloadCsv(`lms_${(c.name || 'course').replace(/[^a-z0-9]+/gi, '_')}.csv`, headers, data);
    } catch (e) { /* handled globally */ }
  };

  // Actions available per course row. `c` is the course; each opens real learner data.
  const rowActions = (c) => [
    { key: 'details', label: 'View Details', icon: Eye, onClick: () => openView(c.id, 'details') },
    { key: 'attendance', label: 'View Attendance', icon: CalendarDays, onClick: () => openView(c.id, 'attendance') },
    { key: 'progress', label: 'View Course Progress', icon: TrendingUp, onClick: () => openView(c.id, 'progress') },
    { key: 'assessment', label: 'View Assessment Report', icon: Award, onClick: () => openView(c.id, 'assessment') },
    { key: 'download', label: 'Download Report', icon: FileDown, onClick: () => downloadCourseCsv(c) },
  ];

  // LMS summary cards — aggregated client-side from the real course list (no new API).
  const summary = useMemo(() => {
    const totalCourses = courses.reduce((s, c) => s + (c.coursesAssigned || 0), 0);
    const completedCourses = courses.reduce((s, c) => s + (c.coursesCompleted || 0), 0);
    const totalLearners = courses.reduce((s, c) => s + (c.totalUsers || 0), 0);
    const activeLearners = courses.reduce((s, c) => s + (c.activeUsers || 0), 0);
    const withScore = courses.filter((c) => c.avgScore != null);
    const avgScore = withScore.length ? Math.round(withScore.reduce((s, c) => s + c.avgScore, 0) / withScore.length) : 0;
    // Overall attendance: learner-weighted average of each course's avgAttendance
    // (only counting courses that actually have attendance records — no mock values).
    const attCourses = courses.filter((c) => (c.learnersWithAttendance || 0) > 0);
    const attWeight = attCourses.reduce((s, c) => s + c.learnersWithAttendance, 0);
    const attendanceRate = attWeight
      ? Math.round((attCourses.reduce((s, c) => s + c.avgAttendance * c.learnersWithAttendance, 0) / attWeight) * 10) / 10
      : 0;
    return {
      totalCourses,
      activeCourses: courses.filter((c) => c.status === 'active').length,
      completedCourses,
      inProgress: Math.max(0, totalCourses - completedCourses),
      totalLearners,
      activeLearners,
      avgScore,
      attendanceRate,
      completionRate: totalCourses ? Math.round((completedCourses / totalCourses) * 100) : 0,
    };
  }, [courses]);

  // Company-wise attendance — aggregated client-side from the course rows (each course row
  // carries its company + avgAttendance + learner counts). Batches spanning multiple companies
  // are grouped under their combined label.
  const companyAttendance = useMemo(() => {
    const map = new Map();
    courses.forEach((c) => {
      if (!(c.learnersWithAttendance > 0)) return;
      const key = c.company || '—';
      const g = map.get(key) || { company: key, learners: 0, weighted: 0, below75: 0, hi: 0, lo: 100 };
      g.learners += c.learnersWithAttendance;
      g.weighted += c.avgAttendance * c.learnersWithAttendance;
      g.below75 += c.learnersBelow75 || 0;
      g.hi = Math.max(g.hi, c.avgAttendance);
      g.lo = Math.min(g.lo, c.avgAttendance);
      map.set(key, g);
    });
    return [...map.values()]
      .map((g) => ({ ...g, avg: Math.round((g.weighted / g.learners) * 10) / 10 }))
      .sort((a, b) => b.avg - a.avg);
  }, [courses]);

  const exportAttendanceCsv = () => {
    const headers = ['Course', 'Company', 'Total Learners', 'Total Sessions', 'Avg Attendance %', 'Learners Below 75%', 'Completion %', 'Avg Score %'];
    const data = courses.map((c) => [
      c.name, c.company, c.totalUsers, c.coursesAssigned,
      `${c.avgAttendance ?? 0}%`, c.learnersBelow75 ?? 0, `${c.completionRate}%`, `${c.avgScore}%`,
    ]);
    downloadCsv('lms_attendance_report.csv', headers, data);
  };

  const paged = courses.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const cell = 'px-3 py-3 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap';

  const cards = [
    { label: 'Total Courses', value: summary.totalCourses, icon: BookOpen },
    { label: 'Active Courses', value: summary.activeCourses, icon: Layers },
    { label: 'Completed Courses', value: summary.completedCourses, icon: CheckCircle2 },
    { label: 'In Progress', value: summary.inProgress, icon: Clock },
    { label: 'Total Learners', value: summary.totalLearners, icon: Users },
    { label: 'Active Learners', value: summary.activeLearners, icon: UserCheck },
    { label: 'Completed Assessments', value: '—', icon: Award },
    { label: 'Pending Assessments', value: '—', icon: Clock },
    { label: 'Avg Assessment', value: `${summary.avgScore}%`, icon: Award },
    { label: 'Attendance Rate', value: `${summary.attendanceRate}%`, icon: UserCog },
    { label: 'Certificates', value: '—', icon: BadgeCheck },
    { label: 'Sessions Conducted', value: summary.totalCourses, icon: CalendarDays },
    { label: 'Completion Rate', value: `${summary.completionRate}%`, icon: Percent },
  ];

  return (
    <div className="space-y-5">
      {/* LMS summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
        {cards.map((c) => <Kpi key={c.label} {...c} />)}
      </div>

      {/* Company-wise attendance */}
      {companyAttendance.length > 0 && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
          <div className="flex items-center gap-2 p-5 border-b border-[var(--border)]">
            <Building2 size={16} className="text-[var(--accent-indigo)]" />
            <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">Company-wise Attendance</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[720px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  {['Company', 'Total Learners', 'Avg Attendance %', 'Highest %', 'Lowest %', 'Below 75%'].map((h) => (
                    <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {companyAttendance.map((g) => (
                  <tr key={g.company} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)]">
                    <td className="px-4 py-3 text-[12px] font-black text-[var(--text-main)]">{g.company}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-main)]">{g.learners}</td>
                    <td className="px-4 py-3"><AttPct value={g.avg} /></td>
                    <td className="px-4 py-3 text-[12px] font-bold" style={{ color: attColor(g.hi) }}>{g.hi}%</td>
                    <td className="px-4 py-3 text-[12px] font-bold" style={{ color: attColor(g.lo) }}>{g.lo}%</td>
                    <td className={`px-4 py-3 text-[12px] font-bold ${g.below75 ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>{g.below75}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Course-wise report */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
          <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">Course-wise Report</h3>
          <div className="flex items-center gap-2">
            <button onClick={exportAttendanceCsv} disabled={!courses.length}
              className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] disabled:opacity-40">
              <FileDown size={13} /> CSV
            </button>
            <div className="relative min-w-[220px]">
              <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search course..."
                className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>
          </div>
        </div>

        {error ? (
          <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--accent-red)]">Failed to load LMS report.</p>
        ) : loading ? (
          <div className="p-5 space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 rounded-xl bg-[var(--input-bg)] animate-pulse" />)}</div>
        ) : courses.length === 0 ? (
          <div className="py-16 text-center"><GraduationCap size={38} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No courses for this period.</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[1000px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">#</th>
                  {['Course Name', 'Total Learners', 'Active Learners', 'Completed', 'Completion %', 'Avg Score', 'Avg Attendance', 'Below 75%', 'Total Sessions'].map((h) => (
                    <th key={h} className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
                  ))}
                  <th className="px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((c, i) => {
                  const isOpen = expanded === c.id;
                  return (
                    <React.Fragment key={c.id}>
                      <tr onClick={() => { setViewMode('details'); setExpanded(isOpen ? null : c.id); }}
                        className={`border-b border-[var(--border)] cursor-pointer transition-colors ${isOpen ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                        <td className="px-3 py-3 text-[12px] font-black text-[var(--text-muted)]">{page * PAGE_SIZE + i + 1}</td>
                        <td className={`${cell} font-black`}>{c.name}</td>
                        <td className={cell}>{c.totalUsers}</td>
                        <td className={cell}>{c.activeUsers}</td>
                        <td className={`${cell} text-[var(--accent-green)]`}>{c.coursesCompleted}</td>
                        <td className={cell}>{c.completionRate}%</td>
                        <td className={cell}>{c.avgScore}%</td>
                        <td className="px-3 py-3"><AttPct value={c.avgAttendance} /></td>
                        <td className={`${cell} ${c.learnersBelow75 ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>{c.learnersBelow75 ?? 0}</td>
                        <td className={cell}>{c.coursesAssigned}</td>
                        <td className="px-3 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                          {(c.totalUsers || 0) === 0 ? (
                            <span className="text-[10px] font-bold text-[var(--text-muted)] italic whitespace-nowrap">No actions available</span>
                          ) : (
                            <div className="inline-flex items-center gap-1.5">
                              <ChevronDown size={16} className={`cursor-pointer text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-180 text-[var(--accent-indigo)]' : ''}`} onClick={() => { setViewMode('details'); setExpanded(isOpen ? null : c.id); }} />
                              <button title="Actions"
                                onClick={(ev) => {
                                  const r = ev.currentTarget.getBoundingClientRect();
                                  setMenu(menu?.id === c.id ? null : { id: c.id, x: r.right, y: r.bottom });
                                }}
                                className={`p-1.5 rounded-lg border transition-colors ${menu?.id === c.id ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--accent-indigo)] hover:bg-[var(--input-bg)]'}`}>
                                <MoreVertical size={15} />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-[var(--bg-main)]"><td colSpan={11} className="p-0"><LearnerRows courseId={c.id} params={params} mode={viewMode} /></td></tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {courses.length > PAGE_SIZE && (
          <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
            <p className="text-[11px] font-bold text-[var(--text-muted)]">Showing {page * PAGE_SIZE + 1} to {Math.min((page + 1) * PAGE_SIZE, courses.length)} of {courses.length} entries</p>
            <div className="flex items-center gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
              <button disabled={(page + 1) * PAGE_SIZE >= courses.length} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>

      {/* Row Action menu — fixed-positioned so it isn't clipped by the table's horizontal scroll. */}
      {menu && (() => {
        const course = courses.find((c) => c.id === menu.id);
        if (!course) return null;
        return (
          <>
            <div className="fixed inset-0 z-[190]" onClick={() => setMenu(null)} />
            <div className="fixed z-[200] w-56 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden py-1"
              style={{ top: menu.y + 6, left: Math.max(8, menu.x - 224) }}>
              <div className="px-3 py-2 border-b border-[var(--border)]">
                <p className="text-[11px] font-black text-[var(--text-main)] truncate">{course.name}</p>
                <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Actions</p>
              </div>
              {rowActions(course).map((a) => (
                <button key={a.key} onClick={a.onClick}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[12px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors text-left">
                  <a.icon size={15} className="text-[var(--accent-indigo)] shrink-0" />
                  {a.label}
                </button>
              ))}
            </div>
          </>
        );
      })()}
    </div>
  );
};

export default LmsReport;
