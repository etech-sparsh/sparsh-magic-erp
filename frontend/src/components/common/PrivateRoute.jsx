import React, { useCallback, useState } from 'react';
import { motion } from 'framer-motion';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import Sidebar from '../layout/Sidebar';
import Navbar from '../layout/Navbar';

const PrivateRoute = ({ children, hideLayout = false }) => {
  const { user } = useAuth();
  const location = useLocation();
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  // Width the fixed sidebar currently occupies, reported by the sidebar itself. The rail below
  // tracks it so an expanded sidebar PUSHES the page instead of covering it.
  const [railWidth, setRailWidth] = useState(72);
  // Stable identity — Sidebar reports width from an effect, so a new function each render
  // would re-fire it on every parent render.
  const handleWidthChange = useCallback((w) => setRailWidth(w), []);

  if (!user) {
    // Carry where they were heading so Login can send them back there. Without this a mailed
    // deep link (e.g. an assigned TPMS form at /f/<token>) is lost at the login redirect and
    // the user lands on the dashboard with no way to find the form. `replace` keeps the
    // unauthenticated URL out of history.
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (hideLayout) {
    return (
      <div className="min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
        {children}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
      {/* Sidebar - Now fixed/floating */}
      <Sidebar isMobileOpen={isMobileSidebarOpen} setIsMobileOpen={setIsMobileSidebarOpen}
        onWidthChange={handleWidthChange} />
      
      {/* Backdrop for mobile */}
      {isMobileSidebarOpen && (
        <div 
          className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 md:hidden animate-in fade-in duration-200"
          onClick={() => setIsMobileSidebarOpen(false)}
        />
      )}
      
      {/* Rail that reserves the fixed sidebar's space. It tracks the sidebar's real width
          (72 collapsed / 240 expanded) with the same spring, so hovering the sidebar pushes
          the page across instead of overlapping it. */}
      <motion.div
        initial={false}
        animate={{ width: railWidth }}
        transition={{ type: 'spring', stiffness: 400, damping: 40 }}
        className="h-screen shrink-0 hidden md:block"
      />

      {/* Main Content Area. min-w-0 lets it actually shrink as the rail grows — without it a
          flex child refuses to go below its content width and the page overflows sideways. */}
      <div className="flex-1 min-w-0 flex flex-col relative w-full h-screen overflow-y-auto no-scrollbar scroll-smooth">
        {/* Top Navbar */}
        <Navbar onMenuClick={() => setIsMobileSidebarOpen(true)} />

        {/* Page Content */}
        <main className="flex-1 px-4 sm:px-6 py-6 w-full">
          <div className="max-w-[1600px] mx-auto space-y-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};

export default PrivateRoute;
