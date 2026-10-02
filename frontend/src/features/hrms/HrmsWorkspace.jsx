import React from 'react';
import { Outlet } from 'react-router-dom';
import HrmsWorkspaceBar from './common/HrmsWorkspaceBar';

/**
 * HRMS ▸ module layout.
 *
 * Nothing but chrome: the workspace bar (identity + pipeline tabs) above whatever screen
 * the router resolved. It carries no state, no data and no guard of its own — RequireHrms
 * already wraps this — so mounting it changes where the tabs render, never what a route
 * does or who may reach it.
 *
 * The bar renders itself as null outside the recruitment pipeline, so the people and
 * master screens keep their plain page header.
 */
const HrmsWorkspace = () => (
  // One `space-y` of its own rather than sitting as two siblings in the shell's `space-y-8`:
  // the bar labels the screen directly beneath it, and 32px of air read as two unrelated
  // blocks.
  <div className="space-y-5">
    <HrmsWorkspaceBar />
    <Outlet />
  </div>
);

export default HrmsWorkspace;
