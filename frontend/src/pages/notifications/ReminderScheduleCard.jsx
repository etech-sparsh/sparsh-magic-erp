import React, { useState } from 'react';
import { Clock, CheckCircle2, Play } from 'lucide-react';
import { Section } from '../../features/tpms/common/dashboardKit';
import { runReminderSweepNow, setReminderSchedule } from '../../services/notifyTemplatesApi';
import { Button } from './NtUi';
import { errMsg, inputCls, to12h } from './ntConfig';

const pad = (n) => String(n).padStart(2, '0');

/**
 * When the time-driven Delegation reminders go out.
 *
 * Its own card rather than a field on any one template: one clock governs every recurring
 * reminder, and putting it inside a per-trigger form would suggest each could have its own.
 */
const ReminderScheduleCard = ({ schedule, onSaved, onNotice, onError }) => {
  const [hour, setHour] = useState(schedule.hour);
  const [minute, setMinute] = useState(schedule.minute);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const dirty = hour !== schedule.hour || minute !== schedule.minute;

  const save = async () => {
    setSaving(true);
    try {
      const res = await setReminderSchedule(hour, minute);
      onNotice(`Reminders will go out at ${to12h(res.data.hour, res.data.minute)} IST from the next run.`);
      onSaved({ ...schedule, hour: res.data.hour, minute: res.data.minute });
    } catch (e) {
      onError(errMsg(e, 'Could not update the reminder time.'));
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true);
    try {
      const res = await runReminderSweepNow();
      onNotice(res.data.note);
    } catch (e) {
      onError(errMsg(e, 'Could not run the reminders.'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Section title="Daily reminder time" icon={Clock}
      subtitle={`Delegation reminders go out once a day at ${to12h(schedule.hour, schedule.minute)} IST · it is ${schedule.now_ist} IST now`}>
      <div className="px-5 py-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]">Send at (IST)</span>
          <div className="flex items-center gap-1.5">
            <select value={hour} onChange={(e) => setHour(Number(e.target.value))} className={`${inputCls} w-auto cursor-pointer`}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>{to12h(h, 0).replace(':00', '')}</option>
              ))}
            </select>
            <span className="text-[13px] font-bold text-[var(--text-muted)]">:</span>
            <select value={minute} onChange={(e) => setMinute(Number(e.target.value))} className={`${inputCls} w-auto cursor-pointer`}>
              {[0, 15, 30, 45].map((m) => <option key={m} value={m}>{pad(m)}</option>)}
            </select>
          </div>
        </div>
        <Button icon={CheckCircle2} busy={saving} disabled={!dirty} onClick={save}>
          {saving ? 'Saving…' : 'Save time'}
        </Button>
        <Button variant="outline" icon={Play} busy={running} onClick={runNow}
          title="Run today's reminders now. A reminder that already went out today will not repeat.">
          {running ? 'Running…' : "Send today's reminders now"}
        </Button>
        <p className="basis-full text-[11.5px] text-[var(--text-muted)] leading-relaxed">
          Daily Due, Weekly Due, Overdue Alert and Verification Chase follow this time. Every other
          event sends the moment it happens. Each reminder goes out at most once a day.
        </p>
      </div>
    </Section>
  );
};

export default ReminderScheduleCard;
