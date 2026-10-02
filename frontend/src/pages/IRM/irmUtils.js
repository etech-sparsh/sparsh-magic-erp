import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import { useAuth } from '../../context/AuthContext';

/* Shared helpers for the IRM pages. Plain .js (no JSX) so the react-refresh lint rule
   stays happy about the .jsx pages exporting only components. */

export const STAFF_ROLES = ['superadmin', 'admin'];
export const CLIENT_ROLES = ['clientadmin', 'clientuser'];
/* Mirrors CONFIG_ROLES / RECALC_ROLES in backend/app/routes/irm.py. The backend is the
   real gate — these only decide what the UI offers, so a hidden control and a rejected
   request can never disagree. */
export const CONFIG_ROLES = [...STAFF_ROLES, 'clientadmin'];
export const RECALC_ROLES = [...STAFF_ROLES, 'clientadmin'];

export const isStaff = (user) => STAFF_ROLES.includes(user?.role);
/** Internal staff, plus a company's own clientadmin for their own people. A clientuser
    never edits: they are the ones being scored. */
export const canEditWeightages = (user) => CONFIG_ROLES.includes(user?.role);
export const canRecalculate = (user) => RECALC_ROLES.includes(user?.role);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** 'YYYY-MM' for the current month — the default period everywhere. */
export const currentPeriod = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

/** 'YYYY-MM' → 'Aug 2026' (echoes the raw value back if it isn't a period). */
export const periodLabel = (period) => {
  const m = /^(\d{4})-(\d{2})$/.exec(String(period || ''));
  if (!m) return String(period || '');
  return `${MONTHS[Number(m[2]) - 1] || m[2]} ${m[1]}`;
};

/** The last `count` months, newest first, as {id, name} select options. */
export const periodOptions = (count = 12) => {
  const now = new Date();
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const id = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    return { id, name: periodLabel(id) };
  });
};

/** Percentages and scores render to 2dp but drop trailing zeros; null → '—'. */
export const fmtNum = (v, dash = '—') => {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  return String(Math.round(Number(v) * 100) / 100);
};

export const fmtPct = (v, dash = '—') => (
  v === null || v === undefined || Number.isNaN(v) ? dash : `${fmtNum(v)}%`
);

/** Score → dashboardKit tone. Kept in one place so tiles, pills and bars agree. */
export const scoreTone = (score) => {
  if (score === null || score === undefined) return 'plain';
  if (score >= 85) return 'green';
  if (score >= 70) return 'blue';
  if (score >= 50) return 'yellow';
  return 'red';
};

export const scoreColor = (score) => ({
  green: 'var(--accent-green)',
  blue: 'var(--accent-indigo)',
  yellow: 'var(--accent-yellow)',
  red: 'var(--accent-red)',
  plain: 'var(--text-muted)',
}[scoreTone(score)]);

/**
 * Company selection for the IRM pages.
 *
 * Internal staff pick a company (and need the list); client-side users are pinned to
 * their own by the backend, so they get no picker and no companies request.
 */
export const useIrmCompany = () => {
  const { user } = useAuth();
  const staff = isStaff(user);
  const [companies, setCompanies] = useState([]);
  // Only staff hold a selection; a client-side user's company is derived, never stored,
  // so switching accounts can't leave a stale id behind.
  const [picked, setPicked] = useState('');

  useEffect(() => {
    if (!staff) return undefined;
    let cancelled = false;
    api.get('/companies')
      .then((res) => {
        if (cancelled) return;
        const list = (Array.isArray(res?.data) ? res.data : [])
          .map((c) => ({ id: String(c._id || c.id || ''), name: c.name || 'Untitled' }))
          .filter((c) => c.id);
        list.sort((a, b) => a.name.localeCompare(b.name));
        setCompanies(list);
        // Land on the first company so the page has something to show immediately.
        setPicked((prev) => prev || list[0]?.id || '');
      })
      .catch(() => { if (!cancelled) setCompanies([]); });
    return () => { cancelled = true; };
  }, [staff]);

  const companyId = staff ? picked : (user?.company_id || '');
  return { user, staff, companies, companyId, setCompanyId: setPicked };
};

/** Read `detail` off an axios error, falling back to a caller-supplied message. */
export const errText = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  // Pydantic validation errors arrive as a list of {msg, loc, …}. `loc` is what names the
  // offending field — without it a missing-field 422 renders as a bare "Field required",
  // which says nothing about WHICH field and sends you looking in the wrong place.
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => {
      const msg = String(d?.msg || '').replace(/^Value error,\s*/, '');
      const field = (Array.isArray(d?.loc) ? d.loc : [])
        .filter((part) => typeof part === 'string' && part !== 'body')
        .pop();
      return field ? `${field}: ${msg}` : msg;
    }).join(' ');
  }
  return fallback;
};

/** Convenience: an async loader with loading/error state, re-run when `deps` change. */
export const useAsync = (loader, deps, { skip = false } = {}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!skip);
  const [error, setError] = useState('');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  const reload = useCallback(async () => {
    if (skip) { setLoading(false); return; }
    setLoading(true);
    setError('');
    try {
      setData(await run());
    } catch (e) {
      setError(errText(e, 'Something went wrong. Please try again.'));
    } finally {
      setLoading(false);
    }
  }, [run, skip]);

  useEffect(() => { reload(); }, [reload]);

  return useMemo(() => ({ data, setData, loading, error, setError, reload }),
    [data, loading, error, reload]);
};
