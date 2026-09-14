/** Public static replay has no account credential state or login transport. */
const snapshot = Object.freeze({ user: undefined, generation: 0 });
export function getIdentitySessionSnapshot() { return snapshot; }
export function subscribeIdentitySession(_listener: () => void) { return () => {}; }
