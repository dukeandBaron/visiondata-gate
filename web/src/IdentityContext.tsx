import { createContext, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { changeIdentityPassword, getIdentityStatus, identityErrorMessage, loginIdentity, logoutIdentity,
  registerIdentity, setupIdentity, type IdentityLoginInput, type IdentityLoginResult, type IdentityRegistrationInput,
  type IdentityStatus } from "./data/identityApi";
import { clearIdentitySession, getIdentitySessionSnapshot, setIdentitySession,
  subscribeIdentitySession, type IdentityPublicUser } from "./identitySession";
import "./styles/identity.css";

export type IdentityPhase = "loading" | "setup" | "login" | "authenticated" | "error";
interface IdentityContextValue {
  status: IdentityPhase;
  user: Readonly<IdentityPublicUser> | undefined;
  generation: number;
  configuration: IdentityStatus | undefined;
  busy: boolean;
  error: string | undefined;
  notice: string | undefined;
  refresh(): Promise<void>;
  login(input: IdentityLoginInput): Promise<void>;
  setup(input: IdentityRegistrationInput): Promise<void>;
  register(input: IdentityRegistrationInput): Promise<void>;
  logout(): Promise<void>;
  password(input: { current_password: string; new_password: string }): Promise<void>;
}
const IdentityContext = createContext<IdentityContextValue | undefined>(undefined);

export function IdentityProvider({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(subscribeIdentitySession, getIdentitySessionSnapshot, getIdentitySessionSnapshot);
  const [phase, setPhase] = useState<IdentityPhase>("loading");
  const [configuration, setConfiguration] = useState<IdentityStatus>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [expiresAt, setExpiresAt] = useState<string>();
  const inFlight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    const requestEpoch = ++epoch.current;
    setPhase("loading"); setError(undefined);
    try {
      const next = await getIdentityStatus();
      if (!mounted.current || requestEpoch !== epoch.current) return;
      setConfiguration(next);
      setPhase(next.setup_required ? "setup" : "login");
    } catch (failure) {
      if (!mounted.current || requestEpoch !== epoch.current) return;
      setError(identityErrorMessage(failure)); setPhase("error");
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; epoch.current += 1; };
  }, [refresh]);

  useEffect(() => {
    if (!session.user || !expiresAt) return;
    const generation = session.generation;
    const remaining = Date.parse(expiresAt) - Date.now();
    const timer = window.setTimeout(() => {
      if (getIdentitySessionSnapshot().generation !== generation) return;
      clearIdentitySession(); setPhase("login"); setNotice("会话已到期，请重新登录。");
    }, Math.max(0, Math.min(remaining, 2_147_483_647)));
    return () => window.clearTimeout(timer);
  }, [session, expiresAt]);

  const run = useCallback(async (operation: () => Promise<void>, ambiguousSetup = false) => {
    if (inFlight.current) return;
    inFlight.current = true; epoch.current += 1; setBusy(true); setError(undefined); setNotice(undefined);
    try { await operation(); } catch (failure) {
      if (mounted.current) {
        setError(identityErrorMessage(failure));
        if (ambiguousSetup) setPhase("error");
      }
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }, []);

  const establish = useCallback((result: IdentityLoginResult, expectedGeneration: number) => {
    if (!mounted.current) return;
    if (getIdentitySessionSnapshot().generation !== expectedGeneration) {
      setPhase("login"); setNotice("会话状态已变化，已忽略先前的登录结果。请重新登录。");
      return;
    }
    setIdentitySession(result.user, result.access_token);
    setExpiresAt(result.expires_at); setPhase("login");
    setConfiguration({ setup_required: false, identity_required: true,
      registration_policy: "ADMIN_APPROVAL", authentication_mode: "USER_SESSION", startup_capability_required: true });
  }, []);
  const login = useCallback((input: IdentityLoginInput) => run(async () => {
    const generation = getIdentitySessionSnapshot().generation;
    establish(await loginIdentity(input), generation);
  }), [run, establish]);
  const setup = useCallback((input: IdentityRegistrationInput) => run(async () => {
    const generation = getIdentitySessionSnapshot().generation;
    establish(await setupIdentity(input), generation);
  }, true), [run, establish]);
  const register = useCallback((input: IdentityRegistrationInput) => run(async () => {
    await registerIdentity(input);
    if (mounted.current) { setPhase("login"); setNotice("注册申请已登记，当前状态为待管理员审批。尚未登录，也没有获得工作区权限。"); }
  }), [run]);
  const logout = useCallback(() => run(async () => {
    try { await logoutIdentity(); } finally {
      clearIdentitySession();
      if (mounted.current) { setExpiresAt(undefined); setPhase("login"); setNotice("本页会话已清除。刷新页面或再次进入时需要重新登录。"); }
    }
  }), [run]);
  const password = useCallback((input: { current_password: string; new_password: string }) => run(async () => {
    await changeIdentityPassword(input);
    clearIdentitySession();
    if (mounted.current) { setExpiresAt(undefined); setPhase("login"); setNotice("密码已更新，旧会话已撤销。请使用新密码重新登录。"); }
  }), [run]);

  return <IdentityContext.Provider value={{ status: session.user ? "authenticated" : phase,
    user: session.user, generation: session.generation, configuration, busy, error, notice,
    refresh, login, setup, register, logout, password }}>{children}</IdentityContext.Provider>;
}

export function useIdentity(): IdentityContextValue {
  const context = useContext(IdentityContext);
  if (!context) throw new Error("useIdentity must be used inside IdentityProvider");
  return context;
}
