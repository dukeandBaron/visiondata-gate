import { operatorFetch, OperatorApiError } from "./api";
import type { IdentityPublicUser } from "../identitySession";
import type { WorkspaceRecord } from "../domain";

export type { IdentityPublicUser } from "../identitySession";
export interface IdentityStatus {
  setup_required: boolean;
  identity_required: boolean;
  registration_policy: "ADMIN_APPROVAL";
  authentication_mode: "SETUP_REQUIRED" | "USER_SESSION";
  startup_capability_required: true;
}
export interface IdentityLoginInput { login_name: string; password: string }
export interface IdentityRegistrationInput extends IdentityLoginInput {
  display_name: string;
  email?: string | null;
}
export interface IdentityLoginResult {
  user: IdentityPublicUser;
  access_token: string;
  token_type: "Bearer";
  expires_at: string;
}
export interface IdentitySessionRecord {
  session_id: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  is_current: boolean;
}
export interface IdentityWorkspaceMember {
  user_id: string;
  display_name: string;
  role: "owner" | "member";
}

const prefix = "/v1/identity";
const loginNamePattern = /^[a-z0-9][a-z0-9._-]{2,63}$/;
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function nonempty(value: unknown): value is string { return typeof value === "string" && value.trim().length > 0; }
function timestamp(value: unknown): value is string { return typeof value === "string" && Number.isFinite(Date.parse(value)); }
function hold(condition: unknown): asserts condition {
  if (!condition) throw new OperatorApiError("IDENTITY_CONTRACT_HOLD", "身份服务响应未通过合同校验，未授予访问权限。请检查后端版本。", 502);
}
function noSecrets(value: Record<string, unknown>): void {
  hold(!["password", "password_hash", "password_kdf", "token", "token_hash", "token_sha256", "access_token"].some((key) => key in value));
}

export function parseIdentityUser(value: unknown): IdentityPublicUser {
  hold(record(value));
  noSecrets(value);
  hold(nonempty(value.user_id) && value.user_id.length <= 256
    && nonempty(value.login_name) && loginNamePattern.test(value.login_name)
    && nonempty(value.display_name) && value.display_name.length <= 120
    && (value.email === null || (typeof value.email === "string" && value.email.length <= 254))
    && (value.platform_role === "ADMIN" || value.platform_role === "USER")
    && (value.status === "PENDING" || value.status === "ACTIVE" || value.status === "DISABLED")
    && timestamp(value.created_at));
  return { user_id: value.user_id, login_name: value.login_name, display_name: value.display_name,
    email: value.email, platform_role: value.platform_role, status: value.status, created_at: value.created_at };
}

export function identityErrorMessage(error: unknown): string {
  if (error instanceof OperatorApiError) {
    if (error.code === "IDENTITY_CONTRACT_HOLD") return "身份服务响应未通过合同校验。请检查后端版本后手动重试。";
    if (error.status === 401) return "登录信息无效、账户尚未启用，或会话已失效。请核对后重新登录。";
    if (error.status === 403) return "当前账户没有此操作权限，或本机连接来源校验未通过。";
    if (error.status === 409) return "操作与当前账户状态冲突。请刷新状态；不要重复初始化或重复提交。";
    if (error.status === 422 || error.status === 400) return "输入不符合账户规则。请检查登录名、显示名称与密码长度。";
    if (error.status === 429) return "尝试次数过多，请稍后再试。系统不会自动重试登录。";
    if (error.status === 404) return "身份接口或目标记录不可用，请确认后端版本与访问范围。";
    if (error.status === 503) return "本机身份服务尚未就绪，请从工作台启动入口重新连接。";
  }
  return "未确认操作结果。请检查本机服务并手动刷新状态；系统不会自动重复提交。";
}

async function request(path: string, method = "GET", body?: unknown): Promise<Response> {
  // One explicit request only. Neither credential failures nor writes are retried here.
  return operatorFetch(`${prefix}${path}`, { method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
}
async function json(response: Response): Promise<unknown> {
  try { return await response.json(); } catch { hold(false); }
}
async function empty(response: Response): Promise<void> { hold(response.status === 204); }
function pathId(value: string): string { hold(nonempty(value) && value.length <= 256); return encodeURIComponent(value); }

export async function getIdentityStatus(): Promise<IdentityStatus> {
  const value = await json(await request("/status"));
  hold(record(value) && typeof value.setup_required === "boolean" && typeof value.identity_required === "boolean"
    && value.registration_policy === "ADMIN_APPROVAL" && value.startup_capability_required === true
    && value.authentication_mode === (value.setup_required ? "SETUP_REQUIRED" : "USER_SESSION"));
  hold(value.identity_required === !value.setup_required);
  return { setup_required: value.setup_required, identity_required: value.identity_required,
    registration_policy: "ADMIN_APPROVAL", authentication_mode: value.setup_required ? "SETUP_REQUIRED" : "USER_SESSION", startup_capability_required: true };
}

async function authenticatedResult(response: Response): Promise<IdentityLoginResult> {
  const value = await json(response);
  hold(record(value) && typeof value.access_token === "string" && value.access_token.length >= 32
    && value.access_token.length <= 512 && !/\s/.test(value.access_token)
    && value.token_type === "Bearer" && timestamp(value.expires_at) && Date.parse(value.expires_at) > Date.now());
  const user = parseIdentityUser(value.user);
  hold(user.status === "ACTIVE");
  return { user, access_token: value.access_token, expires_at: value.expires_at, token_type: "Bearer" };
}
export async function setupIdentity(input: IdentityRegistrationInput): Promise<IdentityLoginResult> {
  const result = await authenticatedResult(await request("/setup", "POST", input));
  hold(result.user.platform_role === "ADMIN");
  return result;
}
export async function loginIdentity(input: IdentityLoginInput): Promise<IdentityLoginResult> {
  return authenticatedResult(await request("/login", "POST", input));
}
export async function registerIdentity(input: IdentityRegistrationInput): Promise<IdentityPublicUser> {
  const user = parseIdentityUser(await json(await request("/register", "POST", input)));
  hold(user.status === "PENDING" && user.platform_role === "USER");
  return user;
}
export async function getIdentityMe(): Promise<IdentityPublicUser> {
  const user = parseIdentityUser(await json(await request("/me")));
  hold(user.status === "ACTIVE");
  return user;
}
export async function logoutIdentity(): Promise<void> { await empty(await request("/logout", "POST")); }
export async function changeIdentityPassword(input: { current_password: string; new_password: string }): Promise<void> {
  await empty(await request("/password", "POST", input));
}
export async function listIdentitySessions(): Promise<IdentitySessionRecord[]> {
  const value = await json(await request("/sessions"));
  hold(record(value) && Array.isArray(value.sessions));
  const ids = new Set<string>();
  const sessions = value.sessions.map((item): IdentitySessionRecord => {
    hold(record(item)); noSecrets(item);
    hold(nonempty(item.session_id) && timestamp(item.created_at) && timestamp(item.expires_at)
      && (item.revoked_at === null || timestamp(item.revoked_at)) && typeof item.is_current === "boolean"
      && !(item.is_current && item.revoked_at !== null) && !ids.has(item.session_id));
    ids.add(item.session_id);
    return { session_id: item.session_id, created_at: item.created_at, expires_at: item.expires_at,
      revoked_at: item.revoked_at, is_current: item.is_current };
  });
  hold(sessions.filter((item) => item.is_current).length <= 1);
  return sessions;
}
export async function revokeIdentitySession(id: string): Promise<void> { await empty(await request(`/sessions/${pathId(id)}`, "DELETE")); }
export async function listIdentityUsers(): Promise<IdentityPublicUser[]> {
  const value = await json(await request("/admin/users"));
  hold(record(value) && Array.isArray(value.users));
  const users = value.users.map(parseIdentityUser);
  hold(new Set(users.map((user) => user.user_id)).size === users.length);
  return users;
}
export async function approveIdentityUser(id: string): Promise<IdentityPublicUser> {
  const user = parseIdentityUser(await json(await request(`/admin/users/${pathId(id)}/approve`, "POST")));
  hold(user.user_id === id && user.status === "ACTIVE"); return user;
}
export async function updateIdentityUserStatus(id: string, status: "ACTIVE" | "DISABLED"): Promise<IdentityPublicUser> {
  const user = parseIdentityUser(await json(await request(`/admin/users/${pathId(id)}/status`, "PUT", { status })));
  hold(user.user_id === id && user.status === status); return user;
}
export async function updateIdentityUserRole(id: string, platform_role: "ADMIN" | "USER"): Promise<IdentityPublicUser> {
  const user = parseIdentityUser(await json(await request(`/admin/users/${pathId(id)}/role`, "PUT", { platform_role })));
  hold(user.user_id === id && user.platform_role === platform_role); return user;
}
export async function listIdentityWorkspaceMembers(workspaceId: string): Promise<IdentityWorkspaceMember[]> {
  const value = await json(await request(`/workspaces/${pathId(workspaceId)}/members`));
  hold(record(value) && Array.isArray(value.members));
  const ids = new Set<string>();
  return value.members.map((item): IdentityWorkspaceMember => {
    hold(record(item)); noSecrets(item);
    hold(nonempty(item.user_id) && nonempty(item.display_name) && (item.role === "owner" || item.role === "member") && !ids.has(item.user_id));
    ids.add(item.user_id);
    return { user_id: item.user_id, display_name: item.display_name, role: item.role };
  });
}
export async function addIdentityWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
  const value = await json(await request(`/workspaces/${pathId(workspaceId)}/members/${pathId(userId)}`, "PUT", { role: "member" }));
  hold(record(value) && Array.isArray(value.members));
  hold(value.members.some((item) => record(item) && item.user_id === userId && item.role === "member"));
}
export async function removeIdentityWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
  await empty(await request(`/workspaces/${pathId(workspaceId)}/members/${pathId(userId)}`, "DELETE"));
}

export async function createIdentityWorkspace(name: string, userId: string): Promise<WorkspaceRecord> {
  const response = await operatorFetch("/v1/workspaces", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), owner_user_id: userId }) });
  const value = await json(response);
  hold(response.status === 201 && record(value) && nonempty(value.workspace_id)
    && value.name === name.trim() && value.owner_user_id === userId && value.role === "owner" && timestamp(value.created_at));
  return { workspace_id: value.workspace_id, name: value.name as string, owner_user_id: userId, role: "owner", created_at: value.created_at };
}
