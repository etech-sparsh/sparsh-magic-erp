// Calendar-first period options. Ranges are computed client-side (local dates) and sent
// to the existing report APIs as a custom start/end range — so every option, including
// "Current Quarter" (which the backend period list doesn't name), works with no backend change.
export const PERIOD_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'this_week', label: 'This Week' },
  { value: 'last_week', label: 'Last Week' },
  { value: 'this_month', label: 'This Month' },
  { value: 'last_month', label: 'Last Month' },
  { value: 'this_quarter', label: 'This Quarter' },
  { value: 'last_quarter', label: 'Last Quarter' },
  { value: 'this_year', label: 'This Year' },
  { value: 'all_time', label: 'All Time' },
  { value: 'custom', label: 'Custom Range' },
];

const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const startISO = (d) => `${fmt(d)}T00:00:00`;
const endISO = (d) => `${fmt(d)}T23:59:59`;

// Returns { startDate, endDate } ISO strings, or null for all_time / incomplete custom.
export const computeRange = (period, customStart, customEnd) => {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const d = now.getDate();

  switch (period) {
    case 'today':
      return { startDate: startISO(now), endDate: endISO(now) };
    case 'yesterday': {
      const yd = new Date(y, m, d - 1);
      return { startDate: startISO(yd), endDate: endISO(yd) };
    }
    case 'this_week': {
      const dow = (now.getDay() + 6) % 7; // Monday = 0
      const mon = new Date(y, m, d - dow);
      const sun = new Date(y, m, d - dow + 6);
      return { startDate: startISO(mon), endDate: endISO(sun) };
    }
    case 'last_week': {
      const dow = (now.getDay() + 6) % 7;
      const mon = new Date(y, m, d - dow - 7);
      const sun = new Date(y, m, d - dow - 1);
      return { startDate: startISO(mon), endDate: endISO(sun) };
    }
    case 'this_month':
      return { startDate: startISO(new Date(y, m, 1)), endDate: endISO(new Date(y, m + 1, 0)) };
    case 'last_month':
      return { startDate: startISO(new Date(y, m - 1, 1)), endDate: endISO(new Date(y, m, 0)) };
    case 'this_quarter': {
      const q = Math.floor(m / 3);
      return { startDate: startISO(new Date(y, q * 3, 1)), endDate: endISO(new Date(y, q * 3 + 3, 0)) };
    }
    case 'last_quarter': {
      let q = Math.floor(m / 3) - 1;
      let yy = y;
      if (q < 0) { q = 3; yy = y - 1; }
      return { startDate: startISO(new Date(yy, q * 3, 1)), endDate: endISO(new Date(yy, q * 3 + 3, 0)) };
    }
    case 'this_year':
      return { startDate: startISO(new Date(y, 0, 1)), endDate: endISO(new Date(y, 11, 31)) };
    case 'custom':
      return (customStart && customEnd) ? { startDate: `${customStart}T00:00:00`, endDate: `${customEnd}T23:59:59` } : null;
    case 'all_time':
    default:
      return null;
  }
};

// Params for the report APIs given the current calendar selection.
export const rangeParams = (period, customStart, customEnd) => {
  const r = computeRange(period, customStart, customEnd);
  return r ? { period: 'custom', startDate: r.startDate, endDate: r.endDate } : {};
};

export const fmtDate = (v) => {
  if (!v) return '—';
  const dt = new Date(v);
  return Number.isNaN(dt.getTime()) ? '—' : dt.toLocaleDateString('en-US', { day: '2-digit', month: 'short', year: 'numeric' });
};
