import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../../../services/api';
import { CheckCircle2, Clock, AlertTriangle, Loader2, ShieldAlert, ClipboardCheck, ClipboardList } from 'lucide-react';
import ClientRatingForm from '../client/ClientRatingForm';
import ClientFeedbackForm from '../client/ClientFeedbackForm';

// ─── Assigned TPMS form (/f/:token) ───
// The landing page for the unique link mailed to a respondent when a form-scored activity is
// scheduled. It is a ROUTER, not a form: it resolves the token, then renders the existing React
// form component that the assignment points at. No form is reimplemented here, and there is no
// picker — the token alone decides, so the user cannot reach any form but their own.
//
//   accountability / ownership / culture  →  ClientRatingForm   (rating matrix UI)
//   implementation_feedback               →  ClientFeedbackForm (yes/no checklist UI)
//
// Access needs BOTH a signed-in session (the route sits behind PrivateRoute) and a token whose
// assignment names that same user; the backend enforces the second, so a forwarded link is
// useless to anyone else.
//
// The forms submit through the ordinary authenticated form APIs they have always used. This
// page only tells the backend the assignment is complete afterwards, so TPMS ▸ Form Mail Logs
// can show Submitted — there is no second submission path.

const Shell = ({ children }) => (
  <div className="max-w-4xl mx-auto w-full py-2">{children}</div>
);

const Notice = ({ icon: NoticeIcon, tone, title, detail }) => (
  <Shell>
    <div className="bg-[var(--bg-card)] rounded-[24px] border border-[var(--border)] p-8 text-center">
      <div className={`mx-auto w-14 h-14 rounded-2xl flex items-center justify-center mb-4 ${tone}`}>
        <NoticeIcon size={26} />
      </div>
      <h1 className="text-lg font-black text-[var(--text-main)] mb-1">{title}</h1>
      {detail && <p className="text-[13px] font-medium text-[var(--text-muted)]">{detail}</p>}
    </div>
  </Shell>
);

const AssignedFormPage = () => {
  const { token } = useParams();
  const [state, setState] = useState({ loading: true });
  const [done, setDone] = useState(false);

  // `alive` guards against the user navigating away mid-request — the same pattern the form
  // components below use — and keeps the setState out of the effect body itself.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get(`/forms/assigned/${token}`);
        if (alive) setState({ loading: false, data: res.data });
      } catch (err) {
        if (!alive) return;
        setState({
          loading: false,
          // The backend distinguishes 403 / 404 / 409 / 410 — surface its own message.
          error: err.response?.data?.detail || 'This form link could not be opened.',
          code: err.response?.status,
        });
      }
    })();
    return () => { alive = false; };
  }, [token]);

  // Close the assignment once the form itself has saved successfully. Failure here is
  // deliberately silent: the answers are already recorded, and the sweep/log lagging by one
  // click must never look to the user like their submission failed.
  const markSubmitted = useCallback(async () => {
    setDone(true);
    try { await api.post(`/forms/assigned/${token}/submitted`); } catch { /* answers are saved */ }
  }, [token]);

  if (state.loading) {
    return (
      <Shell>
        <div className="bg-[var(--bg-card)] rounded-[24px] border border-[var(--border)] p-8 flex items-center justify-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="animate-spin" size={18} />
          <span className="text-[13px] font-bold">Opening your form…</span>
        </div>
      </Shell>
    );
  }

  if (done || state.data?.state === 'submitted' || state.code === 409) {
    return <Notice icon={CheckCircle2} tone="bg-emerald-50 text-emerald-600"
      title="Thank you — your response has been recorded."
      detail="This form has been submitted and does not need to be filled again." />;
  }

  if (state.data?.state === 'expired' || state.code === 410) {
    return <Notice icon={Clock} tone="bg-amber-50 text-amber-600"
      title="This form link has expired."
      detail="The period this form belonged to has closed. Please contact your SMOps coordinator if you still need to submit it." />;
  }

  if (state.code === 403) {
    return <Notice icon={ShieldAlert} tone="bg-rose-50 text-rose-600"
      title="This form was assigned to someone else." detail={state.error} />;
  }

  if (state.error) {
    return <Notice icon={AlertTriangle} tone="bg-rose-50 text-rose-600"
      title="This link is not valid." detail={state.error} />;
  }

  const d = state.data;
  const isMatrix = (d.definition?.kind || '') === 'rating_matrix';
  const FormComponent = isMatrix ? ClientRatingForm : ClientFeedbackForm;

  return (
    <Shell>
      <FormComponent
        formType={d.form_type}
        icon={isMatrix ? ClipboardCheck : ClipboardList}
        lockedPeriod={d.period}
        onSubmitted={markSubmitted}
      />
    </Shell>
  );
};

export default AssignedFormPage;
