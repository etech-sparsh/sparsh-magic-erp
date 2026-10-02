const toNum = (v, d = 0) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : d;
};

const toInt = (v, d = 1) => {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : d;
};

export const sanitizeORMParameters = (params = []) =>
  params.map(p => ({
    ...p,
    weightage: toNum(p.weightage),
    subsections: (p.subsections || []).map(s => ({
      ...s,
      weightage: toNum(s.weightage),
      target: toNum(s.target),
      achievement: toNum(s.achievement),
      dayOfMonth: toInt(s.dayOfMonth, 1),
      auditChecklist: (s.auditChecklist || []).map(a => ({
        ...a,
        max_marks: toNum(a.max_marks, 5),
        obtained_marks: toNum(a.obtained_marks),
      })),
      teamEngagementChecklist: (s.teamEngagementChecklist || []).map(t => ({
        ...t,
        min_marks: toNum(t.min_marks),
      })),
      budgetAdherenceChecklist: (s.budgetAdherenceChecklist || []).map(b => ({
        ...b,
        rate: toNum(b.rate),
        target: toNum(b.target),
        actual: toNum(b.actual),
        gap: toNum(b.gap),
      })),
    })),
  }));
