/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ how a status is SHOWN.

   The backend keeps five cycle states, five link states, six delivery states and three
   score states. That is four vocabularies for one workflow, and three of them use the
   words "pending" and "sent" for different things — so a screen showing all of them made
   the reader translate before they could act.

   This module is the single place that turns backend state into what a person reads.
   Nothing here changes behaviour: every backend field, transition, retry rule and
   anonymity guard is untouched, and no status value is renamed at the source. It only
   decides what to display.

   The four user-facing vocabularies:

     Cycle       Draft → Open → Closed → Published
     Invitation  Pending → Sent → Submitted / Expired   (+ Send failed)
     Delivery    none — folded into the invitation
     Score       Score available / Not enough responses / Not published

   Pure functions, no React import, so they can be unit-tested with plain node.
   ───────────────────────────────────────────────────────────── */

/* ── Cycle ──────────────────────────────────────────────────
   `computed` is deliberately NOT a user-facing state. It means "closed, and the scores
   are frozen" — a step HR takes on the way to publishing, not a different phase of the
   window. It stays in the database, keeps its transitions and still drives the freeze;
   it simply reads as Closed, with the action on the row saying what can happen next. */
export const CYCLE_LABELS = {
  draft: 'Draft',
  open: 'Open',
  closed: 'Closed',
  computed: 'Closed',
  published: 'Published',
};

export const cycleLabel = (status) => CYCLE_LABELS[status] || 'Draft';

/** True when a closed cycle already holds frozen scores — the difference between
 *  "Compute" and "Publish" being the next action. Not a status of its own. */
export const isScoreReady = (status) => status === 'computed';

/** One line saying what this cycle is doing, for the row beneath the chip. */
export const cycleHint = (status) => ({
  draft: 'Being set up. Feedback links can be built but nothing is sent yet.',
  open: 'Collecting feedback.',
  closed: 'Window shut. Compute the scores when you are ready.',
  computed: 'Window shut. Scores are calculated and ready to release.',
  published: 'Scores released to leaders and their reporting managers.',
}[status] || '');

/* ── Invitation ─────────────────────────────────────────────
   `opened` is not shown. Knowing a giver opened the form tells the reader nothing they
   can act on — the action is the same as for Sent: wait, or chase — so it reads as Sent
   and `opened_at` stays in the database for tracking.

   A failed send is its own row state rather than a second status column. It must never
   read as Sent: the mail did not arrive, and the only useful response is to retry. */
export const INVITE_PENDING = 'pending';
export const INVITE_SENT = 'sent';
export const INVITE_SUBMITTED = 'submitted';
export const INVITE_EXPIRED = 'expired';
export const INVITE_FAILED = 'failed';

/**
 * The single invitation state to show for one assignment row.
 * @param {object} row - assignment as the API returns it (`status`, `wa_status`).
 * Delivery failure outranks the link state, because a link reported Pending after a
 * failed send looks like nobody has pressed send yet.
 *
 * `email_status` is still read as a fallback for rows written before Leadership moved to
 * WhatsApp — those invitations really did fail, and dropping the check would quietly
 * relabel them Pending.
 */
export const inviteState = (row) => {
  const link = row?.status || INVITE_PENDING;
  if (link === INVITE_SUBMITTED) return INVITE_SUBMITTED;   // finished business
  if (link === INVITE_EXPIRED) return INVITE_EXPIRED;
  const delivery = row?.wa_status || row?.email_status;
  if (delivery === 'failed' || delivery === 'unreachable') return INVITE_FAILED;
  if (link === 'opened') return INVITE_SENT;                // opened is not shown
  return link === INVITE_SENT ? INVITE_SENT : INVITE_PENDING;
};

export const INVITE_LABELS = {
  pending: 'Pending',
  sent: 'Sent',
  submitted: 'Submitted',
  expired: 'Expired',
  failed: 'Send failed',
};

export const inviteLabel = (row) => INVITE_LABELS[inviteState(row)];

export const inviteTone = (row) => ({
  submitted: 'green',
  sent: 'blue',
  pending: 'yellow',
  expired: 'plain',
  failed: 'red',
}[inviteState(row)] || 'plain');

/** Whether this row should offer a Retry. A submitted invitation never does. */
export const canRetryInvite = (row) => inviteState(row) === INVITE_FAILED;

/** Why the send failed, for a tooltip. Empty unless it actually failed. */
export const inviteError = (row) =>
  (inviteState(row) === INVITE_FAILED && (row?.wa_error || row?.email_error)) || '';

/* ── Score ──────────────────────────────────────────────────
   Three outcomes, no more. `leadership_score` stays null whenever a number is not
   available — it is never shown as 0, which would read as a real and very bad score. */
export const SCORE_LABELS = {
  scored: 'Score available',
  awaiting_responses: 'Not enough responses',
  not_published: 'Not published',
};

export const scoreState = (row) => {
  const s = row?.state;
  if (s && SCORE_LABELS[s]) return s;
  return row?.leadership_score === null || row?.leadership_score === undefined
    ? 'awaiting_responses'
    : 'scored';
};

export const scoreLabel = (row) => SCORE_LABELS[scoreState(row)];

export const scoreStateTone = (row) => ({
  scored: 'green',
  awaiting_responses: 'yellow',
  not_published: 'plain',
}[scoreState(row)] || 'plain');

/** The explanation under a missing score, so nobody reads it as a failure. */
export const scoreHint = (row, minResponses = 3) => ({
  scored: '',
  awaiting_responses: `Needs at least ${minResponses} responses before a score is shown.`,
  not_published: 'Visible to the leader once the cycle is published.',
}[scoreState(row)] || '');

/** A relation group held back because too few people in it replied. Not a status —
 *  a property of one row of the breakdown. */
export const groupWithheldNote = (group) =>
  group?.withheld ? 'Too few responses in this group to show separately' : '';
