/* Unit tests for the simplified Leadership status vocabulary.
   Plain node:  npm run test:status      (no test framework, no new dependencies) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  cycleLabel, cycleHint, isScoreReady,
  inviteState, inviteLabel, inviteTone, canRetryInvite, inviteError,
  scoreState, scoreLabel, scoreHint, groupWithheldNote,
} from './leadershipStatus.js';

/* ── Cycle: four user-facing states ───────────────────────── */

test('cycle shows only Draft / Open / Closed / Published', () => {
  const shown = ['draft', 'open', 'closed', 'computed', 'published'].map(cycleLabel);
  assert.deepEqual([...new Set(shown)], ['Draft', 'Open', 'Closed', 'Published']);
});

test('computed reads as Closed, never as its own status', () => {
  assert.equal(cycleLabel('computed'), 'Closed');
  assert.equal(cycleLabel('computed'), cycleLabel('closed'));
  assert.ok(!Object.values({ c: cycleLabel('computed') }).includes('Computed'));
});

test('computed is still distinguishable internally, for the next action', () => {
  assert.equal(isScoreReady('computed'), true);
  assert.equal(isScoreReady('closed'), false);
  // ...and the hint differs, so the row still explains itself.
  assert.notEqual(cycleHint('computed'), cycleHint('closed'));
  assert.match(cycleHint('computed'), /ready to release/);
});

test('published is the terminal label', () => {
  assert.equal(cycleLabel('published'), 'Published');
});

test('an unknown cycle status falls back to Draft rather than blank', () => {
  assert.equal(cycleLabel(undefined), 'Draft');
  assert.equal(cycleLabel('nonsense'), 'Draft');
});

/* ── Invitation: pending → sent → submitted / expired ─────── */

test('opened is not a user-facing invitation status', () => {
  assert.equal(inviteState({ status: 'opened' }), 'sent');
  assert.equal(inviteLabel({ status: 'opened' }), 'Sent');
  assert.ok(!Object.values(['pending', 'sent', 'opened', 'submitted', 'expired']
    .map((status) => inviteLabel({ status }))).includes('Opened'));
});

test('the four normal invitation states map straight through', () => {
  assert.equal(inviteLabel({ status: 'pending' }), 'Pending');
  assert.equal(inviteLabel({ status: 'sent', wa_status: 'sent' }), 'Sent');
  assert.equal(inviteLabel({ status: 'submitted' }), 'Submitted');
  assert.equal(inviteLabel({ status: 'expired' }), 'Expired');
});

test('a failed send is never shown as Sent', () => {
  const failed = { status: 'pending', wa_status: 'failed', wa_error: 'Delivery failed' };
  assert.equal(inviteState(failed), 'failed');
  assert.equal(inviteLabel(failed), 'Send failed');
  assert.notEqual(inviteLabel(failed), 'Sent');
});

test('a failed send offers Retry and surfaces the reason', () => {
  const failed = { status: 'pending', wa_status: 'failed', wa_error: 'Mailbox full' };
  assert.equal(canRetryInvite(failed), true);
  assert.equal(inviteError(failed), 'Mailbox full');
});

test('a successful send offers no Retry and no error text', () => {
  const sent = { status: 'sent', wa_status: 'sent' };
  assert.equal(canRetryInvite(sent), false);
  assert.equal(inviteError(sent), '');
});

test('submitted outranks a stale failure - finished business is never Send failed', () => {
  const row = { status: 'submitted', wa_status: 'failed', wa_error: 'old bounce' };
  assert.equal(inviteLabel(row), 'Submitted');
  assert.equal(canRetryInvite(row), false);
});

test('expired outranks a failure too', () => {
  assert.equal(inviteLabel({ status: 'expired', wa_status: 'failed' }), 'Expired');
});

test('delivery status is not a separate family - it only colours the invitation', () => {
  assert.equal(inviteTone({ status: 'pending', wa_status: 'failed' }), 'red');
  assert.equal(inviteTone({ status: 'sent', wa_status: 'sent' }), 'blue');
  assert.equal(inviteTone({ status: 'submitted' }), 'green');
});

test('a missing row does not crash the table', () => {
  assert.equal(inviteLabel(undefined), 'Pending');
  assert.equal(inviteLabel({}), 'Pending');
});

/* ── Score: three outcomes ────────────────────────────────── */

test('score has exactly three user-facing outcomes', () => {
  assert.equal(scoreLabel({ state: 'scored', leadership_score: 65 }), 'Score available');
  assert.equal(scoreLabel({ state: 'awaiting_responses' }), 'Not enough responses');
  assert.equal(scoreLabel({ state: 'not_published' }), 'Not published');
});

test('a null score is never read as zero', () => {
  const row = { state: 'awaiting_responses', leadership_score: null };
  assert.equal(scoreState(row), 'awaiting_responses');
  assert.equal(row.leadership_score, null);
  assert.notEqual(row.leadership_score, 0);
});

test('a genuine zero-ish score is still Score available', () => {
  assert.equal(scoreState({ state: 'scored', leadership_score: 20 }), 'scored');
});

test('a row with no state falls back on whether a number exists', () => {
  assert.equal(scoreState({ leadership_score: 65 }), 'scored');
  assert.equal(scoreState({ leadership_score: null }), 'awaiting_responses');
});

test('the min-responses rule is stated in the hint, and stays 3', () => {
  assert.match(scoreHint({ state: 'awaiting_responses' }), /at least 3 responses/);
  assert.match(scoreHint({ state: 'not_published' }), /published/);
  assert.equal(scoreHint({ state: 'scored' }), '');
});

test('a withheld relation group explains itself without a new status', () => {
  assert.match(groupWithheldNote({ withheld: true }), /Too few responses/);
  assert.equal(groupWithheldNote({ withheld: false }), '');
});
