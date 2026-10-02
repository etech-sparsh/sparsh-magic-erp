import React, { useState, useEffect, useMemo } from 'react';
import { Calendar, CalendarRange, Layers, Calculator, FileText, Info, TrendingUp, TrendingDown } from 'lucide-react';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import api from '../../services/api';
import { motion } from 'framer-motion';

// Mirrors the scoring logic used in the ORM Designer (ORMPage.jsx).
const calculateScore = (sub, isReverse) => {
  const target = parseFloat(sub.target) || 0;
  const achievement = parseFloat(sub.achievement) || 0;
  const weightage = parseFloat(sub.weightage) || 0;
  if (!target) return 0;
  const score = isReverse
    ? (target / achievement) * weightage
    : (achievement / target) * weightage;
  return parseFloat(Math.min(score, weightage).toFixed(2));
};

const formatVal = (v, sub) => {
  const n = parseFloat(v);
  if (!Number.isFinite(n)) return '—';
  return sub?.isPercentage ? `${n}%` : n.toLocaleString();
};

// Target Achievement % = (Achievement / Target) * 100
const achievementPct = (sub) => {
  const target = parseFloat(sub.target) || 0;
  const achievement = parseFloat(sub.achievement) || 0;
  if (!target) return null;
  return parseFloat(((achievement / target) * 100).toFixed(2));
};

// Builds display rows + running totals from a parameters array.
const buildMatrix = (parameters) => {
  let grandWeight = 0;
  let grandScore = 0;
  const rows = parameters.map((param) => {
    const subs = param.subsections || [];
    let paramWeight = 0;
    let paramScore = 0;
    const subRows = subs.map((sub) => {
      const score = calculateScore(sub, param.isReverse);
      paramWeight += parseFloat(sub.weightage) || 0;
      paramScore += score;
      return { sub, score };
    });
    grandWeight += paramWeight;
    grandScore += paramScore;
    return { param, subRows, paramWeight, paramScore };
  });
  return { rows, grandWeight, grandScore };
};

const ORMReportTab = ({ companyId, companyName }) => {
  const [viewMode, setViewMode] = useState('monthly'); // 'monthly' | 'quarterly'
  const [loading, setLoading] = useState(false);
  const [parameters, setParameters] = useState([]);
  const [monthsIncluded, setMonthsIncluded] = useState(null); // quarterly: how many months had data

  const monthOptions = useMemo(() => {
    const opts = [];
    const now = new Date();
    for (let i = 0; i < 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const label = d.toLocaleString('default', { month: 'long', year: 'numeric' });
      opts.push({ value, label });
    }
    return opts;
  }, []);

  const quarterOptions = useMemo(() => {
    const opts = [];
    const now = new Date();
    let q = Math.floor(now.getMonth() / 3);
    let year = now.getFullYear();
    for (let i = 0; i < 4; i++) {
      const startMonth = q * 3;
      const periods = [0, 1, 2].map((m) => {
        const mm = startMonth + m;
        return `${year}-${String(mm + 1).padStart(2, '0')}`;
      });
      opts.push({ value: `${year}-Q${q + 1}`, label: `Q${q + 1} ${year}`, periods });
      q -= 1;
      if (q < 0) { q = 3; year -= 1; }
    }
    return opts;
  }, []);

  const [selectedMonth, setSelectedMonth] = useState(monthOptions[0]?.value);
  const [selectedQuarter, setSelectedQuarter] = useState(quarterOptions[0]?.value);

  const fetchMonthly = async (period) => {
    const res = await api.get(`/orm/${companyId}`, { params: { period } });
    setParameters(res.data.parameters || []);
    setMonthsIncluded(null);
  };

  // Quarterly: pull each month of the quarter and average target/achievement per
  // subsection across the months that actually have saved data.
  const fetchQuarterly = async (quarter) => {
    const opt = quarterOptions.find((o) => o.value === quarter);
    if (!opt) return;
    const responses = await Promise.all(
      opt.periods.map((p) =>
        api.get(`/orm/${companyId}`, { params: { period: p } })
          .then((r) => r.data)
          .catch(() => null)
      )
    );
    const withData = responses.filter((r) => r && r.has_month_data && (r.parameters || []).length > 0);
    const structure = (responses.find((r) => r && (r.parameters || []).length > 0) || {}).parameters || [];

    // Average each subsection's target/achievement over the data-bearing months.
    const merged = structure.map((param) => ({
      ...param,
      subsections: (param.subsections || []).map((sub) => {
        const samples = withData
          .map((r) => (r.parameters || []).find((p) => p.id === param.id))
          .filter(Boolean)
          .map((p) => (p.subsections || []).find((s) => s.id === sub.id))
          .filter(Boolean);
        if (samples.length === 0) return { ...sub, achievement: 0 };
        const avg = (key) =>
          samples.reduce((acc, s) => acc + (parseFloat(s[key]) || 0), 0) / samples.length;
        return {
          ...sub,
          target: parseFloat(avg('target').toFixed(2)),
          achievement: parseFloat(avg('achievement').toFixed(2)),
        };
      }),
    }));

    setParameters(merged);
    setMonthsIncluded(withData.length);
  };

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      try {
        if (viewMode === 'monthly') {
          await fetchMonthly(selectedMonth);
        } else {
          await fetchQuarterly(selectedQuarter);
        }
      } catch (err) {
        if (!cancelled) setParameters([]);
        console.error('Failed to load ORM report:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [viewMode, selectedMonth, selectedQuarter, companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { rows, grandWeight, grandScore } = useMemo(() => buildMatrix(parameters), [parameters]);

  const periodLabel = viewMode === 'monthly'
    ? monthOptions.find((o) => o.value === selectedMonth)?.label
    : quarterOptions.find((o) => o.value === selectedQuarter)?.label;

  const handleDownloadPDF = () => {
    const doc = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(14);
    doc.text('ORGANIZATION RESULT MATRIX (ORM)', pageWidth / 2, 36, { align: 'center' });
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(`${companyName || ''}  ·  ${periodLabel || ''}`, pageWidth / 2, 52, { align: 'center' });

    const body = [];
    rows.forEach(({ param, subRows, paramWeight, paramScore }) => {
      subRows.forEach(({ sub, score }) => {
        const pct = achievementPct(sub);
        body.push([
          param.name,
          sub.name,
          (parseFloat(sub.weightage) || 0).toFixed(1),
          formatVal(sub.target, sub),
          formatVal(sub.achievement, sub),
          pct === null ? '—' : `${pct}%`,
          score.toFixed(2),
        ]);
      });
      body.push([
        { content: `${param.name} Total`, styles: { fontStyle: 'bold', fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: paramWeight.toFixed(1), styles: { fontStyle: 'bold', fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: paramScore.toFixed(2), styles: { fontStyle: 'bold', fillColor: [232, 244, 232] } },
      ]);
    });
    body.push([
      { content: 'Grand Total', styles: { fontStyle: 'bold', fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: grandWeight.toFixed(1), styles: { fontStyle: 'bold', fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: grandScore.toFixed(2), styles: { fontStyle: 'bold', fillColor: [208, 230, 208] } },
    ]);

    autoTable(doc, {
      startY: 68,
      head: [['Five-Parameters', 'Subs', 'Weightage', 'Target', 'Achievement', 'Target Achi %', 'Score']],
      body,
      theme: 'grid',
      styles: { fontSize: 9, cellPadding: 4, lineColor: [180, 200, 180], lineWidth: 0.5, textColor: [40, 40, 40] },
      headStyles: { fillColor: [208, 230, 208], textColor: [20, 20, 20], fontStyle: 'bold' },
      columnStyles: {
        0: { cellWidth: 96 },
        1: { cellWidth: 80 },
        2: { cellWidth: 54, halign: 'center' },
        3: { cellWidth: 62, halign: 'right' },
        4: { cellWidth: 66, halign: 'right' },
        5: { cellWidth: 66, halign: 'right' },
        6: { cellWidth: 44, halign: 'center' },
      },
    });

    const safePeriod = (periodLabel || 'report').replace(/\s+/g, '_');
    doc.save(`ORM_${safePeriod}.pdf`);
  };

  const hasData = rows.some((r) => r.subRows.length > 0);

  return (
    <motion.div key="orm" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">
      {/* Controls */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5 flex flex-col lg:flex-row lg:items-center gap-4 justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Layers size={20} />
          </div>
          <div>
            <h3 className="text-[15px] font-bold text-[var(--text-main)]">Organization Result Matrix (ORM)</h3>
            <p className="text-[11px] text-[var(--text-muted)]">View month-wise or quarter-wise ORM report for {companyName}</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Monthly / Quarterly toggle */}
          <div className="flex gap-1 bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--border)]">
            {[
              { id: 'monthly', label: 'Monthly', icon: Calendar },
              { id: 'quarterly', label: 'Quarterly', icon: CalendarRange },
            ].map((m) => (
              <button
                key={m.id}
                onClick={() => setViewMode(m.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-bold transition-all ${
                  viewMode === m.id
                    ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                    : 'text-[var(--text-muted)] hover:bg-[var(--bg-card)]'
                }`}
              >
                <m.icon size={13} /> {m.label}
              </button>
            ))}
          </div>

          {/* Period selector */}
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)]">
            <Calendar size={14} className="text-[var(--accent-indigo)]" />
            {viewMode === 'monthly' ? (
              <select
                value={selectedMonth}
                onChange={(e) => setSelectedMonth(e.target.value)}
                className="bg-transparent text-[11px] font-bold text-[var(--text-main)] outline-none cursor-pointer"
              >
                {monthOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            ) : (
              <select
                value={selectedQuarter}
                onChange={(e) => setSelectedQuarter(e.target.value)}
                className="bg-transparent text-[11px] font-bold text-[var(--text-main)] outline-none cursor-pointer"
              >
                {quarterOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            )}
          </div>

          <button
            onClick={handleDownloadPDF}
            disabled={!hasData}
            className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <FileText size={14} /> Download PDF
          </button>
        </div>
      </div>

      {viewMode === 'quarterly' && monthsIncluded !== null && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-[var(--accent-yellow-bg)] border border-[var(--accent-yellow-border)] text-[var(--accent-yellow)] w-fit">
          <Info size={14} />
          <span className="text-[11px] font-bold">
            {monthsIncluded > 0
              ? `Quarterly view averages ${monthsIncluded} month${monthsIncluded > 1 ? 's' : ''} with recorded data.`
              : 'No recorded ORM data for this quarter yet.'}
          </span>
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
          <div className="flex items-center gap-2 mb-2">
            <Calculator size={16} className="text-[var(--accent-indigo)]" />
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Aggregate Score</span>
          </div>
          <div className="text-3xl font-black text-[var(--text-main)]">{grandScore.toFixed(2)} <span className="text-[var(--text-muted)] text-lg font-bold">/ 100</span></div>
          <div className="mt-3 h-2 bg-[var(--input-bg)] rounded-full overflow-hidden">
            <div className="h-full bg-[var(--accent-indigo)]" style={{ width: `${Math.min(grandScore, 100)}%` }} />
          </div>
        </div>
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
          <div className="flex items-center gap-2 mb-2">
            <Layers size={16} className="text-[var(--accent-green)]" />
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Allocation</span>
          </div>
          <div className="text-3xl font-black text-[var(--text-main)]">{grandWeight.toFixed(0)}<span className="text-[var(--text-muted)] text-lg font-bold">%</span></div>
        </div>
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
          <div className="flex items-center gap-2 mb-2">
            <Calendar size={16} className="text-[var(--accent-orange)]" />
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Period</span>
          </div>
          <div className="text-2xl font-black text-[var(--text-main)]">{periodLabel || '—'}</div>
        </div>
      </div>

      {/* Matrix */}
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin" />
        </div>
      ) : !hasData ? (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl py-20 text-center">
          <Layers size={36} className="mx-auto mb-3 text-[var(--text-muted)] opacity-40" />
          <p className="text-[13px] font-bold text-[var(--text-muted)]">No ORM data recorded for {periodLabel}.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {rows.map(({ param, subRows, paramWeight, paramScore }) => (
            <div key={param.id} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3.5 bg-[var(--input-bg)]/40 border-b border-[var(--border)]">
                <div className="flex items-center gap-3">
                  <h4 className="text-[14px] font-bold text-[var(--text-main)]">{param.name}</h4>
                  <span className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase border ${param.isReverse ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] border-[var(--accent-orange-border)]' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'}`}>
                    {param.isReverse ? 'Reverse Logic' : 'Standard Logic'}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-[11px] font-bold">
                  <span className="text-[var(--text-muted)]">Weight: <span className="text-[var(--accent-indigo)]">{paramWeight.toFixed(1)}%</span></span>
                  <span className="text-[var(--text-muted)]">Score: <span className="text-[var(--accent-green)]">{paramScore.toFixed(2)}</span></span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                      <th className="px-5 py-2.5 text-left text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Sub-Section</th>
                      <th className="px-5 py-2.5 text-left text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Weight</th>
                      <th className="px-5 py-2.5 text-right text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Target</th>
                      <th className="px-5 py-2.5 text-right text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Achievement</th>
                      <th className="px-5 py-2.5 text-right text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Target Achi %</th>
                      <th className="px-5 py-2.5 text-right text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Score</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {subRows.map(({ sub, score }) => {
                      const weight = parseFloat(sub.weightage) || 0;
                      const good = score >= weight * 0.9;
                      const pct = achievementPct(sub);
                      return (
                        <tr key={sub.id} className="hover:bg-[var(--table-hover)] transition-all">
                          <td className="px-5 py-3">
                            <span className="text-[13px] font-bold text-[var(--text-main)]">{sub.name}</span>
                            {sub.unitName && <span className="ml-2 text-[10px] font-bold text-[var(--text-muted)] uppercase">· {sub.unitName}</span>}
                          </td>
                          <td className="px-5 py-3 text-[12px] font-bold text-[var(--accent-indigo)]">{weight}%</td>
                          <td className="px-5 py-3 text-right text-[12px] font-medium text-[var(--text-muted)]">{formatVal(sub.target, sub)}</td>
                          <td className="px-5 py-3 text-right text-[12px] font-bold text-[var(--text-main)]">{formatVal(sub.achievement, sub)}</td>
                          <td className="px-5 py-3 text-right text-[12px] font-bold text-[var(--accent-indigo)]">{pct === null ? '—' : `${pct}%`}</td>
                          <td className="px-5 py-3 text-right">
                            <span className={`inline-flex items-center gap-1 text-[12px] font-black ${good ? 'text-[var(--accent-green)]' : 'text-[var(--accent-orange)]'}`}>
                              {score.toFixed(2)}
                              {good ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
};

export default ORMReportTab;
