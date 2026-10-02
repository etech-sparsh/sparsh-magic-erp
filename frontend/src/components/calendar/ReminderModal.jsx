import React, { useState, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, Plus, Trash2, Bell, Mail, MessageSquare, Clock, CheckCircle } from 'lucide-react';

// offset_minutes is what's actually persisted (see Reminder model in calendar_event.py);
// offset_unit is UI-only (silently dropped by the backend's pydantic model on save) so a
// reminder edited/reloaded later re-derives its display unit from offset_minutes via inferUnit.
const UNIT_MINUTES = { Minutes: 1, Hours: 60, Days: 1440 };
const inferUnit = (mins) => {
    if (mins && mins % 1440 === 0) return 'Days';
    if (mins && mins % 60 === 0) return 'Hours';
    return 'Minutes';
};

// Exported so read-only views (e.g. the task View screen) describe a reminder exactly the way
// this editor does, instead of re-deriving the unit and drifting from it.
export const describeReminder = (r) => {
    const unit = r?.offset_unit || inferUnit(r?.offset_minutes);
    const amount = Math.round((r?.offset_minutes || 0) / UNIT_MINUTES[unit]);
    const when = `${amount} ${amount === 1 ? unit.replace(/s$/, '') : unit} ${r?.timing_type || 'before'}`;
    const channel = r?.reminder_type === 'both' ? 'Email + WhatsApp'
        : r?.reminder_type === 'whatsapp' ? 'WhatsApp' : 'Email';
    return { when, channel };
};

const ReminderModal = ({ isOpen, onClose, reminders, onApply }) => {
    const [localReminders, setLocalReminders] = useState([]);

    useEffect(() => {
        if (isOpen) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setLocalReminders((reminders || []).map(r => ({ ...r, offset_unit: r.offset_unit || inferUnit(r.offset_minutes) })));
        }
    }, [isOpen, reminders]);

    const addReminder = () => {
        setLocalReminders([...localReminders, {
            id: Date.now().toString(),
            reminder_type: 'both',
            timing_type: 'before',
            offset_minutes: 10,
            offset_unit: 'Minutes',
            sent: false,
            parent_type: 'event' // will be set correctly on save
        }]);
    };

    const removeReminder = (id) => {
        setLocalReminders(localReminders.filter(r => r.id !== id));
    };

    const updateReminder = (id, fields) => {
        setLocalReminders(localReminders.map(r => r.id === id ? { ...r, ...fields } : r));
    };

    const handleApply = () => {
        onApply(localReminders);
        onClose();
    };

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
                <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
                    className="bg-white w-full max-w-md rounded-[32px] shadow-2xl relative overflow-hidden flex flex-col border border-gray-100"
                    style={{ color: '#1a202c' }}
                >
                    <div className="px-8 py-6 border-b border-gray-100 flex items-center justify-between" style={{ backgroundColor: '#f9f9f9' }}>
                       <div className="flex items-center gap-3">
                           <div className="p-2 bg-orange-100 text-orange-600 rounded-xl"><Bell size={20}/></div>
                           <h3 className="text-lg font-black text-gray-800 uppercase tracking-tight">Set Reminders</h3>
                       </div>
                       <button onClick={onClose} className="p-2 hover:bg-gray-200 rounded-full transition-all text-gray-400"> <X size={24}/> </button>
                    </div>

                    <div className="p-8 max-h-[60vh] overflow-y-auto no-scrollbar space-y-6" style={{ backgroundColor: 'white' }}>
                        {localReminders.length === 0 && (
                            <div className="py-12 flex flex-col items-center justify-center text-gray-400 rounded-3xl border border-dashed border-gray-200" style={{ backgroundColor: '#fdfdfd' }}>
                                <Bell size={40} className="mb-3 opacity-20"/>
                                <p className="text-sm font-medium">No reminders configured yet.</p>
                            </div>
                        )}
                        
                        {localReminders.map((r, idx) => (
                            <motion.div layout key={r.id || idx} className="p-6 bg-white border border-gray-100 rounded-[24px] shadow-sm space-y-5 relative group">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="w-6 h-6 rounded-full bg-emerald-500 text-white text-[10px] flex items-center justify-center font-bold">{idx + 1}</span>
                                        <span className="text-xs font-black text-gray-400 uppercase tracking-widest">Reminder {idx + 1}</span>
                                    </div>
                                    <button onClick={() => removeReminder(r.id)} className="text-red-400 hover:text-red-600 p-1.5 hover:bg-red-50 transition-all rounded-lg"> <Trash2 size={16}/> </button>
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-gray-400 uppercase px-1">Type</label>
                                         <select value={r.reminder_type} onChange={e => updateReminder(r.id, {reminder_type: e.target.value})}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm font-bold outline-none"
                                            style={{ backgroundColor: '#f3f4f6', color: '#1f2937' }}>
                                            <option value="email">📧 Email</option>
                                            <option value="whatsapp">💬 WhatsApp</option>
                                            <option value="both">⚡ Both</option>
                                         </select>
                                     </div>
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-gray-400 uppercase px-1">Timing</label>
                                         <select value={r.timing_type} onChange={e => updateReminder(r.id, {timing_type: e.target.value})}
                                            className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm font-bold outline-none"
                                            style={{ backgroundColor: '#f3f4f6', color: '#1f2937' }}>
                                            <option value="before">Before</option>
                                            <option value="after">After</option>
                                         </select>
                                     </div>
                                </div>

                                 <div className="space-y-1.5">
                                    <label className="text-[10px] font-black text-gray-400 uppercase px-1">Offset (Time Amount)</label>
                                    <div className="flex flex-col gap-3">
                                        <div className="flex items-center gap-3">
                                            <input type="number" min="1"
                                                value={Math.round(r.offset_minutes / UNIT_MINUTES[r.offset_unit || 'Minutes'])}
                                                onChange={e => updateReminder(r.id, {offset_minutes: (parseInt(e.target.value) || 0) * UNIT_MINUTES[r.offset_unit || 'Minutes']})}
                                                className="flex-1 px-4 py-2.5 border border-gray-200 rounded-xl text-sm font-bold outline-none"
                                                style={{ backgroundColor: '#f3f4f6', color: '#1f2937' }} />
                                            <select value={r.offset_unit || 'Minutes'}
                                                onChange={e => {
                                                    const amount = Math.round(r.offset_minutes / UNIT_MINUTES[r.offset_unit || 'Minutes']);
                                                    updateReminder(r.id, {offset_unit: e.target.value, offset_minutes: amount * UNIT_MINUTES[e.target.value]});
                                                }}
                                                className="px-3 py-2.5 border border-gray-200 rounded-xl text-[11px] font-black uppercase outline-none"
                                                style={{ backgroundColor: '#f3f4f6', color: '#1f2937' }}>
                                                <option value="Minutes">Minutes</option>
                                                <option value="Hours">Hours</option>
                                                <option value="Days">Days</option>
                                            </select>
                                        </div>
                                        <div className="flex flex-wrap gap-2">
                                            {[
                                                {l: '5m', v: 5, unit: 'Minutes'}, {l: '15m', v: 15, unit: 'Minutes'}, {l: '30m', v: 30, unit: 'Minutes'},
                                                {l: '1h', v: 60, unit: 'Hours'}, {l: '2h', v: 120, unit: 'Hours'}, {l: '1d', v: 1440, unit: 'Days'}, {l: '2d', v: 2880, unit: 'Days'}
                                            ].map(opt => (
                                                <button key={opt.l} onClick={() => updateReminder(r.id, {offset_minutes: opt.v, offset_unit: opt.unit})}
                                                    className={`px-3 py-2 text-[10px] font-black rounded-lg border transition-all ${r.offset_minutes == opt.v ? 'bg-emerald-500 text-white border-emerald-500' : 'bg-gray-100 text-gray-400 border-gray-200 hover:border-emerald-200'}`}
                                                    style={r.offset_minutes == opt.v ? {} : { color: '#9ca3af', backgroundColor: '#f3f4f6' }}>
                                                    {opt.l}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </motion.div>
                        ))}
                    </div>

                    <div className="p-8 flex items-center justify-between gap-4" style={{ backgroundColor: '#f9f9f9', borderTop: '1px solid #eee' }}>
                        <button onClick={addReminder} className="flex items-center gap-2 px-6 py-3 border border-gray-200 text-gray-700 rounded-2xl text-xs font-black hover:border-emerald-500 hover:text-emerald-500 transition-all shadow-sm" style={{ backgroundColor: 'white' }}>
                            <Plus size={16}/> ADD MORE
                        </button>
                        <button onClick={handleApply} className="flex items-center gap-2 bg-gradient-to-r from-orange-500 to-orange-600 text-white px-8 py-3 rounded-2xl text-xs font-black shadow-lg shadow-orange-500/30 hover:scale-105 active:scale-95 transition-all uppercase tracking-widest">
                            <CheckCircle size={18}/> Apply Changes
                        </button>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    );
};

export default ReminderModal;
