import React, { createContext, useContext, useMemo, useState } from 'react';

/**
 * SMOPS manages multiple companies. This context holds the currently-selected
 * company (plus the "All Companies" aggregate) and is shared by the SMOPS layout
 * header selector and every sub-module beneath it.
 *
 * Replace COMPANIES with an API fetch (e.g. /smops/companies) when ready.
 */
const COMPANIES = [
  { id: 'all',    name: 'All Companies', short: 'ALL' },
  { id: 'acme',   name: 'Acme Corp',     short: 'AC' },
  { id: 'nimbus', name: 'Nimbus Ltd',    short: 'NL' },
  { id: 'vertex', name: 'Vertex Health', short: 'VH' },
  { id: 'orbit',  name: 'Orbit Media',   short: 'OM' },
  { id: 'cobalt', name: 'Cobalt Bank',   short: 'CB' },
];

const CompanyContext = createContext(null);

export const CompanyProvider = ({ children }) => {
  const [companyId, setCompanyId] = useState(COMPANIES[0].id);
  const company = COMPANIES.find((c) => c.id === companyId) || COMPANIES[0];
  const isAll = companyId === 'all';

  const value = useMemo(
    () => ({ companies: COMPANIES, companyId, setCompanyId, company, isAll }),
    [companyId, company, isAll],
  );

  return <CompanyContext.Provider value={value}>{children}</CompanyContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components
export const useCompany = () => {
  const ctx = useContext(CompanyContext);
  if (!ctx) throw new Error('useCompany must be used within a CompanyProvider');
  return ctx;
};
