import type { ReactNode } from "react";

/** Public replay never imports private login forms or contacts identity APIs. */
export function IdentityProvider({ children }: { children: ReactNode }) { return <>{children}</>; }
export function useIdentity() { return { status: "authenticated" as const, user: undefined, generation: 0 }; }
