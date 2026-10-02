import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { 
  Users, Building2, Calendar, Target, 
  TrendingUp, Activity, Plus, Clock, 
  ChevronRight, ArrowUpRight, Zap
} from 'lucide-react';
import { motion } from 'framer-motion';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, BarChart, Bar,
  PieChart, Pie, Cell, Legend
} from 'recharts';

const Dashboard = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [stats, setStats] = useState({
    registered_entities: 0,
    active_batches: 0,
    strategic_learners: 0,
    session_velocity: 0
  });
  const [pulseData, setPulseData] = useState([]);
  const [mixData, setMixData] = useState([]);
  const [upcomingEvents, setUpcomingEvents] = useState([]);
  const [teamMembers, setTeamMembers] = useState([]);
  const [_loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const role = user?.role?.toLowerCase();
      const isStaffRole = ['superadmin', 'admin', 'coach'].includes(role);

      const [statsRes, eventRes, teamRes] = await Promise.all([
        api.get('/dashboard/stats'),
        api.get('/calendar/events').catch(() => ({ data: [] })),
        !isStaffRole && user?.company_id 
            ? api.get(`/companies/${user.company_id}/users?active_only=true`).catch(() => ({ data: [] }))
            : Promise.resolve({ data: [] })
      ]);
      
      setStats(statsRes.data.kpis);
      setPulseData(statsRes.data.operational_pulse);
      setMixData(statsRes.data.session_mix);
      setTeamMembers(teamRes.data || []);

      setUpcomingEvents(eventRes.data
        .filter(e => new Date(e.start) >= new Date())
        .sort((a, b) => new Date(a.start) - new Date(b.start))
        .slice(0, 5)
      );
    } catch (err) {
      console.error("Dashboard fetch error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const role = user?.role?.toLowerCase();
  const isAdmin = ['superadmin', 'admin', 'coach'].includes(role);

  const canReadCompanies = user?.role === 'superadmin' || user?.permissions?.companies?.read;
  const canReadBatches = user?.role === 'superadmin' || user?.permissions?.batches?.read;
  const canReadUsers = user?.role === 'superadmin' || user?.permissions?.users?.read;
  const canReadLogs = user?.role === 'superadmin' || user?.permissions?.logs?.read;

  const statsTiles = isAdmin ? [
    ...(canReadCompanies ? [{ label: 'Registered Entities', value: stats.registered_entities, icon: Building2, color: 'var(--accent-indigo)', trend: 'Live', sub: 'total companies' }] : []),
    ...(canReadBatches ? [{ label: 'Active Batches', value: stats.active_batches, icon: Zap, color: 'var(--accent-orange)', trend: 'Active', sub: 'in progress' }] : []),
    ...(canReadUsers ? [{ label: 'Strategic Learners', value: stats.strategic_learners, icon: Users, color: 'var(--accent-green)', trend: 'Active', sub: 'onboarded' }] : []),
    ...(canReadLogs ? [{ label: 'Session Velocity', value: stats.session_velocity, icon: Activity, color: 'var(--accent-red)', trend: '30 Days', sub: 'completed sessions' }] : [])
  ] : [
    { label: 'Team Magnitude', value: stats.strategic_learners, icon: Users, color: 'var(--accent-indigo)', trend: 'My Company', sub: 'active nodes' },
    { label: 'Attendance Pulse', value: `${stats.attendance_rate}%`, icon: Target, color: 'var(--accent-green)', trend: 'Overall', sub: 'participation rate' },
    { label: 'Batch Lifecycle', value: stats.active_batches, icon: Zap, color: 'var(--accent-orange)', trend: 'Active', sub: 'program batches' },
    { label: 'Sessions Ingested', value: stats.session_velocity, icon: Activity, color: 'var(--accent-red)', trend: '30 Days', sub: 'completed track' }
  ];

  return (
    <div className="space-y-8 pb-10">
      {/* Header section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">Executive Overview</h1>
          <p className="text-[14px] text-[var(--text-muted)] font-bold">Welcome back, {user?.full_name}. Here is your organizational pulse.</p>
        </div>
      </div>

      {/* KPI Tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {statsTiles.map((tile, i) => (
          <motion.div 
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
            key={tile.label} className="bg-[var(--bg-card)] p-6 rounded-3xl border border-[var(--border)] shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all group"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="p-3 rounded-2xl bg-[var(--input-bg)] text-[var(--text-main)] group-hover:bg-[var(--accent-indigo-bg)] group-hover:text-[var(--accent-indigo)] transition-colors">
                <tile.icon size={24} />
              </div>
              <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] text-[10px] font-black uppercase tracking-widest">
                <ArrowUpRight size={12}/> {tile.trend}
              </div>
            </div>
            <div className="space-y-1">
                <h3 className="text-3xl font-black text-[var(--text-main)]">{tile.value}</h3>
                <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wider">{tile.label}</p>
                <p className="text-[10px] text-[var(--text-muted)] opacity-60 font-bold">{tile.sub}</p>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Middle Row: Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm flex flex-col h-[450px]">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h3 className="text-xl font-black text-[var(--text-main)] uppercase italic tracking-tight">System Pulse</h3>
              <p className="text-[12px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">Completion Velocity & Neural Activity (14-Day Trend)</p>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl">
               <div className="w-2 h-2 rounded-full bg-[var(--accent-indigo)] animate-pulse"></div>
               <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Live Flow</span>
            </div>
          </div>
          <div className="flex-1 w-full min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={pulseData}>
                <defs>
                  <linearGradient id="colorSessions" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-indigo)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--accent-indigo)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900}} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900}} />
                <Tooltip 
                  contentStyle={{ borderRadius: '24px', border: '1px solid var(--border)', background: 'var(--bg-card)', boxShadow: '0 20px 50px rgba(0,0,0,0.1)', padding: '12px 20px' }}
                  itemStyle={{ fontSize: '13px', fontWeight: 900, color: 'var(--accent-indigo)' }}
                  cursor={{ stroke: 'var(--accent-indigo)', strokeWidth: 1, strokeDasharray: '5 5' }}
                />
                <Area type="monotone" dataKey="sessions" stroke="var(--accent-indigo)" strokeWidth={4} fillOpacity={1} fill="url(#colorSessions)" animationDuration={1500} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm flex flex-col h-[450px]">
          <div className="mb-6">
            <h3 className="text-xl font-black text-[var(--text-main)] uppercase italic tracking-tight">Coaching Mix</h3>
            <p className="text-[12px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">Distribution by Segment</p>
          </div>
          <div className="flex-1 w-full flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={mixData} innerRadius={80} outerRadius={110} paddingAngle={10} dataKey="value" stroke="none" animationBegin={0} animationDuration={1800}>
                  {mixData.map((entry, index) => <Cell key={`cell-${index}`} fill={entry.color} />)}
                </Pie>
                <Tooltip 
                   contentStyle={{ borderRadius: '20px', border: 'none', boxShadow: '0 10px 30px rgba(0,0,0,0.1)' }}
                   itemStyle={{ fontSize: '11px', fontWeight: 900 }}
                />
                <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.1em' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Operational Timeline */}
        <div className="lg:col-span-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm">
            <div className="flex items-center justify-between mb-8">
                <h3 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2 uppercase italic tracking-tight"><Clock size={22} className="text-[var(--accent-indigo)]"/> Operational Timeline</h3>
                <button onClick={() => navigate('/calendar')} className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-widest px-4 py-2 bg-[var(--accent-indigo-bg)] rounded-xl hover:opacity-80 transition-all">Full Calendar</button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {upcomingEvents.length > 0 ? upcomingEvents.map((ev, i) => (
                    <div key={ev.id} onClick={() => navigate(`/sessions/${ev.id}`)} className="flex items-center gap-4 p-5 bg-[var(--input-bg)] rounded-2xl border border-transparent hover:border-[var(--border)] hover:bg-white transition-all group cursor-pointer shadow-sm hover:shadow-md">
                         <div className="w-14 h-14 flex flex-col items-center justify-center bg-white rounded-2xl border border-[var(--border)] group-hover:border-[var(--accent-indigo)] transition-all flex-shrink-0">
                             <span className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-tighter">{new Date(ev.start).toLocaleString('en-US', { month: 'short' })}</span>
                             <span className="text-[18px] font-black text-[var(--text-main)] leading-none">{new Date(ev.start).getDate()}</span>
                         </div>
                         <div className="min-w-0">
                             <h4 className="text-[13px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-all truncate uppercase italic">{ev.title}</h4>
                             <p className="text-[11px] font-bold text-[var(--text-muted)] flex items-center gap-1 mt-0.5"><Clock size={12}/> {new Date(ev.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {ev.type}</p>
                         </div>
                    </div>
                )) : (
                    <div className="col-span-full py-10 text-center space-y-3 opacity-30">
                        <Calendar size={32} className="mx-auto" />
                        <p className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">No sessions scheduled.</p>
                    </div>
                )}
            </div>
        </div>

        {/* My Team (Learners only) */}
        {!isAdmin && (
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm flex flex-col">
                <div className="flex items-center justify-between mb-8">
                    <h3 className="text-xl font-black text-[var(--text-main)] uppercase italic tracking-tight">Company Ecosystem</h3>
                    <button onClick={() => navigate('/team')} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all"> <ChevronRight size={20}/> </button>
                </div>
                <div className="space-y-4 flex-1 overflow-y-auto no-scrollbar max-h-[300px]">
                    {teamMembers.length > 0 ? teamMembers.slice(0, 6).map((m, i) => (
                        <div key={m._id} onClick={() => navigate(`/members/${m._id}`)} className="flex items-center justify-between p-4 bg-[var(--input-bg)] rounded-2xl hover:bg-white border border-transparent hover:border-[var(--border)] transition-all cursor-pointer group">
                             <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-xl bg-white border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)] font-black text-[12px] group-hover:scale-110 transition-all">
                                    {m.full_name?.charAt(0) || m.first_name?.charAt(0) || '?'}
                                </div>
                                <div>
                                    <p className="text-[13px] font-black text-[var(--text-main)]">{m.full_name || m.first_name}</p>
                                    <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase opacity-60">{m.designation || 'Specialist'}</p>
                                </div>
                             </div>
                             <div className={`w-2 h-2 rounded-full ${m.is_active !== false ? 'bg-green-500' : 'bg-red-500'}`} />
                        </div>
                    )) : (
                        <div className="py-10 text-center opacity-20">
                            <Users size={32} className="mx-auto mb-2" />
                            <p className="text-[10px] font-black uppercase tracking-widest">No nodes detected</p>
                        </div>
                    )}
                </div>
                {teamMembers.length > 6 && (
                    <button onClick={() => navigate('/team')} className="mt-4 w-full py-3 border border-[var(--border)] rounded-xl text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest hover:bg-[var(--input-bg)] transition-all">
                        View Network (+{teamMembers.length - 6})
                    </button>
                )}
            </div>
        )}

        {isAdmin && (
            <div className="bg-[var(--accent-indigo)] rounded-[32px] p-8 text-white relative overflow-hidden group shadow-2xl shadow-indigo-500/20">
                <div className="absolute inset-0 bg-gradient-to-br from-white/10 to-transparent pointer-events-none" />
                <Zap size={48} className="text-white/20 mb-4 group-hover:scale-110 group-hover:rotate-12 transition-all duration-500" />
                <h3 className="text-xl font-black mb-2 tracking-tight uppercase">System Insight</h3>
                <p className="text-[13px] font-medium opacity-80 leading-relaxed">Organizational metadata is being synchronized in real-time. Last pulse detected from secure node.</p>
                {canReadUsers && (
                    <button onClick={() => navigate('/admin/users')} className="mt-8 w-full py-3 bg-white text-[var(--accent-indigo)] rounded-2xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:scale-[1.02] active:scale-[0.98] transition-all">Staff Registry</button>
                )}
            </div>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
