/** Sidebar is a projection, never the authority for routes or permissions. */
export interface SidebarSection {
  id: string;
  label: string;
  collapsible: boolean;
  paths: string[];
}

const localOnly = new Set(['/models', '/data-pools', '/platform', '/learning', '/compute']);
export function sidebarSections(publicMode: boolean): SidebarSection[] {
  return [
    { id: 'daily', label: '当前项目', collapsible: false, paths: ['/workspace', '/command-center', '/data-pools', '/models', '/capa'] },
    { id: 'records', label: '项目记录', collapsible: true, paths: ['/cases', '/evidence', '/runs', '/lineage'] },
    { id: 'tools', label: '更多工具', collapsible: true, paths: ['/platform', '/learning', '/compute'] },
    { id: 'delivery', label: '交付与帮助', collapsible: true, paths: ['/governance', '/review', '/start', '/pilot'] },
  ].map(group => ({ ...group, paths: group.paths.filter(p => !publicMode || !localOnly.has(p)) }))
    .filter(group => group.paths.length > 0);
}

export function workbenchTabKey(actorId: string | undefined, publicMode: boolean): string {
  return `workbench:open-tabs:v2:${publicMode ? 'replay' : 'local'}:${encodeURIComponent(actorId || 'anonymous')}`;
}

export function validWorkbenchTabs(value: unknown, publicMode: boolean): string[] {
  const known = new Set([...sidebarSections(publicMode).flatMap(g => g.paths), '/settings', '/account', '/integrations']);
  if (!Array.isArray(value)) return ['/workspace'];
  const result = value.filter((href): href is string => {
    if (typeof href !== 'string' || href.length > 2048 || !href.startsWith('/') || href.startsWith('//') || /[\\\x00-\x1f]/.test(href)) return false;
    const rawPath = href.split(/[?#]/, 1)[0];
    if (new URL(href, 'http://workbench.local').pathname !== rawPath) return false;
    return known.has(rawPath) || /^\/cases\/[^/]+$/.test(rawPath);
  });
  const unique = [...new Set(result)].slice(-7);
  return unique.length ? unique : ['/workspace'];
}
