import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useHrms } from '../HrmsContext';
import {
  getClientCompanies, getClientRequisitions, getClientScorecards,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ Client Hiring ▸ the non-component half of the shared kit.
 *
 * Split from `clientKit.jsx` for the same reason `internalKit.js` is split from its own
 * `.jsx`: a module that exports both components and plain values defeats fast refresh, so
 * the constants and the hook live here and the components live next door.
 */

/** Every client-track status, toned by what it means rather than by where it sits. */
export const CLIENT_TONE = {
  // Requisition
  'Need Mapping': 'warn',
  'Manpower Requisition': 'warn',
  'Pending Feasibility': 'warn',
  // Scorecard
  Draft: 'neutral',
  'Pending Internal Review': 'warn',
  'Pending Client Approval': 'warn',
  // Offer -- the salary deviation. 'warn' because it is somebody's move, 'bad'
  // because a refusal ends this offer and sends the candidate to the pool.
  'Pending Salary Deviation': 'warn',
  'Deviation Rejected': 'bad',
  // Candidate
  Sourced: 'neutral',
  Screened: 'neutral',
  'Telephonic Passed': 'good',
  'Telephonic Failed': 'bad',
  Shortlisted: 'good',
  'Shared with Client': 'warn',
  'Client Approved': 'good',
  'Client Rejected': 'bad',
  Assessment: 'neutral',
  'Assessment Reviewed': 'neutral',
  Interview: 'neutral',
  Selected: 'good',
  'Offer Released': 'neutral',
  'Offer Accepted': 'good',
  'Offer Declined': 'bad',
  // Assessment
  Sent: 'neutral',
  Submitted: 'warn',
  Scored: 'neutral',
  'Reviewed by Client': 'good',
  // Interview
  Scheduled: 'neutral',
  Conducted: 'neutral',
  'Selected by Client': 'good',
  'Rejected by Client': 'bad',
  // Offer
  'Pending Verification': 'warn',
  Released: 'good',
  Accepted: 'good',
  Declined: 'bad',
  // Joining
  'Pre-boarding': 'warn',
  Joined: 'good',
  Completed: 'good',
  'Dropped Out': 'bad',
  // Reference check outcomes
  Positive: 'good',
  Mixed: 'warn',
  Negative: 'bad',
  // Shared
  Approved: 'good',
  Rejected: 'bad',
  Closed: 'neutral',
  Withdrawn: 'neutral',
};

/**
 * Which client company the Client Hiring screens are reading.
 *
 * NOT the same thing as `useHrms().scope`. That is the HRMS TENANT — on an in-house system
 * it resolves to Sparsh Magic, the one company that is not a client — so a stage screen
 * scoped by it showed Sparsh staff an empty list while the board beside it counted the
 * client's real records. Two different questions that happened to share a parameter name.
 *
 * The workspace provides this; a screen mounted on its own falls back to the HRMS scope,
 * which is correct for a client-side user because the server pins them to their own
 * company regardless of what is sent.
 */
export const ClientScopeContext = createContext(null);

export const useClientScope = () => {
  const provided = useContext(ClientScopeContext);
  const { scope } = useHrms();
  return provided ?? scope;
};


/**
 * Load one client-track collection for the tenant in scope.
 *
 * Sparsh staff with no company selected still load — the server answers across every
 * client for them. A client-side user with no company is a state that should not exist,
 * but if it happens the screen says nothing rather than asking for everybody's data.
 */
export const useClientList = (fetcher, key, extraParams) => {
  const { companyId, isInternal } = useHrms();
  const scope = useClientScope();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const params = JSON.stringify(extraParams || {});
  const load = useCallback(async () => {
    if (!companyId && !isInternal) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await fetcher({ ...scope, ...(extraParams || {}), limit: 200 });
      setRows(data?.[key] || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'That could not be loaded.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, isInternal, key, JSON.stringify(scope), params]);

  useEffect(() => { load(); }, [load]);

  return { rows, loading, error, reload: load, setRows };
};


/**
 * The client companies this viewer may look at.
 *
 * The shared HRMS company selector cannot serve the client track. It lists companies with
 * the HRMS module enabled, which on an in-house system means Sparsh Magic itself -- so on
 * a Client Hiring screen it offered "Sparsh Magic", the one company that is NOT a client.
 * This asks the client track's own endpoint instead, which answers with the client
 * companies and pins a client-side caller to their own.
 */
export const useClientCompanies = () => {
  const { isInternal } = useHrms();
  const [clients, setClients] = useState([]);
  const [anyEnabled, setAnyEnabled] = useState(true);
  const [picked, setPicked] = useState('');

  useEffect(() => {
    let live = true;
    getClientCompanies({})
      .then(({ data }) => {
        if (!live) return;
        const rows = data?.client_companies || [];
        setClients(rows);
        setAnyEnabled(!!data?.any_enabled);
        // Open on a client whose engagement has actually started, falling back to the
        // first. Defaulting to whoever sorts first alphabetically lands on an empty
        // board whenever that company has nothing, which reads as "Client Hiring is
        // empty" rather than "this one client is".
        setPicked((cur) => cur
          || (rows.find((r) => r.has_records) || rows[0] || {}).id
          || '');
      })
      .catch(() => { if (live) { setClients([]); setAnyEnabled(false); } });
    return () => { live = false; };
  }, []);

  const pickedName = (clients.find((c) => c.id === picked) || {}).name || '';

  return { clients, anyEnabled, picked, setPicked, pickedName, isInternal };
};


/**
 * Requisitions that can actually carry a candidate or a posting.
 *
 * NOT simply "approved requisitions". Sourcing and advertising are both gated on an
 * APPROVED SCORECARD (`assert_sourcing_allowed`), so a picker listing every approved
 * requisition offers rows the server then refuses with a 409 — the user picks one, gets an
 * error, and has no way to tell which of the others would have worked.
 *
 * Two requests rather than one: the requisition list carries no scorecard status, and
 * adding one to it would put a second stage's state on a first stage's record.
 */
export const useSourceableRequisitions = (scope, { enabled = true } = {}) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(enabled);

  const key = JSON.stringify(scope || {});
  const load = useCallback(async () => {
    if (!enabled) { setLoading(false); return; }
    setLoading(true);
    try {
      const [reqRes, scRes] = await Promise.all([
        getClientRequisitions({ ...(scope || {}), status: 'Approved', limit: 200 }),
        getClientScorecards({ ...(scope || {}), status: 'Approved', limit: 200 }),
      ]);
      const agreed = new Set(
        (scRes.data?.client_scorecards || []).map((s) => s.cr_no).filter(Boolean));
      setRows((reqRes.data?.client_requisitions || [])
        .filter((r) => agreed.has(r.cr_no)));
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key]);

  useEffect(() => { load(); }, [load]);

  return { requisitions: rows, loading };
};
