import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { canAccessTaskManagement, isClientSideUser, taskAccessDeniedMessage } from '../../utils/taskAccess';

// Route guard for the Task Management / Delegation module. Anyone without access who reaches
// a task URL directly gets a denial panel instead of the page (the backend also 403s every
// task API, so this is the UX layer of a defense-in-depth gate). A company user whose company
// has the Delegation toggle off is told the module isn't enabled, rather than being told the
// module is internal-only — for them it is a switch their Sparsh admin can flip.
const RequireTaskAccess = ({ children }) => {
  const { user } = useAuth();

  if (canAccessTaskManagement(user)) return children;

  const isCompanyUser = isClientSideUser(user);

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-16 h-16 rounded-2xl bg-[var(--accent-red-bg)] flex items-center justify-center text-[var(--accent-red)] mb-4">
        <ShieldAlert size={30} />
      </div>
      <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight mb-1">
        {isCompanyUser ? 'Module Not Enabled' : 'Access Denied'}
      </h1>
      <p className="text-[13px] font-bold text-[var(--text-muted)] max-w-md">{taskAccessDeniedMessage(user)}</p>
      <a href="/" className="mt-6 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest hover:opacity-90 transition-all">
        Back to Dashboard
      </a>
    </div>
  );
};

export default RequireTaskAccess;
