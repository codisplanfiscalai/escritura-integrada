export const OVERVIEW_TAB_ID = 'dashboard';

// Protect the permanent tab in the state transition, not just in its markup.
export function removeWorkspaceTab(tabs, id) {
  if (id === OVERVIEW_TAB_ID || !tabs.includes(id)) return tabs;
  return tabs.filter(tab => tab !== id);
}
