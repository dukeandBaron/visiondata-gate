#!/usr/bin/env node
/**
 * Fail-closed, zero-dependency browser verifier for the semifinal review UI.
 *
 * This tool verifies the real served workbench. It does not replace the
 * Python manifest verifier, product tests, or factory/customer validation.
 * Every browser run gets an isolated Chrome profile and every outcome writes
 * a machine-readable receipt, including failures.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import {
  basename,
  dirname,
  extname,
  isAbsolute,
  join,
  relative,
  resolve,
} from "node:path";
import { tmpdir } from "node:os";

const RECEIPT_SCHEMA = "visiondata-gate.semifinal-review-ui-receipt.v1";
const NEGATIVE_RECEIPT_SCHEMA =
  "visiondata-gate.review-projection-negative-ui-receipt.v1";
const PROFILE_PREFIX = "visiondata-gate-semifinal-ui-";
const DEFAULT_URL = "http://127.0.0.1:4180";
const DEFAULT_MANIFEST = "output/semifinal_demo/product/semifinal_demo_manifest.json";
const DEFAULT_OUTPUT = "output/semifinal_demo/semifinal_review_ui_receipt.json";
const DEFAULT_NEGATIVE_OUTPUT =
  "output/semifinal_demo/review_projection_negative_ui_receipt.json";
const DEFAULT_VIEWPORTS = Object.freeze([
  Object.freeze({ width: 390, height: 844 }),
  Object.freeze({ width: 720, height: 900 }),
  Object.freeze({ width: 1036, height: 768 }),
  Object.freeze({ width: 1366, height: 768 }),
]);
const PAGE_WAIT_MS = 45_000;
const BROWSER_WAIT_MS = 20_000;
const COMMAND_WAIT_MS = 15_000;
const AUTHORITY_VIEWPORT = Object.freeze({ width: 1366, height: 900 });
const REVIEW_PROJECTION_URL_PATTERN =
  "*/v1/tasks/*/industrial-incidents/*/review-projection";
const REVIEW_PROJECTION_NEGATIVE_SCENARIOS = Object.freeze([
  Object.freeze({
    id: "MISSING_REASON_CODES",
    expectedStatus: "CONTRACT_HOLD",
    expectedErrorCode: "INVALID_INCIDENT_REVIEW_PROJECTION",
  }),
  Object.freeze({
    id: "BAD_AGENT_BEHAVIOR_SHA",
    expectedStatus: "CONTRACT_HOLD",
    expectedErrorCode: "INVALID_INCIDENT_REVIEW_PROJECTION",
  }),
  Object.freeze({
    id: "BAD_STRONG_ETAG",
    expectedStatus: "STALE_HOLD",
    expectedErrorCode: "RESPONSE_ETAG_BINDING_DRIFT",
  }),
  Object.freeze({
    id: "NETWORK_INTERRUPTION",
    expectedStatus: "RETRYABLE_UNAVAILABLE",
    expectedErrorCode: "NETWORK_UNAVAILABLE",
  }),
  Object.freeze({
    id: "STALE_RETENTION",
    expectedStatus: "STALE_HOLD",
    expectedErrorCode: "INCIDENT_REVIEW_PROJECTION_SHA_DRIFT",
  }),
]);
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const TASK_ID_PATTERN = /^tsk_[0-9a-f]{20}$/;
const CASE_ID_PATTERN = /^incident_[0-9a-f]{20}$/;
const DECISION_ID_PATTERN = /^incident_decision_[0-9a-f]{20}$/;
const INTERACTION_ID_PATTERN = /^interaction_[0-9a-f]{20}$/;
const ASSET_ID_PATTERN = /^img_[0-9a-f]{20}$/;

const HELP_TEXT = [
  "VisionData Gate semifinal review UI verifier",
  "",
  "Usage:",
  "  node tools/check_semifinal_review_ui.mjs [options]",
  "",
  "Options:",
  "  --url <url>             Served workbench origin or exact review URL",
  "                          default: " + DEFAULT_URL,
  "  --manifest <path>       Prepared semifinal demo manifest",
  "                          default: " + DEFAULT_MANIFEST,
  "  --output <path>         JSON receipt destination",
  "                          default: " + DEFAULT_OUTPUT,
  "  --runs <count>          Independent browser/profile runs (default: 1)",
  "  --viewports <list>      Comma-separated WIDTHxHEIGHT values",
  "                          default: 390x844,720x900,1036x768,1366x768",
  "  --review-projection-negative",
  "                          Run five fail-closed Review Projection scenarios",
  "                          at a fixed 1366x900 viewport",
  "  --help                  Show this help",
  "",
  "Optional environment:",
  "  VISIONDATA_BROWSER_PATH Exact Chrome or Edge executable to use",
].join("\n");

function delay(milliseconds) {
  return new Promise((accept) => setTimeout(accept, milliseconds));
}

function sha256Bytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalJson(value) {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("canonical JSON does not accept non-finite numbers");
    }
    return JSON.stringify(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + value.map((item) => canonicalJson(item)).join(",") + "]";
  }
  if (typeof value === "object") {
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + canonicalJson(value[key]))
        .join(",") +
      "}"
    );
  }
  throw new TypeError("unsupported canonical JSON value: " + typeof value);
}

function canonicalJsonBytes(value) {
  return Buffer.from(canonicalJson(value) + "\n", "utf8");
}

function cleanText(value, limit = 1200) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  return normalized.length <= limit
    ? normalized
    : normalized.slice(0, limit) + "…";
}

function errorText(error) {
  if (error instanceof Error) return error.message;
  return String(error);
}

function contract(condition, message) {
  if (!condition) throw new Error(message);
}

function parseViewports(raw) {
  if (raw === undefined) return DEFAULT_VIEWPORTS.map((item) => ({ ...item }));
  const entries = String(raw)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  contract(entries.length > 0, "--viewports must contain at least one viewport");
  const seen = new Set();
  return entries.map((entry) => {
    const match = /^([0-9]{2,5})x([0-9]{2,5})$/i.exec(entry);
    contract(Boolean(match), "invalid viewport: " + entry);
    const width = Number.parseInt(match[1], 10);
    const height = Number.parseInt(match[2], 10);
    contract(
      width >= 240 && width <= 7680 && height >= 240 && height <= 7680,
      "viewport outside the supported 240..7680 range: " + entry,
    );
    const key = String(width) + "x" + String(height);
    contract(!seen.has(key), "duplicate viewport: " + key);
    seen.add(key);
    return { width, height };
  });
}

function takeOptionValue(argv, index, name) {
  const token = argv[index];
  const prefix = name + "=";
  if (token.startsWith(prefix)) {
    const value = token.slice(prefix.length);
    contract(value.length > 0, name + " requires a value");
    return { value, nextIndex: index };
  }
  contract(token === name, "internal option parser error for " + name);
  contract(index + 1 < argv.length, name + " requires a value");
  contract(!argv[index + 1].startsWith("--"), name + " requires a value");
  return { value: argv[index + 1], nextIndex: index + 1 };
}

function parseArgs(argv) {
  const values = {
    url: DEFAULT_URL,
    manifest: DEFAULT_MANIFEST,
    output: DEFAULT_OUTPUT,
    outputExplicit: false,
    runs: 1,
    viewports: undefined,
    reviewProjectionNegative: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--help" || token === "-h") {
      values.help = true;
      continue;
    }
    if (token === "--review-projection-negative") {
      values.reviewProjectionNegative = true;
      continue;
    }
    const option = ["--url", "--manifest", "--output", "--runs", "--viewports"].find(
      (candidate) => token === candidate || token.startsWith(candidate + "="),
    );
    contract(Boolean(option), "unknown option: " + token);
    const parsed = takeOptionValue(argv, index, option);
    index = parsed.nextIndex;
    if (option === "--url") values.url = parsed.value;
    if (option === "--manifest") values.manifest = parsed.value;
    if (option === "--output") {
      values.output = parsed.value;
      values.outputExplicit = true;
    }
    if (option === "--runs") values.runs = Number.parseInt(parsed.value, 10);
    if (option === "--viewports") values.viewports = parsed.value;
  }
  if (values.help) return values;
  contract(
    Number.isSafeInteger(values.runs) && values.runs >= 1 && values.runs <= 20,
    "--runs must be an integer between 1 and 20",
  );
  const parsedUrl = new URL(values.url);
  contract(
    parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:",
    "--url must use http or https",
  );
  const manifestPath = resolve(values.manifest);
  const outputPath = resolve(
    values.outputExplicit
      ? values.output
      : values.reviewProjectionNegative
        ? DEFAULT_NEGATIVE_OUTPUT
        : DEFAULT_OUTPUT,
  );
  contract(
    manifestPath !== outputPath,
    "--output must not overwrite the semifinal demo manifest",
  );
  return {
    help: false,
    url: parsedUrl.toString(),
    manifestPath,
    outputPath,
    runs: values.runs,
    viewports: parseViewports(values.viewports),
    reviewProjectionNegative: values.reviewProjectionNegative,
  };
}

function outputPathFromRawArgs(argv) {
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token.startsWith("--output=")) {
      const value = token.slice("--output=".length);
      if (value) return resolve(value);
    }
    if (token === "--output" && index + 1 < argv.length) {
      return resolve(argv[index + 1]);
    }
  }
  return resolve(
    argv.includes("--review-projection-negative")
      ? DEFAULT_NEGATIVE_OUTPUT
      : DEFAULT_OUTPUT,
  );
}

function receiptSchemaFromRawArgs(argv) {
  return argv.includes("--review-projection-negative")
    ? NEGATIVE_RECEIPT_SCHEMA
    : RECEIPT_SCHEMA;
}

function validateDigest(payload, field) {
  contract(
    typeof payload[field] === "string" && SHA256_PATTERN.test(payload[field]),
    field + " must be a lowercase SHA-256 digest",
  );
}

async function readManifest(manifestPath, rawUrl) {
  const rawBytes = await readFile(manifestPath);
  let payload;
  try {
    payload = JSON.parse(rawBytes.toString("utf8"));
  } catch (error) {
    throw new Error("manifest is not valid UTF-8 JSON: " + errorText(error));
  }
  contract(payload && typeof payload === "object" && !Array.isArray(payload), "manifest root must be an object");

  const exact = {
    schema_version: "visiondata-gate.semifinal-demo-manifest.v1",
    status: "PASS_LOCAL_DEMO_PREPARED",
    source_scope: "SYNTHETIC_FIXTURE_REPLAY_ONLY",
    actor_user_id: "usr_local_demo",
    project_source_kind: "synthetic_demo",
    task_execution_status: "COMPLETED",
    task_final_decision: "PASS",
    task_release_readiness_status: "DEMO_ONLY",
    decision_kind: "CONTINUE_HOLD",
    child_incident_status: "INVESTIGATION_REQUIRED",
    child_incident_recommendation: "CONTINUE_HOLD",
    interaction_status: "RESUMED_WITH_OPEN_QUESTIONS",
    customer_validation: "NOT_CLAIMED",
    factory_shadow_metrics: "NOT_MEASURED_PENDING_ADJUDICATION",
  };
  for (const [field, expected] of Object.entries(exact)) {
    contract(payload[field] === expected, field + " must remain " + expected);
  }
  contract(payload.production_release_allowed === false, "production_release_allowed must remain false");
  contract(payload.machine_write_permitted === false, "machine_write_permitted must remain false");
  contract(payload.remaining_open_question_count === 1, "frozen interaction must retain one open question");
  contract(Number.isInteger(payload.event_count) && payload.event_count > 0, "event_count must be positive");

  const identities = [
    ["task_id", TASK_ID_PATTERN],
    ["parent_case_id", CASE_ID_PATTERN],
    ["child_case_id", CASE_ID_PATTERN],
    ["decision_id", DECISION_ID_PATTERN],
    ["interaction_id", INTERACTION_ID_PATTERN],
  ];
  for (const [field, pattern] of identities) {
    contract(typeof payload[field] === "string" && pattern.test(payload[field]), field + " is invalid");
  }
  contract(payload.parent_case_id !== payload.child_case_id, "Parent and Child Case ids must differ");
  contract(
    payload.review_start_path === "/review?task=" + payload.task_id,
    "review_start_path is not bound to the prepared Task",
  );
  for (const field of [
    "task_request_sha256",
    "task_evidence_sha256",
    "task_release_readiness_sha256",
    "parent_case_sha256",
    "decision_sha256",
    "child_case_sha256",
    "interaction_receipt_sha256",
    "manifest_sha256",
  ]) {
    validateDigest(payload, field);
  }

  contract(Array.isArray(payload.visual_assets) && payload.visual_assets.length === 2, "visual_assets must contain two frozen assets");
  const expectedNames = new Set([
    "synthetic-fixture-before.png",
    "synthetic-fixture-recheck.png",
  ]);
  const observedNames = new Set();
  const observedIds = new Set();
  for (const asset of payload.visual_assets) {
    contract(asset && typeof asset === "object" && !Array.isArray(asset), "visual asset must be an object");
    contract(typeof asset.asset_id === "string" && ASSET_ID_PATTERN.test(asset.asset_id), "visual asset id is invalid");
    contract(!observedIds.has(asset.asset_id), "visual asset ids must be unique");
    observedIds.add(asset.asset_id);
    contract(expectedNames.has(asset.filename), "visual asset filename is outside the frozen set");
    observedNames.add(asset.filename);
    contract(SHA256_PATTERN.test(asset.source_sha256), "visual asset source_sha256 is invalid");
    contract(SHA256_PATTERN.test(asset.preview_sha256), "visual asset preview_sha256 is invalid");
    contract(Number.isInteger(asset.width) && asset.width > 0, "visual asset width is invalid");
    contract(Number.isInteger(asset.height) && asset.height > 0, "visual asset height is invalid");
  }
  contract(observedNames.size === expectedNames.size, "frozen visual asset set drifted");

  contract(typeof payload.product_root === "string", "product_root is missing");
  contract(
    resolve(dirname(manifestPath)) === resolve(payload.product_root),
    "manifest is not stored at its declared isolated product root",
  );
  const stable = { ...payload };
  delete stable.manifest_sha256;
  const calculatedManifestSha256 = sha256Bytes(canonicalJsonBytes(stable));
  contract(
    calculatedManifestSha256 === payload.manifest_sha256,
    "manifest_sha256 does not match canonical manifest bytes",
  );

  const suppliedUrl = new URL(rawUrl);
  let targetUrl;
  if (suppliedUrl.pathname === "/" && suppliedUrl.search === "") {
    targetUrl = new URL(payload.review_start_path, suppliedUrl);
  } else {
    contract(
      suppliedUrl.pathname + suppliedUrl.search === payload.review_start_path,
      "--url exact path does not match manifest review_start_path",
    );
    targetUrl = suppliedUrl;
  }
  return {
    payload,
    targetUrl: targetUrl.toString(),
    evidence: {
      path: manifestPath,
      file_sha256: sha256Bytes(rawBytes),
      declared_manifest_sha256: payload.manifest_sha256,
      calculated_manifest_sha256: calculatedManifestSha256,
      bytes: rawBytes.length,
      task_id: payload.task_id,
      review_start_path: payload.review_start_path,
      interaction_receipt_sha256: payload.interaction_receipt_sha256,
      task_final_decision: payload.task_final_decision,
      task_release_readiness_status: payload.task_release_readiness_status,
      task_release_readiness_sha256: payload.task_release_readiness_sha256,
      decision_kind: payload.decision_kind,
      child_incident_status: payload.child_incident_status,
      child_incident_recommendation: payload.child_incident_recommendation,
      boundaries: {
        source_scope: payload.source_scope,
        task_final_decision: payload.task_final_decision,
        task_release_readiness_status: payload.task_release_readiness_status,
        task_release_readiness_sha256: payload.task_release_readiness_sha256,
        decision_kind: payload.decision_kind,
        child_incident_status: payload.child_incident_status,
        child_incident_recommendation: payload.child_incident_recommendation,
        production_release_allowed: payload.production_release_allowed,
        machine_write_permitted: payload.machine_write_permitted,
        customer_validation: payload.customer_validation,
        factory_shadow_metrics: payload.factory_shadow_metrics,
      },
      contract_status: "VERIFIED",
    },
  };
}

async function isExecutableFile(path) {
  try {
    const details = await stat(path);
    if (!details.isFile()) return false;
    await access(path, fsConstants.R_OK | fsConstants.X_OK);
    return true;
  } catch {
    return false;
  }
}

async function findBrowser() {
  const candidates = [];
  if (process.env.VISIONDATA_BROWSER_PATH) {
    candidates.push(process.env.VISIONDATA_BROWSER_PATH);
  }
  if (process.platform === "win32") {
    const programFiles = process.env.PROGRAMFILES || "C:\\Program Files";
    const programFilesX86 = process.env["PROGRAMFILES(X86)"] || "C:\\Program Files (x86)";
    const localAppData = process.env.LOCALAPPDATA;
    candidates.push(
      join(programFiles, "Google", "Chrome", "Application", "chrome.exe"),
      join(programFilesX86, "Google", "Chrome", "Application", "chrome.exe"),
      join(programFiles, "Microsoft", "Edge", "Application", "msedge.exe"),
      join(programFilesX86, "Microsoft", "Edge", "Application", "msedge.exe"),
    );
    if (localAppData) {
      candidates.push(
        join(localAppData, "Google", "Chrome", "Application", "chrome.exe"),
        join(localAppData, "Microsoft", "Edge", "Application", "msedge.exe"),
      );
    }
  } else if (process.platform === "darwin") {
    candidates.push(
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      join(process.env.HOME || "", "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    );
  } else {
    candidates.push(
      "/usr/bin/google-chrome",
      "/usr/bin/google-chrome-stable",
      "/usr/bin/chromium",
      "/usr/bin/chromium-browser",
      "/usr/bin/microsoft-edge",
      "/usr/bin/microsoft-edge-stable",
    );
  }
  const seen = new Set();
  for (const raw of candidates) {
    if (!raw) continue;
    const candidate = resolve(raw);
    if (seen.has(candidate)) continue;
    seen.add(candidate);
    if (await isExecutableFile(candidate)) {
      return {
        executable: candidate,
        family: candidate.toLowerCase().includes("edge") ? "Microsoft Edge" : "Google Chrome/Chromium",
      };
    }
  }
  throw new Error(
    "Chrome or Edge was not found; set VISIONDATA_BROWSER_PATH to an exact executable",
  );
}

async function makeSafeProfile() {
  const root = await realpath(tmpdir());
  const profile = await mkdtemp(join(root, PROFILE_PREFIX));
  const resolvedProfile = await realpath(profile);
  const relation = relative(root, resolvedProfile);
  contract(
    relation !== "" &&
      !relation.startsWith("..") &&
      !isAbsolute(relation) &&
      basename(resolvedProfile).startsWith(PROFILE_PREFIX),
    "refusing unsafe temporary browser profile: " + resolvedProfile,
  );
  return { root, profile: resolvedProfile };
}

function appendCapped(buffer, chunk, limit = 24_000) {
  const next = buffer.value + String(chunk);
  buffer.value = next.length <= limit ? next : next.slice(next.length - limit);
}

async function launchBrowser(browser, profile) {
  const argumentsList = [
    "--headless=new",
    "--remote-debugging-port=0",
    "--remote-allow-origins=*",
    "--user-data-dir=" + profile,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-dev-shm-usage",
    "--metrics-recording-only",
    "--password-store=basic",
    "--window-size=1440,1000",
    "about:blank",
  ];
  const stderr = { value: "" };
  const stdout = { value: "" };
  const startedAt = Date.now();
  const child = spawn(browser.executable, argumentsList, {
    shell: false,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => appendCapped(stdout, chunk));
  child.stderr.on("data", (chunk) => appendCapped(stderr, chunk));
  contract(Number.isInteger(child.pid), "browser did not expose a spawned pid");

  const portFile = join(profile, "DevToolsActivePort");
  const deadline = Date.now() + BROWSER_WAIT_MS;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(
        "browser exited before CDP became ready (code " +
          String(child.exitCode) +
          "): " +
          cleanText(stderr.value, 2000),
      );
    }
    try {
      const lines = (await readFile(portFile, "utf8"))
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      const port = Number.parseInt(lines[0], 10);
      if (Number.isInteger(port) && port > 0 && port <= 65535) {
        return {
          child,
          pid: child.pid,
          port,
          browserWebSocketPath: lines[1] || null,
          startedAt,
          stderr,
          stdout,
          arguments: argumentsList,
        };
      }
    } catch {
      // The browser creates DevToolsActivePort asynchronously.
    }
    await delay(100);
  }
  throw new Error("browser did not create DevToolsActivePort within " + BROWSER_WAIT_MS + " ms");
}

async function fetchJson(url, init = {}) {
  const response = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(3_000),
  });
  contract(response.ok, "CDP discovery request failed with HTTP " + response.status);
  return response.json();
}

async function findPageWebSocket(port) {
  const endpoint = "http://127.0.0.1:" + String(port);
  const deadline = Date.now() + BROWSER_WAIT_MS;
  while (Date.now() < deadline) {
    try {
      const targets = await fetchJson(endpoint + "/json/list");
      const page = Array.isArray(targets)
        ? targets.find((target) => target.type === "page" && target.webSocketDebuggerUrl)
        : undefined;
      if (page) return page.webSocketDebuggerUrl;
      const created = await fetchJson(
        endpoint + "/json/new?" + encodeURIComponent("about:blank"),
        { method: "PUT" },
      );
      if (created && created.webSocketDebuggerUrl) return created.webSocketDebuggerUrl;
    } catch {
      // CDP HTTP discovery can lag behind DevToolsActivePort.
    }
    await delay(100);
  }
  throw new Error("no CDP page target became available");
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    this.closed = false;
    socket.addEventListener("message", (event) => {
      void this.handleMessage(event.data);
    });
    socket.addEventListener("close", () => {
      this.closed = true;
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error("CDP socket closed"));
      }
      this.pending.clear();
    });
  }

  static async connect(url) {
    return new Promise((accept, reject) => {
      const socket = new WebSocket(url);
      const timer = setTimeout(() => {
        socket.close();
        reject(new Error("timed out connecting to CDP WebSocket"));
      }, COMMAND_WAIT_MS);
      socket.addEventListener("open", () => {
        clearTimeout(timer);
        accept(new CdpClient(socket));
      }, { once: true });
      socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("failed to connect to CDP WebSocket"));
      }, { once: true });
    });
  }

  async handleMessage(data) {
    let text;
    if (typeof data === "string") {
      text = data;
    } else if (data instanceof ArrayBuffer) {
      text = Buffer.from(data).toString("utf8");
    } else if (typeof Blob !== "undefined" && data instanceof Blob) {
      text = await data.text();
    } else {
      text = Buffer.from(data).toString("utf8");
    }
    let message;
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }
    if (message.id !== undefined) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.error) {
        pending.reject(
          new Error(
            "CDP " +
              pending.method +
              " failed: " +
              String(message.error.message || JSON.stringify(message.error)),
          ),
        );
      } else {
        pending.resolve(message.result || {});
      }
      return;
    }
    const listeners = this.listeners.get(message.method) || [];
    for (const listener of listeners) {
      try {
        listener(message.params || {});
      } catch {
        // A diagnostics listener must not interrupt the CDP transport.
      }
    }
  }

  on(method, listener) {
    const entries = this.listeners.get(method) || [];
    entries.push(listener);
    this.listeners.set(method, entries);
    return () => {
      const current = this.listeners.get(method) || [];
      const next = current.filter((item) => item !== listener);
      if (next.length > 0) this.listeners.set(method, next);
      else this.listeners.delete(method);
    };
  }

  send(method, params = {}, timeoutMs = COMMAND_WAIT_MS) {
    if (this.closed || this.socket.readyState !== 1) {
      return Promise.reject(new Error("CDP socket is not open"));
    }
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((accept, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("CDP command timed out: " + method));
      }, timeoutMs);
      this.pending.set(id, { resolve: accept, reject, timer, method });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    if (!this.closed && this.socket.readyState < 2) this.socket.close();
  }
}

function remoteArgumentText(argument) {
  if (Object.prototype.hasOwnProperty.call(argument, "value")) {
    try {
      return typeof argument.value === "string"
        ? argument.value
        : JSON.stringify(argument.value);
    } catch {
      return String(argument.value);
    }
  }
  return argument.description || argument.className || argument.type || "";
}

function installConsoleCollector(client, startedAt) {
  const entries = [];
  client.on("Runtime.consoleAPICalled", (params) => {
    if (!["warning", "error", "assert"].includes(params.type)) return;
    entries.push({
      kind: "console",
      level: params.type === "warning" ? "warning" : "error",
      elapsed_ms: Date.now() - startedAt,
      text: cleanText((params.args || []).map(remoteArgumentText).join(" "), 3000),
      url: params.stackTrace?.callFrames?.[0]?.url || null,
    });
  });
  client.on("Runtime.exceptionThrown", (params) => {
    const details = params.exceptionDetails || {};
    entries.push({
      kind: "runtime_exception",
      level: "error",
      elapsed_ms: Date.now() - startedAt,
      text: cleanText(
        details.exception?.description || details.text || "Unhandled runtime exception",
        3000,
      ),
      url: details.url || null,
      line: Number.isInteger(details.lineNumber) ? details.lineNumber + 1 : null,
      column: Number.isInteger(details.columnNumber) ? details.columnNumber + 1 : null,
    });
  });
  client.on("Log.entryAdded", (params) => {
    const entry = params.entry || {};
    if (!["warning", "error"].includes(entry.level)) return;
    entries.push({
      kind: "browser_log",
      level: entry.level,
      elapsed_ms: Date.now() - startedAt,
      text: cleanText(entry.text || "", 3000),
      url: entry.url || null,
      source: entry.source || null,
    });
  });
  return entries;
}

function deduplicateConsole(entries) {
  const seen = new Set();
  return entries.filter((entry) => {
    const key = [entry.kind, entry.level, entry.text, entry.url].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function headerValue(headers, expectedName) {
  const normalized = expectedName.toLowerCase();
  if (Array.isArray(headers)) {
    const entry = headers.find(
      (item) => String(item?.name || "").toLowerCase() === normalized,
    );
    return entry ? String(entry.value ?? "").trim() : "";
  }
  if (headers && typeof headers === "object") {
    const entry = Object.entries(headers).find(
      ([name]) => name.toLowerCase() === normalized,
    );
    return entry ? String(entry[1] ?? "").trim() : "";
  }
  return "";
}

function decodeCdpBody(result) {
  contract(result && typeof result.body === "string", "CDP response body is missing");
  const bytes = Buffer.from(
    result.body,
    result.base64Encoded ? "base64" : "utf8",
  );
  contract(bytes.length > 0, "CDP response body is empty");
  return bytes;
}

function parseJsonObjectBytes(bytes, label) {
  let value;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch (error) {
    throw new Error(label + " is not valid UTF-8 JSON: " + errorText(error));
  }
  contract(value && typeof value === "object" && !Array.isArray(value), label + " root must be an object");
  return value;
}

function alternateSha256(value) {
  const zero = "0".repeat(64);
  return value === zero ? "1".repeat(64) : zero;
}

function reviewProjectionUrlParts(rawUrl) {
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return null;
  }
  const match = /^\/v1\/tasks\/([^/]+)\/industrial-incidents\/([^/]+)\/review-projection$/.exec(
    parsed.pathname,
  );
  if (!match || parsed.search !== "") return null;
  return {
    origin: parsed.origin,
    taskId: decodeURIComponent(match[1]),
    caseId: decodeURIComponent(match[2]),
    url: parsed.toString(),
  };
}

function projectionWorkerPolicyReasons(payload) {
  return [
    ...(Array.isArray(payload.selected_workers) ? payload.selected_workers : []),
    ...(Array.isArray(payload.rejected_workers) ? payload.rejected_workers : []),
  ]
    .map((worker) => ({
      worker_id: String(worker?.worker_id || ""),
      selected: worker?.selected === true,
      reason_codes: Array.isArray(worker?.reason_codes)
        ? worker.reason_codes.map((item) => String(item))
        : [],
    }))
    .sort((left, right) => left.worker_id.localeCompare(right.worker_id));
}

function projectionTriggerReasons(payload) {
  return (Array.isArray(payload.triggering_evidence)
    ? payload.triggering_evidence
    : [])
    .map((trigger) => ({
      worker_id: String(trigger?.worker_role || ""),
      trigger_reason_codes: Array.isArray(trigger?.trigger_reason_codes)
        ? trigger.trigger_reason_codes.map((item) => String(item))
        : [],
    }))
    .sort((left, right) => left.worker_id.localeCompare(right.worker_id));
}

function validatePristineReviewProjection({ payload, headers, url, manifest }) {
  const parts = reviewProjectionUrlParts(url);
  contract(parts, "review projection response URL is outside the expected route");
  contract(parts.taskId === manifest.task_id, "review projection response Task drifted");
  contract(CASE_ID_PATTERN.test(parts.caseId), "review projection response Case id is invalid");
  contract(
    payload.schema_version === "visiondata-gate.incident-review-projection.v1",
    "review projection schema drifted",
  );
  contract(payload.task_id === parts.taskId, "review projection payload Task drifted");
  contract(payload.case_id === parts.caseId, "review projection payload Case drifted");
  contract(
    typeof payload.projection_sha256 === "string" &&
      SHA256_PATTERN.test(payload.projection_sha256),
    "review projection digest is invalid",
  );
  contract(
    typeof payload.agent_behavior_receipt_sha256 === "string" &&
      SHA256_PATTERN.test(payload.agent_behavior_receipt_sha256),
    "review projection behavior digest is invalid",
  );
  contract(
    Array.isArray(payload.selected_workers) && payload.selected_workers.length > 0,
    "negative test requires at least one selected Worker",
  );
  const policyReasons = projectionWorkerPolicyReasons(payload);
  contract(
    policyReasons.length > 0 &&
      policyReasons.every(
        (worker) => worker.worker_id && worker.reason_codes.length > 0,
      ),
    "review projection Worker policy reasons are incomplete",
  );
  const triggerReasons = projectionTriggerReasons(payload);
  contract(
    triggerReasons.length === payload.selected_workers.length &&
      triggerReasons.every(
        (worker) => worker.worker_id && worker.trigger_reason_codes.length > 0,
      ),
    "review projection execution trigger reasons are incomplete",
  );
  contract(payload.production_release_allowed === false, "production release boundary drifted");
  contract(payload.machine_write_permitted === false, "machine write boundary drifted");
  const stable = { ...payload };
  delete stable.projection_sha256;
  const calculatedSha256 = sha256Bytes(canonicalJsonBytes(stable));
  contract(
    calculatedSha256 === payload.projection_sha256,
    "pristine review projection canonical digest drifted",
  );
  const contentSha256 = headerValue(headers, "X-Content-SHA256").toLowerCase();
  const etag = headerValue(headers, "ETag");
  const etagMatch = /^"([0-9a-fA-F]{64})"$/.exec(etag);
  contract(
    contentSha256 === payload.projection_sha256,
    "pristine X-Content-SHA256 is not bound to the projection",
  );
  contract(Boolean(etagMatch), "pristine review projection ETag is not strong");
  contract(
    etagMatch[1].toLowerCase() === payload.projection_sha256,
    "pristine review projection ETag is not bound to the projection",
  );
  return {
    task_id: payload.task_id,
    case_id: payload.case_id,
    projection_sha256: payload.projection_sha256,
    calculated_projection_sha256: calculatedSha256,
    agent_behavior_receipt_sha256: payload.agent_behavior_receipt_sha256,
    etag,
    x_content_sha256: contentSha256,
    policy_reasons: policyReasons,
    execution_trigger_reasons: triggerReasons,
    production_release_allowed: payload.production_release_allowed,
    machine_write_permitted: payload.machine_write_permitted,
  };
}

function installPageNetworkAudit(client, startedAt) {
  const requests = [];
  const requestById = new Map();
  const responses = [];
  const loadingFailures = [];
  const unsubscribe = [
    client.on("Network.requestWillBeSent", (params) => {
      const item = {
        request_id: params.requestId || null,
        elapsed_ms: Date.now() - startedAt,
        method: String(params.request?.method || "").toUpperCase(),
        url: String(params.request?.url || ""),
        type: params.type || null,
      };
      requests.push(item);
      if (item.request_id) requestById.set(item.request_id, item);
    }),
    client.on("Network.responseReceived", (params) => {
      const request = requestById.get(params.requestId);
      responses.push({
        request_id: params.requestId || null,
        elapsed_ms: Date.now() - startedAt,
        method: request?.method || null,
        url: String(params.response?.url || request?.url || ""),
        status: Number(params.response?.status || 0),
        headers: params.response?.headers || {},
        from_disk_cache: params.response?.fromDiskCache === true,
        from_service_worker: params.response?.fromServiceWorker === true,
      });
    }),
    client.on("Network.loadingFailed", (params) => {
      const request = requestById.get(params.requestId);
      loadingFailures.push({
        request_id: params.requestId || null,
        elapsed_ms: Date.now() - startedAt,
        method: request?.method || null,
        url: request?.url || "",
        error_text: String(params.errorText || ""),
        canceled: params.canceled === true,
        blocked_reason: params.blockedReason || null,
      });
    }),
  ];
  return {
    requests,
    responses,
    loadingFailures,
    stop() {
      for (const remove of unsubscribe) remove();
    },
  };
}

async function captureReviewProjectionBaseline(client, audit, manifest) {
  const candidates = audit.responses.filter(
    (item) =>
      item.method === "GET" &&
      item.status === 200 &&
      reviewProjectionUrlParts(item.url)?.taskId === manifest.task_id,
  );
  contract(candidates.length > 0, "no real 200 Review Projection response was observed");
  const response = candidates[candidates.length - 1];
  const bodyResult = await client.send("Network.getResponseBody", {
    requestId: response.request_id,
  });
  const bodyBytes = decodeCdpBody(bodyResult);
  const payload = parseJsonObjectBytes(bodyBytes, "baseline review projection");
  const evidence = validatePristineReviewProjection({
    payload,
    headers: response.headers,
    url: response.url,
    manifest,
  });
  return {
    payload,
    evidence: {
      status: "VERIFIED_REAL_API",
      request_id: response.request_id,
      url: response.url,
      http_status: response.status,
      response_body_sha256: sha256Bytes(bodyBytes),
      response_candidate_count: candidates.length,
      from_disk_cache: response.from_disk_cache,
      from_service_worker: response.from_service_worker,
      ...evidence,
    },
  };
}

function responseHeadersForFulfill(headers, overrides = {}) {
  const overrideNames = new Set(
    Object.keys(overrides).map((name) => name.toLowerCase()),
  );
  const dropped = new Set([
    "content-length",
    "content-encoding",
    "transfer-encoding",
  ]);
  const result = (Array.isArray(headers) ? headers : [])
    .filter((item) => {
      const name = String(item?.name || "").toLowerCase();
      return name && !dropped.has(name) && !overrideNames.has(name);
    })
    .map((item) => ({ name: String(item.name), value: String(item.value ?? "") }));
  for (const [name, value] of Object.entries(overrides)) {
    result.push({ name, value: String(value) });
  }
  return result;
}

function buildReviewProjectionMutation(scenario, payload, rawBody, responseHeaders) {
  const cloned = JSON.parse(JSON.stringify(payload));
  let mutation;
  let body = rawBody;
  let headers = responseHeadersForFulfill(responseHeaders);
  if (scenario.id === "MISSING_REASON_CODES") {
    const original = [...cloned.selected_workers[0].reason_codes];
    delete cloned.selected_workers[0].reason_codes;
    body = Buffer.from(JSON.stringify(cloned), "utf8");
    mutation = {
      action: "DELETE_JSON_FIELD",
      json_pointer: "/selected_workers/0/reason_codes",
      original_value: original,
    };
  } else if (scenario.id === "BAD_AGENT_BEHAVIOR_SHA") {
    const original = cloned.agent_behavior_receipt_sha256;
    cloned.agent_behavior_receipt_sha256 = "not-a-sha256";
    body = Buffer.from(JSON.stringify(cloned), "utf8");
    mutation = {
      action: "REPLACE_JSON_VALUE",
      json_pointer: "/agent_behavior_receipt_sha256",
      original_value: original,
      injected_value: cloned.agent_behavior_receipt_sha256,
    };
  } else if (scenario.id === "BAD_STRONG_ETAG") {
    const original = headerValue(responseHeaders, "ETag");
    const injected = `"${alternateSha256(payload.projection_sha256)}"`;
    headers = responseHeadersForFulfill(responseHeaders, { ETag: injected });
    mutation = {
      action: "REPLACE_RESPONSE_HEADER",
      header: "ETag",
      original_value: original,
      injected_value: injected,
      strong_etag_syntax_preserved: true,
    };
  } else if (scenario.id === "STALE_RETENTION") {
    const original = cloned.projection_sha256;
    cloned.projection_sha256 = alternateSha256(original);
    body = Buffer.from(JSON.stringify(cloned), "utf8");
    mutation = {
      action: "REPLACE_JSON_VALUE",
      json_pointer: "/projection_sha256",
      original_value: original,
      injected_value: cloned.projection_sha256,
      sha256_syntax_preserved: true,
    };
  } else {
    contract(
      scenario.id === "NETWORK_INTERRUPTION",
      "unsupported Review Projection negative scenario: " + scenario.id,
    );
    mutation = {
      action: "FAIL_REQUEST",
      error_reason: "InternetDisconnected",
    };
  }
  return { body, headers, mutation };
}

function sameProjectionBaseline(left, right) {
  return Boolean(
    left.projection_sha256 === right.projection_sha256 &&
      left.agent_behavior_receipt_sha256 === right.agent_behavior_receipt_sha256 &&
      canonicalJson(left.policy_reasons) === canonicalJson(right.policy_reasons) &&
      canonicalJson(left.execution_trigger_reasons) ===
        canonicalJson(right.execution_trigger_reasons),
  );
}

function promiseWithTimeout(promise, timeoutMs, message) {
  return new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        accept(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function createReviewProjectionFaultController({
  client,
  scenario,
  expectedUrl,
  manifest,
  baseline,
}) {
  const pending = new Set();
  const state = {
    paused_count: 0,
    exact_match_count: 0,
    handled_count: 0,
    request_id: null,
    network_id: null,
    url: null,
    method: null,
    original_response: null,
    mutation: null,
    errors: [],
  };
  let settleAccept;
  let settleReject;
  let settled = false;
  const settledPromise = new Promise((accept, reject) => {
    settleAccept = accept;
    settleReject = reject;
  });

  const settleSuccess = () => {
    if (settled) return;
    settled = true;
    settleAccept(true);
  };
  const settleFailure = (error) => {
    if (settled) return;
    settled = true;
    settleReject(error);
  };

  const handlePaused = async (params) => {
    state.paused_count += 1;
    const requestId = params.requestId;
    const method = String(params.request?.method || "").toUpperCase();
    const url = String(params.request?.url || "");
    const exact = method === "GET" && url === expectedUrl;
    if (!exact) {
      await client.send("Fetch.continueRequest", { requestId });
      return;
    }
    state.exact_match_count += 1;
    if (state.exact_match_count > 1) {
      await client.send("Fetch.continueRequest", { requestId });
      return;
    }
    state.handled_count += 1;
    state.request_id = requestId;
    state.network_id = params.networkId || null;
    state.url = url;
    state.method = method;
    contract(params.responseErrorReason === undefined, "real refresh already had a network error");
    contract(params.responseStatusCode === 200, "real refresh did not return HTTP 200");
    const responseBody = await client.send("Fetch.getResponseBody", { requestId });
    const rawBody = decodeCdpBody(responseBody);
    const payload = parseJsonObjectBytes(rawBody, "fault-source review projection");
    const pristine = validatePristineReviewProjection({
      payload,
      headers: params.responseHeaders || [],
      url,
      manifest,
    });
    contract(
      sameProjectionBaseline(pristine, baseline),
      "real refresh drifted from the verified scenario baseline before injection",
    );
    state.original_response = {
      http_status: params.responseStatusCode,
      body_sha256: sha256Bytes(rawBody),
      projection_sha256: pristine.projection_sha256,
      agent_behavior_receipt_sha256: pristine.agent_behavior_receipt_sha256,
      etag: pristine.etag,
      x_content_sha256: pristine.x_content_sha256,
    };
    const injected = buildReviewProjectionMutation(
      scenario,
      payload,
      rawBody,
      params.responseHeaders || [],
    );
    state.mutation = injected.mutation;
    if (scenario.id === "NETWORK_INTERRUPTION") {
      await client.send("Fetch.failRequest", {
        requestId,
        errorReason: "InternetDisconnected",
      });
    } else {
      await client.send("Fetch.fulfillRequest", {
        requestId,
        responseCode: params.responseStatusCode,
        responsePhrase: params.responseStatusText || "OK",
        responseHeaders: injected.headers,
        body: injected.body.toString("base64"),
      });
    }
    settleSuccess();
  };

  const removeListener = client.on("Fetch.requestPaused", (params) => {
    const task = handlePaused(params).catch(async (error) => {
      state.errors.push(errorText(error));
      try {
        if (params.requestId) {
          await client.send("Fetch.failRequest", {
            requestId: params.requestId,
            errorReason: "Aborted",
          });
        }
      } catch {
        // Fetch.disable and browser teardown remain the final fail-closed cleanup.
      }
      settleFailure(error);
    });
    pending.add(task);
    void task.finally(() => pending.delete(task));
  });

  return {
    async wait(timeoutMs = COMMAND_WAIT_MS) {
      return promiseWithTimeout(
        settledPromise,
        timeoutMs,
        "timed out waiting for the Review Projection fault injection",
      );
    },
    async drain() {
      await Promise.all([...pending]);
    },
    stop() {
      removeListener();
    },
    snapshot() {
      return {
        ...state,
        pending_request_count: pending.size,
      };
    },
  };
}

async function evaluate(client, expression) {
  const response = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(
      "browser evaluation failed: " +
        cleanText(
          response.exceptionDetails.exception?.description ||
            response.exceptionDetails.text ||
            "unknown evaluation error",
          2000,
        ),
    );
  }
  return response.result?.value;
}

function functionExpression(fn, ...args) {
  return (
    "(" +
    fn.toString() +
    ")(" +
    args.map((value) => JSON.stringify(value)).join(",") +
    ")"
  );
}

function browserProofSnapshot(expectedManifestSha256) {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number.parseFloat(style.opacity || "1") > 0 &&
      box.width > 0 &&
      box.height > 0
    );
  };
  const exactVisibleText = (root, expected) =>
    Array.from((root || document).querySelectorAll("*")).some(
      (element) => element.textContent.trim() === expected && isVisible(element),
    );
  const page = document.querySelector(".review-page");
  const syntheticProof = document.querySelector(".review-synthetic-proof");
  const interaction = document.querySelector(".interaction-receipt");
  const dynamicBenchEvidence = document.querySelector("#dynamicbench-evidence");
  const semifinalManifestEvidence = document.querySelector(
    "#semifinal-manifest-evidence",
  );
  const visualProof = document.querySelector("#review-visual-proof");
  const interactionFailure = document.querySelector(
    '.review-interaction-bridge[role="alert"]',
  );
  const generalFailure = document.querySelector(
    '.review-live-notice.is-error[role="alert"], .review-empty-state, .review-synthetic-proof__state.is-error[role="alert"], .evaluation-evidence__failure[role="alert"], #semifinal-manifest-evidence[role="alert"]',
  );
  const fixtureVerified = exactVisibleText(syntheticProof, "FIXTURE VERIFIED");
  const fixtureFailClosed =
    Boolean(syntheticProof) &&
    (exactVisibleText(syntheticProof, "FAIL CLOSED") ||
      Boolean(syntheticProof.querySelector('[role="alert"]')));
  const turnCount = interaction
    ? interaction.querySelectorAll(".interaction-receipt__timeline > li").length
    : 0;
  const dynamicBenchPass = exactVisibleText(
    dynamicBenchEvidence,
    "PASS_LOCAL_EVIDENCE",
  );
  const manifestSha256Visible = exactVisibleText(
    semifinalManifestEvidence,
    expectedManifestSha256,
  );
  const precedes = (left, right) =>
    Boolean(
      left &&
        right &&
        (left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING),
    );
  const narrativeOrderVerified =
    precedes(semifinalManifestEvidence, visualProof) &&
    precedes(visualProof, interaction) &&
    precedes(interaction, dynamicBenchEvidence);
  return {
    document_ready_state: document.readyState,
    page_present: Boolean(page),
    page_visible: isVisible(page),
    fixture_verified: fixtureVerified,
    fixture_fail_closed: fixtureFailClosed,
    interaction_receipt_present: isVisible(interaction),
    interaction_turn_count: turnCount,
    dynamicbench_evidence_present: isVisible(dynamicBenchEvidence),
    dynamicbench_status:
      dynamicBenchEvidence?.getAttribute("data-status") || "",
    dynamicbench_pass_local_evidence_visible: dynamicBenchPass,
    semifinal_manifest_evidence_present: isVisible(semifinalManifestEvidence),
    semifinal_manifest_status:
      semifinalManifestEvidence?.getAttribute("data-status") || "",
    chain_verified_visible: exactVisibleText(
      semifinalManifestEvidence,
      "CHAIN VERIFIED",
    ),
    outcome_hold_visible: exactVisibleText(
      semifinalManifestEvidence,
      "OUTCOME · HOLD",
    ),
    narrative_order_verified: narrativeOrderVerified,
    manifest_sha256_visible: manifestSha256Visible,
    expected_manifest_sha256: expectedManifestSha256,
    interaction_fail_closed: isVisible(interactionFailure),
    interaction_fail_closed_text: interactionFailure
      ? interactionFailure.textContent.replace(/\s+/g, " ").trim()
      : "",
    general_error_present: isVisible(generalFailure),
    general_error_text: generalFailure
      ? generalFailure.textContent.replace(/\s+/g, " ").trim()
      : "",
    location: window.location.href,
  };
}

function browserLayoutSnapshot() {
  const metrics = (element) => {
    if (!element) return null;
    const box = element.getBoundingClientRect();
    return {
      client_width: element.clientWidth,
      scroll_width: element.scrollWidth,
      client_height: element.clientHeight,
      scroll_height: element.scrollHeight,
      rect_left: Number(box.left.toFixed(2)),
      rect_right: Number(box.right.toFixed(2)),
      rect_width: Number(box.width.toFixed(2)),
    };
  };
  const html = document.documentElement;
  const body = document.body;
  const page = document.querySelector(".review-page");
  const checkpointList = document.querySelector(".review-checkpoints");
  const statusbar = document.querySelector(".linear-statusbar");
  const checkpointBox = checkpointList?.getBoundingClientRect();
  const clipped = [];
  if (checkpointList && checkpointBox) {
    Array.from(checkpointList.children).forEach((child, index) => {
      const box = child.getBoundingClientRect();
      const button = child.querySelector("button");
      if (
        box.left < checkpointBox.left - 1 ||
        box.right > checkpointBox.right + 1 ||
        (button && button.scrollWidth > button.clientWidth + 1)
      ) {
        clipped.push(index + 1);
      }
    });
  }
  const computedColumns = checkpointList
    ? window
        .getComputedStyle(checkpointList)
        .gridTemplateColumns.split(/\s+/)
        .filter(Boolean).length
    : 0;
  const visibleControls = Array.from(
    (page || document).querySelectorAll(
      'button, select, input, textarea, a[href], [role="button"]',
    ),
  ).filter((element) => {
    const style = window.getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && box.width > 0 && box.height > 0;
  });
  const undersizedControls = visibleControls
    .map((element) => {
      const box = element.getBoundingClientRect();
      return {
        label:
          element.getAttribute("aria-label") ||
          element.textContent.replace(/\s+/g, " ").trim().slice(0, 80) ||
          element.tagName,
        width: Number(box.width.toFixed(2)),
        height: Number(box.height.toFixed(2)),
      };
    })
    .filter((item) => item.width < 44 || item.height < 44);
  return {
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      device_pixel_ratio: window.devicePixelRatio,
    },
    html: metrics(html),
    body: metrics(body),
    review_page: metrics(page),
    statusbar: metrics(statusbar),
    checkpoint_grid: {
      computed_column_count: computedColumns,
      item_count: checkpointList?.children.length || 0,
      clipped_item_indices: clipped,
    },
    controls: {
      visible_count: visibleControls.length,
      below_44px_count: undersizedControls.length,
      below_44px_sample: undersizedControls.slice(0, 12),
    },
  };
}

function browserVisibleTextSnapshot() {
  const text = (selector) =>
    document.querySelector(selector)?.textContent.replace(/\s+/g, " ").trim() || "";
  const bodyText = document.body?.innerText.replace(/\s+/g, " ").trim() || "";
  return {
    document_title: document.title,
    reviewer_banner: text(".review-lock-banner"),
    brief_title: text("#review-brief-title"),
    brief_eyebrow: text(".review-brief__eyebrow"),
    truthline: text(".review-truthline"),
    fixture_proof: text(".review-synthetic-proof"),
    interaction_receipt: text(".interaction-receipt"),
    interaction_failure: text('.review-interaction-bridge[role="alert"]'),
    authority_boundary: text(".review-authority-boundary"),
    dynamicbench_evidence: text("#dynamicbench-evidence"),
    semifinal_manifest_evidence: text("#semifinal-manifest-evidence"),
    body_text: bodyText,
  };
}

function browserReviewProjectionSnapshot() {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number.parseFloat(style.opacity || "1") > 0 &&
      box.width > 0 &&
      box.height > 0
    );
  };
  const exactVisibleText = (root, expected) =>
    Array.from((root || document).querySelectorAll("*")).some(
      (element) => element.textContent.trim() === expected && isVisible(element),
    );
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const panel = document.querySelector(".incident-review-projection--reviewer");
  const readState = panel?.querySelector(".incident-review-read-state");
  const readStateTitle = clean(readState?.querySelector("strong")?.textContent);
  const projectionDigest = Array.from(
    panel?.querySelectorAll(".incident-review-projection__footer .digest") || [],
  ).find(
    (digest) => clean(digest.querySelector("span")?.textContent) === "REVIEW PROJECTION SHA-256",
  );
  const behaviorDigest = panel?.querySelector(
    'code[title="Agent behavior receipt SHA-256"]',
  );
  const workerPolicyReasons = Array.from(
    panel?.querySelectorAll(".incident-review-worker-lanes article") || [],
  )
    .map((article) => {
      const reasonBlock = Array.from(
        article.querySelectorAll(".incident-review-worker__reasons"),
      ).find((block) =>
        clean(block.querySelector("span")?.textContent).startsWith(
          "SELECTION POLICY",
        ),
      );
      return {
        worker_id: clean(article.querySelector(":scope > strong")?.textContent),
        selected: article.classList.contains("is-selected"),
        reason_codes: Array.from(reasonBlock?.querySelectorAll("code") || []).map(
          (item) => clean(item.textContent),
        ),
      };
    })
    .sort((left, right) => left.worker_id.localeCompare(right.worker_id));
  const workerTriggerReasons = Array.from(
    panel?.querySelectorAll(".incident-review-worker-lanes article.is-selected") || [],
  )
    .map((article) => {
      const reasonBlock = Array.from(
        article.querySelectorAll(".incident-review-worker__reasons"),
      ).find(
        (block) => clean(block.querySelector("span")?.textContent) === "EXECUTION TRIGGER REASONS",
      );
      return {
        worker_id: clean(article.querySelector(":scope > strong")?.textContent),
        trigger_reason_codes: Array.from(
          reasonBlock?.querySelectorAll("code") || [],
        ).map((item) => clean(item.textContent)),
      };
    })
    .sort((left, right) => left.worker_id.localeCompare(right.worker_id));
  return {
    panel_present: Boolean(panel),
    panel_visible: isVisible(panel),
    data_read_status: panel?.getAttribute("data-read-status") || "",
    aria_busy: panel?.getAttribute("aria-busy") || "",
    root_is_stale: panel?.classList.contains("is-stale") || false,
    read_state_title: readStateTitle,
    read_state_text: clean(readState?.textContent),
    error_text: clean(readState?.querySelector("code")?.textContent),
    current_projection_visible: exactVisibleText(panel, "CURRENT PROJECTION"),
    stale_projection_visible: exactVisibleText(panel, "STALE PROJECTION"),
    stale_display_visible: readStateTitle.includes("STALE DISPLAY"),
    projection_sha256: clean(projectionDigest?.querySelector("code")?.getAttribute("title")) ||
      clean(projectionDigest?.querySelector("code")?.textContent),
    agent_behavior_display: clean(behaviorDigest?.textContent),
    worker_policy_reasons: workerPolicyReasons,
    worker_execution_trigger_reasons: workerTriggerReasons,
    location: window.location.href,
  };
}

function browserClickReviewProjectionRefresh() {
  const panel = document.querySelector(".incident-review-projection--reviewer");
  if (!panel) return { clicked: false, reason: "panel_missing" };
  const button = Array.from(panel.querySelectorAll("button")).find(
    (item) => item.textContent.replace(/\s+/g, " ").trim() === "重新 GET 核验",
  );
  if (!button) return { clicked: false, reason: "refresh_button_missing" };
  if (button.disabled) return { clicked: false, reason: "refresh_button_disabled" };
  button.click();
  return { clicked: true, label: "重新 GET 核验" };
}

function browserFocusReviewProjection() {
  const panel = document.querySelector(".incident-review-projection--reviewer");
  if (!panel) return false;
  panel.scrollIntoView({ block: "start", inline: "nearest" });
  return true;
}

async function waitForReviewProjectionStatus(
  client,
  expectedStatus,
  timeoutMs = PAGE_WAIT_MS,
) {
  const startedAt = Date.now();
  let last = null;
  while (Date.now() - startedAt < timeoutMs) {
    last = await evaluate(
      client,
      functionExpression(browserReviewProjectionSnapshot),
    );
    if (
      last.panel_present &&
      last.panel_visible &&
      last.data_read_status === expectedStatus &&
      last.aria_busy !== "true"
    ) {
      return {
        status: "OBSERVED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    await delay(200);
  }
  return {
    status: "TIMEOUT",
    wait_ms: Date.now() - startedAt,
    expected_status: expectedStatus,
    snapshot: last,
  };
}

function browserSettle() {
  return new Promise((accept) => {
    window.scrollTo(0, 0);
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => accept(true));
    });
  });
}

async function waitForReviewState(
  client,
  expectedManifestSha256,
  timeoutMs = PAGE_WAIT_MS,
) {
  const startedAt = Date.now();
  let last = null;
  let generalFailureObservedAt = null;
  while (Date.now() - startedAt < timeoutMs) {
    last = await evaluate(
      client,
      functionExpression(browserProofSnapshot, expectedManifestSha256),
    );
    if (
      last.page_present &&
      last.page_visible &&
      last.fixture_verified &&
      last.interaction_receipt_present &&
      last.interaction_turn_count >= 3 &&
      last.dynamicbench_evidence_present &&
      last.dynamicbench_status === "PASS_LOCAL_EVIDENCE" &&
      last.dynamicbench_pass_local_evidence_visible &&
      last.semifinal_manifest_evidence_present &&
      last.semifinal_manifest_status === "PASS_LOCAL_DEMO_VERIFIED" &&
      last.manifest_sha256_visible &&
      last.chain_verified_visible &&
      last.outcome_hold_visible &&
      last.narrative_order_verified
    ) {
      return {
        status: "VERIFIED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    if (
      last.page_present &&
      (last.fixture_fail_closed || last.interaction_fail_closed)
    ) {
      return {
        status: "FAIL_CLOSED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    if (last.page_present && last.general_error_present) {
      if (generalFailureObservedAt === null) {
        generalFailureObservedAt = Date.now();
      } else if (Date.now() - generalFailureObservedAt >= 2_500) {
        return {
          status: "FAIL_CLOSED",
          wait_ms: Date.now() - startedAt,
          snapshot: last,
        };
      }
    } else {
      generalFailureObservedAt = null;
    }
    await delay(200);
  }
  return {
    status: "TIMEOUT",
    wait_ms: Date.now() - startedAt,
    snapshot: last,
  };
}

function expectedCheckpointColumns(width) {
  if (width <= 720) return 1;
  if (width <= 860) return 2;
  if (width <= 1280) return 3;
  return 6;
}

function layoutPass(layout) {
  const noOverflow = (item) =>
    item && item.scroll_width <= item.client_width + 1;
  return Boolean(
    noOverflow(layout.html) &&
      noOverflow(layout.body) &&
      noOverflow(layout.review_page) &&
      noOverflow(layout.statusbar) &&
      layout.checkpoint_grid.computed_column_count > 0 &&
      layout.checkpoint_grid.column_contract_pass &&
      layout.checkpoint_grid.item_count > 0 &&
      layout.checkpoint_grid.clipped_item_indices.length === 0 &&
      layout.controls.target_contract_pass,
  );
}

function normalizeAttributes(tag) {
  const attributes = {};
  const pattern = /\b([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>]+))/g;
  let match;
  while ((match = pattern.exec(tag)) !== null) {
    attributes[match[1].toLowerCase()] = match[2] ?? match[3] ?? match[4] ?? "";
  }
  return attributes;
}

function discoverHtmlAssets(html, pageUrl) {
  const discovered = [];
  const page = new URL(pageUrl);
  const add = (rawUrl, kind) => {
    if (!rawUrl) return;
    const resolved = new URL(rawUrl, page);
    if (resolved.origin !== page.origin) return;
    const key = kind + "|" + resolved.toString();
    if (discovered.some((item) => item.key === key)) return;
    discovered.push({ key, kind, url: resolved.toString() });
  };
  for (const match of html.matchAll(/<script\b[^>]*>/gi)) {
    const attributes = normalizeAttributes(match[0]);
    if (attributes.src) add(attributes.src, "javascript");
  }
  for (const match of html.matchAll(/<link\b[^>]*>/gi)) {
    const attributes = normalizeAttributes(match[0]);
    const relationships = String(attributes.rel || "").toLowerCase().split(/\s+/);
    if (relationships.includes("stylesheet")) add(attributes.href, "stylesheet");
    if (relationships.includes("modulepreload")) add(attributes.href, "javascript");
    if (
      relationships.includes("preload") &&
      ["script", "style"].includes(String(attributes.as || "").toLowerCase())
    ) {
      add(
        attributes.href,
        String(attributes.as).toLowerCase() === "style"
          ? "stylesheet"
          : "javascript",
      );
    }
  }
  return discovered.map(({ key, ...item }) => item);
}

async function hashBuildAssets(targetUrl) {
  const response = await fetch(targetUrl, {
    cache: "no-store",
    redirect: "follow",
    signal: AbortSignal.timeout(15_000),
  });
  contract(response.ok, "review HTML returned HTTP " + response.status);
  const htmlBytes = Buffer.from(await response.arrayBuffer());
  const html = htmlBytes.toString("utf8");
  const discovered = discoverHtmlAssets(html, response.url);
  contract(discovered.some((item) => item.kind === "javascript"), "review HTML has no same-origin JavaScript asset");
  contract(discovered.some((item) => item.kind === "stylesheet"), "review HTML has no same-origin stylesheet asset");
  const assets = [];
  for (const item of discovered) {
    const assetResponse = await fetch(item.url, {
      cache: "no-store",
      redirect: "follow",
      signal: AbortSignal.timeout(15_000),
    });
    contract(assetResponse.ok, item.kind + " asset returned HTTP " + assetResponse.status + ": " + item.url);
    const bytes = Buffer.from(await assetResponse.arrayBuffer());
    contract(bytes.length > 0, item.kind + " asset is empty: " + item.url);
    assets.push({
      kind: item.kind,
      url: item.url,
      status: assetResponse.status,
      content_type: assetResponse.headers.get("content-type"),
      bytes: bytes.length,
      sha256: sha256Bytes(bytes),
    });
  }
  assets.sort((left, right) =>
    (left.kind + "|" + left.url).localeCompare(right.kind + "|" + right.url),
  );
  const fingerprint = sha256Bytes(
    canonicalJsonBytes(
      assets.map((item) => ({
        kind: item.kind,
        url: item.url,
        bytes: item.bytes,
        sha256: item.sha256,
      })),
    ),
  );
  return {
    status: "VERIFIED",
    html_url: response.url,
    html_bytes: htmlBytes.length,
    html_sha256: sha256Bytes(htmlBytes),
    asset_count: assets.length,
    javascript_count: assets.filter((item) => item.kind === "javascript").length,
    stylesheet_count: assets.filter((item) => item.kind === "stylesheet").length,
    asset_bundle_sha256: fingerprint,
    assets,
  };
}

async function writeScreenshot(client, path) {
  const response = await client.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  }, 30_000);
  contract(typeof response.data === "string" && response.data.length > 0, "Page.captureScreenshot returned no PNG bytes");
  const bytes = Buffer.from(response.data, "base64");
  contract(bytes.length > 8 && bytes.subarray(1, 4).toString("ascii") === "PNG", "captured screenshot is not PNG");
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, bytes);
  return {
    path,
    bytes: bytes.length,
    sha256: sha256Bytes(bytes),
  };
}

async function terminateSpawnedBrowser(launch) {
  if (!launch?.child || launch.child.exitCode !== null) {
    return { exact_pid: launch?.pid || null, terminated: true, method: "already_exited" };
  }
  const pid = launch.pid;
  if (process.platform === "win32") {
    const result = await new Promise((accept) => {
      const killer = spawn(
        "taskkill.exe",
        ["/PID", String(pid), "/T", "/F"],
        { shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] },
      );
      let stderr = "";
      killer.stderr.on("data", (chunk) => {
        stderr += String(chunk);
      });
      const timer = setTimeout(() => {
        killer.kill();
        accept({ code: null, stderr: "taskkill timed out" });
      }, 10_000);
      killer.once("exit", (code) => {
        clearTimeout(timer);
        accept({ code, stderr });
      });
      killer.once("error", (error) => {
        clearTimeout(timer);
        accept({ code: null, stderr: errorText(error) });
      });
    });
    await delay(200);
    return {
      exact_pid: pid,
      terminated: launch.child.exitCode !== null || result.code === 0,
      method: "taskkill_exact_pid_tree",
      detail: cleanText(result.stderr, 1000),
    };
  }
  launch.child.kill("SIGTERM");
  const deadline = Date.now() + 5_000;
  while (launch.child.exitCode === null && Date.now() < deadline) await delay(100);
  if (launch.child.exitCode === null) launch.child.kill("SIGKILL");
  await delay(100);
  return {
    exact_pid: pid,
    terminated: launch.child.exitCode !== null || launch.child.killed,
    method: "signal_exact_spawned_process",
  };
}

async function removeSafeProfile(profileInfo) {
  if (!profileInfo?.profile) return { removed: true, path: null };
  const root = await realpath(tmpdir());
  let profile;
  try {
    profile = await realpath(profileInfo.profile);
  } catch {
    profile = resolve(profileInfo.profile);
  }
  const relation = relative(root, profile);
  contract(
    relation !== "" &&
      !relation.startsWith("..") &&
      !isAbsolute(relation) &&
      basename(profile).startsWith(PROFILE_PREFIX),
    "refusing recursive deletion outside verifier temp scope: " + profile,
  );
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  return { removed: true, path: profile };
}

function compactVisibleText(raw, taskId, manifestSha256) {
  const bodyText = raw.body_text || "";
  const required = {
    reviewer_mode_read_only: bodyText.includes("REVIEWER MODE · READ ONLY"),
    fixture_verified: bodyText.includes("FIXTURE VERIFIED"),
    three_turn_interaction: bodyText.includes("三轮受控交互"),
    task_id_bound: bodyText.includes(taskId),
    production_release_false: bodyText.includes("production release=false"),
    dynamicbench_pass_local_evidence:
      raw.dynamicbench_evidence.includes("PASS_LOCAL_EVIDENCE"),
    manifest_sha256_bound:
      raw.semifinal_manifest_evidence.includes(manifestSha256),
    chain_verified:
      raw.semifinal_manifest_evidence.includes("CHAIN VERIFIED"),
    outcome_hold:
      raw.semifinal_manifest_evidence.includes("OUTCOME · HOLD"),
  };
  return {
    document_title: cleanText(raw.document_title, 240),
    reviewer_banner: cleanText(raw.reviewer_banner, 500),
    brief_title: cleanText(raw.brief_title, 240),
    brief_eyebrow: cleanText(raw.brief_eyebrow, 240),
    truthline: cleanText(raw.truthline, 800),
    fixture_proof: cleanText(raw.fixture_proof, 1200),
    interaction_receipt: cleanText(raw.interaction_receipt, 1600),
    interaction_failure: cleanText(raw.interaction_failure, 800),
    authority_boundary: cleanText(raw.authority_boundary, 800),
    dynamicbench_evidence: cleanText(raw.dynamicbench_evidence, 1600),
    semifinal_manifest_evidence: cleanText(
      raw.semifinal_manifest_evidence,
      1600,
    ),
    body_text_sha256: sha256Bytes(Buffer.from(bodyText, "utf8")),
    required,
    required_pass: Object.values(required).every(Boolean),
  };
}

async function verifyViewport({
  client,
  viewport,
  runIndex,
  viewportIndex,
  artifactsRoot,
  manifest,
}) {
  const label = String(viewport.width) + "x" + String(viewport.height);
  try {
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await evaluate(client, functionExpression(browserSettle));
    const proof = await waitForReviewState(client, manifest.manifest_sha256);
    const layout = await evaluate(client, functionExpression(browserLayoutSnapshot));
    layout.checkpoint_grid.expected_column_count =
      expectedCheckpointColumns(viewport.width);
    layout.checkpoint_grid.column_contract_pass =
      layout.checkpoint_grid.computed_column_count ===
      layout.checkpoint_grid.expected_column_count;
    layout.controls.minimum_target_px = 44;
    layout.controls.target_contract_applicable = viewport.width <= 720;
    layout.controls.target_contract_pass =
      viewport.width > 720 || layout.controls.below_44px_count === 0;
    const rawText = await evaluate(client, functionExpression(browserVisibleTextSnapshot));
    const keyText = compactVisibleText(
      rawText,
      manifest.task_id,
      manifest.manifest_sha256,
    );
    const screenshotPath = join(
      artifactsRoot,
      "run-" + String(runIndex).padStart(2, "0"),
      String(viewportIndex + 1).padStart(2, "0") + "-" + label + ".png",
    );
    const screenshot = await writeScreenshot(client, screenshotPath);
    const observedReviewPath = new URL(proof.snapshot?.location || "about:blank");
    const expectedReviewPath = manifest.review_start_path;
    const pathBound =
      observedReviewPath.pathname + observedReviewPath.search === expectedReviewPath;
    const layoutVerified = layoutPass(layout);
    const passed =
      proof.status === "VERIFIED" &&
      pathBound &&
      layoutVerified &&
      keyText.required_pass &&
      SHA256_PATTERN.test(screenshot.sha256);
    return {
      viewport: { ...viewport, label },
      status: passed ? "PASS_LOCAL_VIEWPORT" : "FAIL_CLOSED",
      proof,
      review_path_bound: pathBound,
      layout: {
        ...layout,
        status: layoutVerified ? "NO_HORIZONTAL_CLIPPING" : "HORIZONTAL_CLIPPING_DETECTED",
      },
      key_visible_text: keyText,
      screenshot,
    };
  } catch (error) {
    return {
      viewport: { ...viewport, label },
      status: "FAIL_CLOSED",
      error: errorText(error),
    };
  }
}

function browserAuthorityIndexSnapshot(expectedTaskId, expectedCaseId) {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number.parseFloat(style.opacity || "1") > 0 &&
      box.width > 0 &&
      box.height > 0
    );
  };
  const workbench = document.querySelector(".live-cases-workbench");
  const selectedCase = document.querySelector(".live-cases-case-header h2");
  const workbenchLink = document.querySelector("a.live-cases-open-workbench");
  const error = document.querySelector(".live-cases-empty.is-danger");
  const current = new URL(window.location.href);
  let linked = null;
  try {
    linked = workbenchLink
      ? new URL(workbenchLink.getAttribute("href") || "", window.location.href)
      : null;
  } catch {
    linked = null;
  }
  const expectedWorkbenchPath = "/cases/" + encodeURIComponent(expectedCaseId);
  return {
    page_present: Boolean(workbench),
    page_visible: isVisible(workbench),
    entry_route_bound:
      current.pathname === "/cases" &&
      current.searchParams.get("task") === expectedTaskId &&
      current.searchParams.get("case") === expectedCaseId,
    selected_case_id: selectedCase?.textContent.trim() || "",
    selected_case_bound:
      isVisible(selectedCase) && selectedCase.textContent.trim() === expectedCaseId,
    workbench_link_visible: isVisible(workbenchLink),
    workbench_link_bound:
      Boolean(linked) &&
      linked.origin === current.origin &&
      linked.pathname === expectedWorkbenchPath &&
      linked.searchParams.get("task") === expectedTaskId,
    workbench_href: linked?.toString() || "",
    error_present: isVisible(error),
    error_text: error?.textContent.replace(/\s+/g, " ").trim() || "",
    location: current.toString(),
  };
}

async function waitForAuthorityIndexState(
  client,
  manifest,
  timeoutMs = PAGE_WAIT_MS,
) {
  const startedAt = Date.now();
  let last = null;
  while (Date.now() - startedAt < timeoutMs) {
    last = await evaluate(
      client,
      functionExpression(
        browserAuthorityIndexSnapshot,
        manifest.task_id,
        manifest.child_case_id,
      ),
    );
    if (
      last.page_present &&
      last.page_visible &&
      last.entry_route_bound &&
      last.selected_case_bound &&
      last.workbench_link_visible &&
      last.workbench_link_bound
    ) {
      return {
        status: "VERIFIED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    if (last.error_present) {
      return {
        status: "FAIL_CLOSED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    await delay(200);
  }
  return {
    status: "TIMEOUT",
    wait_ms: Date.now() - startedAt,
    snapshot: last,
  };
}

function browserAuthoritySnapshot(expectedTaskId, expectedCaseId) {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number.parseFloat(style.opacity || "1") > 0 &&
      box.width > 0 &&
      box.height > 0
    );
  };
  const exactVisibleText = (root, expected) =>
    Array.from((root || document).querySelectorAll("*")).some(
      (element) => element.textContent.trim() === expected && isVisible(element),
    );
  const page = document.querySelector(".live-incident-workbench");
  const bridge = document.querySelector(".incident-authority-bridge");
  const unavailable = document.querySelector(
    ".incident-authority-bridge--unavailable",
  );
  const heading = document.querySelector(".live-incident-heading h1");
  const current = new URL(window.location.href);
  return {
    page_present: Boolean(page),
    page_visible: isVisible(page),
    route_bound:
      current.pathname === "/cases/" + encodeURIComponent(expectedCaseId) &&
      current.searchParams.get("task") === expectedTaskId,
    case_heading_bound:
      isVisible(heading) && heading.textContent.trim() === expectedCaseId,
    authority_bridge_present: Boolean(bridge),
    authority_bridge_visible: isVisible(bridge),
    receipts_verified_visible: exactVisibleText(bridge, "RECEIPTS VERIFIED"),
    unavailable_present: Boolean(unavailable),
    unavailable_visible: isVisible(unavailable),
    authority_text: bridge?.textContent.replace(/\s+/g, " ").trim() || "",
    location: current.toString(),
  };
}

async function waitForAuthorityState(
  client,
  manifest,
  timeoutMs = PAGE_WAIT_MS,
) {
  const startedAt = Date.now();
  let last = null;
  while (Date.now() - startedAt < timeoutMs) {
    last = await evaluate(
      client,
      functionExpression(
        browserAuthoritySnapshot,
        manifest.task_id,
        manifest.child_case_id,
      ),
    );
    if (
      last.page_present &&
      last.page_visible &&
      last.route_bound &&
      last.case_heading_bound &&
      last.authority_bridge_present &&
      last.authority_bridge_visible &&
      last.receipts_verified_visible &&
      !last.unavailable_present
    ) {
      return {
        status: "VERIFIED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    if (last.unavailable_present || last.unavailable_visible) {
      return {
        status: "FAIL_CLOSED",
        wait_ms: Date.now() - startedAt,
        snapshot: last,
      };
    }
    await delay(200);
  }
  return {
    status: "TIMEOUT",
    wait_ms: Date.now() - startedAt,
    snapshot: last,
  };
}

async function verifyAuthorityCase({
  client,
  targetUrl,
  manifest,
  runIndex,
  artifactsRoot,
}) {
  const entryUrl = new URL("/cases", targetUrl);
  entryUrl.search = "";
  entryUrl.searchParams.set("task", manifest.task_id);
  entryUrl.searchParams.set("case", manifest.child_case_id);
  const receipt = {
    status: "FAIL_CLOSED",
    expected_task_id: manifest.task_id,
    expected_child_case_id: manifest.child_case_id,
    entry_url: entryUrl.toString(),
    entry_path: entryUrl.pathname + entryUrl.search,
    entry_proof: null,
    workbench_url: null,
    workbench_proof: null,
    authority_screenshot: null,
    errors: [],
  };
  try {
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: AUTHORITY_VIEWPORT.width,
      height: AUTHORITY_VIEWPORT.height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const entryNavigation = await client.send(
      "Page.navigate",
      { url: entryUrl.toString() },
      30_000,
    );
    contract(
      !entryNavigation.errorText,
      "authority case entry navigation failed: " + entryNavigation.errorText,
    );
    receipt.entry_proof = await waitForAuthorityIndexState(client, manifest);
    contract(
      receipt.entry_proof.status === "VERIFIED",
      "authority case entry route did not bind the manifest Child Case",
    );

    const workbenchUrl = new URL(
      receipt.entry_proof.snapshot.workbench_href,
      entryUrl,
    );
    const expectedWorkbenchPath =
      "/cases/" + encodeURIComponent(manifest.child_case_id);
    contract(
      workbenchUrl.origin === entryUrl.origin &&
        workbenchUrl.pathname === expectedWorkbenchPath &&
        workbenchUrl.searchParams.get("task") === manifest.task_id,
      "authority workbench href escaped the manifest Task / Child Case scope",
    );
    receipt.workbench_url = workbenchUrl.toString();
    const workbenchNavigation = await client.send(
      "Page.navigate",
      { url: workbenchUrl.toString() },
      30_000,
    );
    contract(
      !workbenchNavigation.errorText,
      "authority workbench navigation failed: " + workbenchNavigation.errorText,
    );
    receipt.workbench_proof = await waitForAuthorityState(client, manifest);
    contract(
      receipt.workbench_proof.status === "VERIFIED",
      "Goal 3 authority receipts were not verified for the manifest Child Case",
    );
    await evaluate(client, functionExpression(browserSettle));
    const screenshotPath = join(
      artifactsRoot,
      "run-" + String(runIndex).padStart(2, "0"),
      "authority-case.png",
    );
    receipt.authority_screenshot = await writeScreenshot(client, screenshotPath);
    contract(
      receipt.authority_screenshot.bytes > 8 &&
        SHA256_PATTERN.test(receipt.authority_screenshot.sha256),
      "authority screenshot receipt is incomplete",
    );
    receipt.status = "PASS_LOCAL_AUTHORITY_CASE";
  } catch (error) {
    receipt.errors.push(errorText(error));
  }
  return receipt;
}

function compactDigestForUi(value, head = 10, tail = 6) {
  if (!value) return "—";
  return value.length > head + tail + 1
    ? value.slice(0, head) + "…" + value.slice(-tail)
    : value;
}

function summarizePageNetwork(audit) {
  const methodCounts = {};
  for (const request of audit.requests) {
    methodCounts[request.method] = (methodCounts[request.method] || 0) + 1;
  }
  const forbiddenMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  const forbidden = audit.requests.filter((item) =>
    forbiddenMethods.has(item.method),
  );
  return {
    request_count: audit.requests.length,
    method_counts: methodCounts,
    review_projection_requests: audit.requests.filter((item) =>
      Boolean(reviewProjectionUrlParts(item.url)),
    ),
    forbidden_write_method_count: forbidden.length,
    forbidden_write_requests: forbidden,
    loading_failures: [...audit.loadingFailures],
  };
}

function assessNegativeConsole(entries, scenario, faultUrl) {
  const unique = deduplicateConsole(entries);
  const allowed = [];
  const unexpected = [];
  for (const entry of unique) {
    const expectedInjectedNetworkFailure =
      scenario.id === "NETWORK_INTERRUPTION" &&
      entry.kind === "browser_log" &&
      entry.level === "error" &&
      entry.source === "network" &&
      entry.url === faultUrl &&
      /ERR_INTERNET_DISCONNECTED/i.test(entry.text);
    if (expectedInjectedNetworkFailure) allowed.push(entry);
    else unexpected.push(entry);
  }
  return {
    warning_count: unique.filter((item) => item.level === "warning").length,
    error_count: unique.filter((item) => item.level === "error").length,
    runtime_exception_count: unique.filter(
      (item) => item.kind === "runtime_exception",
    ).length,
    allowed_injected_network_error_count: allowed.length,
    unexpected_count: unexpected.length,
    allowed_entries: allowed,
    unexpected_entries: unexpected,
  };
}

function negativeScenarioAssertions({
  scenario,
  baseline,
  baselineDom,
  fault,
  observed,
  pageNetwork,
  consoleAssessment,
  screenshot,
}) {
  const snapshot = observed?.snapshot || {};
  const matchingLoadingFailures = pageNetwork.loading_failures.filter(
    (item) =>
      (fault.network_id && item.request_id === fault.network_id) ||
      (item.method === "GET" && item.url === fault.url),
  );
  const expectedNetworkFailure = matchingLoadingFailures.some((item) =>
    /ERR_INTERNET_DISCONNECTED/i.test(item.error_text),
  );
  return {
    baseline_real_api_verified:
      baseline.status === "VERIFIED_REAL_API" &&
      baseline.http_status === 200 &&
      baseline.from_disk_cache === false &&
      baseline.from_service_worker === false,
    baseline_dom_verified:
      baselineDom.status === "OBSERVED" &&
      baselineDom.snapshot?.data_read_status === "VERIFIED" &&
      baselineDom.snapshot?.current_projection_visible === true &&
      baselineDom.snapshot?.stale_projection_visible === false &&
      baselineDom.snapshot?.projection_sha256 === baseline.projection_sha256 &&
      baselineDom.snapshot?.agent_behavior_display ===
        "BEH " + compactDigestForUi(baseline.agent_behavior_receipt_sha256) &&
      canonicalJson(baselineDom.snapshot?.worker_policy_reasons || []) ===
        canonicalJson(baseline.policy_reasons) &&
      canonicalJson(
        baselineDom.snapshot?.worker_execution_trigger_reasons || [],
      ) === canonicalJson(baseline.execution_trigger_reasons),
    exactly_one_fault_match:
      fault.exact_match_count === 1 &&
      fault.handled_count === 1 &&
      fault.pending_request_count === 0,
    fault_bound_to_get:
      fault.method === "GET" &&
      fault.url === baseline.url &&
      Boolean(fault.request_id),
    expected_hold_observed:
      observed?.status === "OBSERVED" &&
      snapshot.data_read_status === scenario.expectedStatus &&
      snapshot.error_text.includes(scenario.expectedErrorCode),
    verified_claim_removed: snapshot.current_projection_visible === false,
    retained_projection_marked_stale:
      snapshot.root_is_stale === true &&
      snapshot.stale_display_visible === true &&
      snapshot.stale_projection_visible === true,
    retained_projection_sha256:
      snapshot.projection_sha256 === baseline.projection_sha256,
    retained_agent_behavior_sha256:
      snapshot.agent_behavior_display ===
      "BEH " + compactDigestForUi(baseline.agent_behavior_receipt_sha256),
    retained_policy_reasons:
      canonicalJson(snapshot.worker_policy_reasons || []) ===
      canonicalJson(baseline.policy_reasons),
    retained_execution_trigger_reasons:
      canonicalJson(snapshot.worker_execution_trigger_reasons || []) ===
      canonicalJson(baseline.execution_trigger_reasons),
    no_page_http_write_methods:
      pageNetwork.forbidden_write_method_count === 0,
    no_uncaught_runtime_exception:
      consoleAssessment.runtime_exception_count === 0,
    no_unexpected_console_or_browser_error:
      consoleAssessment.unexpected_count === 0,
    network_fault_landed:
      scenario.id === "NETWORK_INTERRUPTION"
        ? expectedNetworkFailure
        : matchingLoadingFailures.length === 0,
    screenshot_bound:
      Boolean(
        screenshot &&
          screenshot.bytes > 8 &&
          SHA256_PATTERN.test(screenshot.sha256),
      ),
  };
}

async function runReviewProjectionNegativeScenario({
  browser,
  targetUrl,
  manifest,
  scenario,
  runIndex,
  scenarioIndex,
  artifactsRoot,
}) {
  const runReceipt = {
    run: runIndex,
    scenario: scenario.id,
    expected_status: scenario.expectedStatus,
    expected_error_code: scenario.expectedErrorCode,
    status: "FAIL_CLOSED",
    browser: {
      family: browser.family,
      executable: browser.executable,
    },
    viewport: { ...AUTHORITY_VIEWPORT },
    baseline: null,
    fault_injection: null,
    observed: null,
    page_network: null,
    console: null,
    screenshot: null,
    assertions: {},
    cleanup: {
      exact_spawned_pid: null,
      browser_terminated: false,
      profile_removed: false,
      errors: [],
    },
    errors: [],
  };
  let profileInfo;
  let launch;
  let client;
  let audit;
  let controller;
  let fetchEnabled = false;
  let consoleEntries = [];
  const screenshotPath = join(
    artifactsRoot,
    "negative",
    "run-" + String(runIndex).padStart(2, "0"),
    String(scenarioIndex + 1).padStart(2, "0") +
      "-" +
      scenario.id.toLowerCase().replaceAll("_", "-") +
      ".png",
  );
  try {
    profileInfo = await makeSafeProfile();
    launch = await launchBrowser(browser, profileInfo.profile);
    runReceipt.browser.pid = launch.pid;
    runReceipt.browser.profile_scope = "isolated_os_temp";
    runReceipt.cleanup.exact_spawned_pid = launch.pid;
    const pageWebSocket = await findPageWebSocket(launch.port);
    client = await CdpClient.connect(pageWebSocket);
    consoleEntries = installConsoleCollector(client, launch.startedAt);
    audit = installPageNetworkAudit(client, launch.startedAt);
    await Promise.all([
      client.send("Page.enable"),
      client.send("Runtime.enable"),
      client.send("Log.enable"),
      client.send("Network.enable"),
    ]);
    const version = await client.send("Browser.getVersion");
    runReceipt.browser.product = version.product || null;
    runReceipt.browser.user_agent = version.userAgent || null;
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: AUTHORITY_VIEWPORT.width,
      height: AUTHORITY_VIEWPORT.height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const navigation = await client.send(
      "Page.navigate",
      { url: targetUrl },
      30_000,
    );
    contract(!navigation.errorText, "Page.navigate failed: " + navigation.errorText);

    const baselineDom = await waitForReviewProjectionStatus(client, "VERIFIED");
    contract(
      baselineDom.status === "OBSERVED",
      "Review Projection did not reach a clean VERIFIED baseline",
    );
    const capturedBaseline = await captureReviewProjectionBaseline(
      client,
      audit,
      manifest,
    );
    runReceipt.baseline = {
      ...capturedBaseline.evidence,
      dom: baselineDom,
    };
    contract(
      baselineDom.snapshot?.projection_sha256 ===
        capturedBaseline.evidence.projection_sha256,
      "VERIFIED DOM is not bound to the observed real API projection digest",
    );
    contract(
      deduplicateConsole(consoleEntries).length === 0,
      "clean Review Projection baseline emitted console or browser diagnostics",
    );

    controller = createReviewProjectionFaultController({
      client,
      scenario,
      expectedUrl: capturedBaseline.evidence.url,
      manifest,
      baseline: capturedBaseline.evidence,
    });
    await client.send("Fetch.enable", {
      patterns: [
        {
          urlPattern: REVIEW_PROJECTION_URL_PATTERN,
          requestStage: "Response",
        },
      ],
    });
    fetchEnabled = true;
    const clicked = await evaluate(
      client,
      functionExpression(browserClickReviewProjectionRefresh),
    );
    contract(clicked?.clicked === true, "failed to click the explicit Review Projection GET refresh");
    await controller.wait(PAGE_WAIT_MS);
    await client.send("Fetch.disable");
    fetchEnabled = false;
    await controller.drain();
    runReceipt.fault_injection = controller.snapshot();
    controller.stop();
    controller = null;

    runReceipt.observed = await waitForReviewProjectionStatus(
      client,
      scenario.expectedStatus,
    );
    await evaluate(client, functionExpression(browserFocusReviewProjection));
    await evaluate(client, functionExpression(browserSettle));
    runReceipt.screenshot = await writeScreenshot(client, screenshotPath);
    runReceipt.page_network = summarizePageNetwork(audit);
    runReceipt.console = assessNegativeConsole(
      consoleEntries,
      scenario,
      capturedBaseline.evidence.url,
    );
    runReceipt.assertions = negativeScenarioAssertions({
      scenario,
      baseline: capturedBaseline.evidence,
      baselineDom,
      fault: runReceipt.fault_injection,
      observed: runReceipt.observed,
      pageNetwork: runReceipt.page_network,
      consoleAssessment: runReceipt.console,
      screenshot: runReceipt.screenshot,
    });
  } catch (error) {
    runReceipt.errors.push(errorText(error));
  } finally {
    if (client && fetchEnabled) {
      try {
        await client.send("Fetch.disable");
      } catch (error) {
        runReceipt.cleanup.errors.push("Fetch cleanup: " + errorText(error));
      }
    }
    if (controller) {
      try {
        await controller.drain();
      } catch (error) {
        runReceipt.cleanup.errors.push("Fetch drain: " + errorText(error));
      }
      runReceipt.fault_injection = controller.snapshot();
      controller.stop();
    }
    if (client && !runReceipt.screenshot) {
      try {
        await evaluate(client, functionExpression(browserFocusReviewProjection));
        await evaluate(client, functionExpression(browserSettle));
        runReceipt.screenshot = await writeScreenshot(client, screenshotPath);
      } catch (error) {
        runReceipt.cleanup.errors.push("failure screenshot: " + errorText(error));
      }
    }
    if (audit) {
      if (!runReceipt.page_network) runReceipt.page_network = summarizePageNetwork(audit);
      audit.stop();
    }
    if (!runReceipt.console) {
      runReceipt.console = assessNegativeConsole(
        consoleEntries,
        scenario,
        runReceipt.baseline?.url || "",
      );
    }
    client?.close();
    try {
      const termination = await terminateSpawnedBrowser(launch);
      runReceipt.cleanup.browser_terminated = termination.terminated;
      runReceipt.cleanup.termination = termination;
    } catch (error) {
      runReceipt.cleanup.errors.push("browser cleanup: " + errorText(error));
    }
    try {
      const removal = await removeSafeProfile(profileInfo);
      runReceipt.cleanup.profile_removed = removal.removed;
      runReceipt.cleanup.profile = removal;
    } catch (error) {
      runReceipt.cleanup.errors.push("profile cleanup: " + errorText(error));
    }
    if (launch) {
      runReceipt.browser.stderr_excerpt = cleanText(launch.stderr.value, 2000);
    }
  }
  runReceipt.assertions.cleanup_complete =
    runReceipt.cleanup.browser_terminated &&
    runReceipt.cleanup.profile_removed &&
    runReceipt.cleanup.errors.length === 0;
  const passed =
    runReceipt.errors.length === 0 &&
    Object.values(runReceipt.assertions).length > 0 &&
    Object.values(runReceipt.assertions).every(Boolean);
  runReceipt.status = passed ? "PASS_EXPECTED_FAIL_CLOSED" : "FAIL_CLOSED";
  return runReceipt;
}

async function runReviewProjectionNegativeSuite({
  browser,
  targetUrl,
  manifest,
  runs,
  artifactsRoot,
}) {
  const scenarioRuns = [];
  for (let runIndex = 1; runIndex <= runs; runIndex += 1) {
    for (
      let scenarioIndex = 0;
      scenarioIndex < REVIEW_PROJECTION_NEGATIVE_SCENARIOS.length;
      scenarioIndex += 1
    ) {
      scenarioRuns.push(
        await runReviewProjectionNegativeScenario({
          browser,
          targetUrl,
          manifest,
          scenario: REVIEW_PROJECTION_NEGATIVE_SCENARIOS[scenarioIndex],
          runIndex,
          scenarioIndex,
          artifactsRoot,
        }),
      );
    }
  }
  return scenarioRuns;
}

async function runBrowserVerification({
  browser,
  targetUrl,
  manifest,
  viewports,
  runIndex,
  artifactsRoot,
}) {
  const runReceipt = {
    run: runIndex,
    status: "FAIL_CLOSED",
    browser: {
      family: browser.family,
      executable: browser.executable,
    },
    launch_to_interactive_ms: null,
    build_assets: null,
    authority_case: null,
    viewports: [],
    console: { warning_count: 0, error_count: 0, entries: [] },
    cleanup: {
      exact_spawned_pid: null,
      browser_terminated: false,
      profile_removed: false,
      errors: [],
    },
    errors: [],
  };
  let profileInfo;
  let launch;
  let client;
  try {
    profileInfo = await makeSafeProfile();
    launch = await launchBrowser(browser, profileInfo.profile);
    runReceipt.browser.pid = launch.pid;
    runReceipt.browser.profile_scope = "isolated_os_temp";
    runReceipt.cleanup.exact_spawned_pid = launch.pid;
    const pageWebSocket = await findPageWebSocket(launch.port);
    client = await CdpClient.connect(pageWebSocket);
    const consoleEntries = installConsoleCollector(client, launch.startedAt);
    await Promise.all([
      client.send("Page.enable"),
      client.send("Runtime.enable"),
      client.send("Log.enable"),
    ]);
    const version = await client.send("Browser.getVersion");
    runReceipt.browser.product = version.product || null;
    runReceipt.browser.user_agent = version.userAgent || null;

    const firstViewport = viewports[0];
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: firstViewport.width,
      height: firstViewport.height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const navigation = await client.send("Page.navigate", { url: targetUrl }, 30_000);
    contract(!navigation.errorText, "Page.navigate failed: " + navigation.errorText);
    const initialProof = await waitForReviewState(
      client,
      manifest.manifest_sha256,
    );
    runReceipt.launch_to_interactive_ms = Date.now() - launch.startedAt;
    runReceipt.initial_interactive_state = initialProof;

    for (let index = 0; index < viewports.length; index += 1) {
      const viewportReceipt = await verifyViewport({
        client,
        viewport: viewports[index],
        runIndex,
        viewportIndex: index,
        artifactsRoot,
        manifest,
      });
      runReceipt.viewports.push(viewportReceipt);
    }
    runReceipt.authority_case = await verifyAuthorityCase({
      client,
      targetUrl,
      manifest,
      runIndex,
      artifactsRoot,
    });
    try {
      runReceipt.build_assets = await hashBuildAssets(targetUrl);
    } catch (error) {
      runReceipt.build_assets = {
        status: "FAIL_CLOSED",
        error: errorText(error),
      };
    }
    const uniqueConsole = deduplicateConsole(consoleEntries);
    runReceipt.console = {
      warning_count: uniqueConsole.filter((item) => item.level === "warning").length,
      error_count: uniqueConsole.filter((item) => item.level === "error").length,
      entries: uniqueConsole,
    };
    const consoleClean =
      runReceipt.console.warning_count === 0 && runReceipt.console.error_count === 0;
    const passed =
      initialProof.status === "VERIFIED" &&
      runReceipt.viewports.length === viewports.length &&
      runReceipt.viewports.every((item) => item.status === "PASS_LOCAL_VIEWPORT") &&
      runReceipt.authority_case?.status === "PASS_LOCAL_AUTHORITY_CASE" &&
      runReceipt.build_assets?.status === "VERIFIED" &&
      consoleClean;
    runReceipt.status = passed ? "PASS_LOCAL_UI_RUN" : "FAIL_CLOSED";
  } catch (error) {
    runReceipt.errors.push(errorText(error));
  } finally {
    client?.close();
    try {
      const termination = await terminateSpawnedBrowser(launch);
      runReceipt.cleanup.browser_terminated = termination.terminated;
      runReceipt.cleanup.termination = termination;
    } catch (error) {
      runReceipt.cleanup.errors.push("browser cleanup: " + errorText(error));
    }
    try {
      const removal = await removeSafeProfile(profileInfo);
      runReceipt.cleanup.profile_removed = removal.removed;
      runReceipt.cleanup.profile = removal;
    } catch (error) {
      runReceipt.cleanup.errors.push("profile cleanup: " + errorText(error));
    }
    if (
      !runReceipt.cleanup.browser_terminated ||
      !runReceipt.cleanup.profile_removed ||
      runReceipt.cleanup.errors.length > 0
    ) {
      runReceipt.status = "FAIL_CLOSED";
    }
    if (launch) {
      runReceipt.browser.stderr_excerpt = cleanText(launch.stderr.value, 2000);
    }
  }
  return runReceipt;
}

function makeFailureReceipt(error, argv) {
  const schemaVersion = receiptSchemaFromRawArgs(argv);
  const negative = schemaVersion === NEGATIVE_RECEIPT_SCHEMA;
  const receipt = {
    schema_version: schemaVersion,
    status: "FAIL_CLOSED",
    generated_at_utc: new Date().toISOString(),
    request: {
      argv,
      node_version: process.version,
      cwd: process.cwd(),
    },
    manifest: null,
    errors: [errorText(error)],
    boundaries: {
      local_ui_verification_only: true,
      production_release_allowed: false,
      machine_write_permitted: false,
      customer_validation: "NOT_CLAIMED",
      factory_shadow_metrics: "NOT_MEASURED_PENDING_ADJUDICATION",
      submission_eligible: false,
    },
    claim_boundary:
      "Failure receipt only. No browser, factory, customer, deployment, or production claim may be inferred.",
  };
  if (negative) {
    receipt.mode = "REVIEW_PROJECTION_NEGATIVE";
    receipt.scenario_runs = [];
    receipt.summary = {
      requested_runs: 0,
      required_scenario_count: REVIEW_PROJECTION_NEGATIVE_SCENARIOS.length,
      completed_scenario_count: 0,
      passed_scenario_count: 0,
      failed_scenario_count: 0,
      screenshot_count: 0,
      no_page_http_write_methods: false,
    };
  } else {
    receipt.browser_runs = [];
    receipt.summary = {
      requested_runs: 0,
      completed_runs: 0,
      passed_runs: 0,
      failed_runs: 0,
      authority_passed_runs: 0,
      authority_screenshot_count: 0,
      asset_bundle_consistent: false,
    };
  }
  return receipt;
}

function makeReviewProjectionNegativeReceipt({ options, manifest, scenarioRuns }) {
  const requiredScenarioCount =
    options.runs * REVIEW_PROJECTION_NEGATIVE_SCENARIOS.length;
  const passedScenarioCount = scenarioRuns.filter(
    (item) => item.status === "PASS_EXPECTED_FAIL_CLOSED",
  ).length;
  const screenshotCount = scenarioRuns.filter(
    (item) => item.screenshot && SHA256_PATTERN.test(item.screenshot.sha256),
  ).length;
  const noPageHttpWriteMethods = scenarioRuns.every(
    (item) => item.page_network?.forbidden_write_method_count === 0,
  );
  const overallPass =
    scenarioRuns.length === requiredScenarioCount &&
    passedScenarioCount === requiredScenarioCount &&
    screenshotCount === requiredScenarioCount &&
    noPageHttpWriteMethods;
  return {
    overallPass,
    receipt: {
      schema_version: NEGATIVE_RECEIPT_SCHEMA,
      mode: "REVIEW_PROJECTION_NEGATIVE",
      status: overallPass
        ? "PASS_LOCAL_REVIEW_PROJECTION_NEGATIVE_UI"
        : "FAIL_CLOSED",
      generated_at_utc: new Date().toISOString(),
      request: {
        url: options.url,
        target_url: manifest.targetUrl,
        manifest_path: options.manifestPath,
        output_path: options.outputPath,
        runs: options.runs,
        viewport: { ...AUTHORITY_VIEWPORT },
        node_version: process.version,
        required_scenarios: REVIEW_PROJECTION_NEGATIVE_SCENARIOS.map(
          (item) => item.id,
        ),
      },
      manifest: manifest.evidence,
      scenario_runs: scenarioRuns,
      summary: {
        requested_runs: options.runs,
        required_scenario_count: requiredScenarioCount,
        completed_scenario_count: scenarioRuns.length,
        passed_scenario_count: passedScenarioCount,
        failed_scenario_count: scenarioRuns.length - passedScenarioCount,
        screenshot_count: screenshotCount,
        no_page_http_write_methods: noPageHttpWriteMethods,
        console_unexpected_count: scenarioRuns.reduce(
          (total, item) => total + (item.console?.unexpected_count || 0),
          0,
        ),
        runtime_exception_count: scenarioRuns.reduce(
          (total, item) => total + (item.console?.runtime_exception_count || 0),
          0,
        ),
      },
      errors: scenarioRuns.flatMap((item) => item.errors || []),
      boundaries: {
        local_ui_verification_only: true,
        expected_fail_closed_behavior_only: true,
        source_scope: manifest.payload.source_scope,
        production_release_allowed: false,
        machine_write_permitted: false,
        page_http_mutation_permitted: false,
        customer_validation: "NOT_CLAIMED",
        factory_shadow_metrics: "NOT_MEASURED_PENDING_ADJUDICATION",
        submission_eligible: false,
      },
      claim_boundary:
        "This receipt proves only that five injected local browser faults produced the expected fail-closed Review Projection UI states. It is not factory shadow evidence, customer acceptance, production deployment, official submission, or production release.",
    },
  };
}

function finalizeReceipt(receipt) {
  const stable = { ...receipt };
  delete stable.receipt_sha256;
  return {
    ...stable,
    receipt_sha256: sha256Bytes(canonicalJsonBytes(stable)),
  };
}

async function emitReceipt(receipt, outputPath) {
  const finalized = finalizeReceipt(receipt);
  const serialized = JSON.stringify(finalized, null, 2) + "\n";
  let writeError = null;
  try {
    await mkdir(dirname(outputPath), { recursive: true });
    await writeFile(outputPath, serialized, "utf8");
  } catch (error) {
    writeError = errorText(error);
  }
  process.stdout.write(serialized);
  if (writeError) {
    process.stderr.write(
      "SEMIFINAL_REVIEW_UI_RECEIPT_WRITE_FAILED: " + writeError + "\n",
    );
  }
  return { receipt: finalized, writeError };
}

async function execute(argv) {
  let options;
  try {
    options = parseArgs(argv);
  } catch (error) {
    const emitted = await emitReceipt(
      makeFailureReceipt(error, argv),
      outputPathFromRawArgs(argv),
    );
    return emitted.writeError ? 3 : 2;
  }
  if (options.help) {
    process.stdout.write(HELP_TEXT + "\n");
    return 0;
  }

  let manifest;
  try {
    const majorVersion = Number.parseInt(process.versions.node.split(".")[0], 10);
    contract(majorVersion >= 22, "Node.js 22 or newer is required for native CDP WebSocket");
    contract(typeof WebSocket === "function", "Node.js global WebSocket is unavailable");
    manifest = await readManifest(options.manifestPath, options.url);
    const browser = await findBrowser();
    const artifactsRoot = join(
      dirname(options.outputPath),
      basename(options.outputPath, extname(options.outputPath)) + "_artifacts",
    );
    if (options.reviewProjectionNegative) {
      const scenarioRuns = await runReviewProjectionNegativeSuite({
        browser,
        targetUrl: manifest.targetUrl,
        manifest: manifest.payload,
        runs: options.runs,
        artifactsRoot,
      });
      const negative = makeReviewProjectionNegativeReceipt({
        options,
        manifest,
        scenarioRuns,
      });
      const emitted = await emitReceipt(negative.receipt, options.outputPath);
      if (emitted.writeError) return 3;
      return negative.overallPass ? 0 : 2;
    }
    const browserRuns = [];
    for (let runIndex = 1; runIndex <= options.runs; runIndex += 1) {
      browserRuns.push(
        await runBrowserVerification({
          browser,
          targetUrl: manifest.targetUrl,
          manifest: manifest.payload,
          viewports: options.viewports,
          runIndex,
          artifactsRoot,
        }),
      );
    }
    const fingerprints = browserRuns
      .map((item) => item.build_assets?.asset_bundle_sha256)
      .filter((item) => typeof item === "string");
    const assetBundleConsistent =
      fingerprints.length === options.runs && new Set(fingerprints).size === 1;
    const passedRuns = browserRuns.filter(
      (item) => item.status === "PASS_LOCAL_UI_RUN",
    ).length;
    const authorityPassedRuns = browserRuns.filter(
      (item) =>
        item.authority_case?.status === "PASS_LOCAL_AUTHORITY_CASE",
    ).length;
    const authorityScreenshotCount = browserRuns.filter(
      (item) =>
        item.authority_case?.authority_screenshot &&
        SHA256_PATTERN.test(item.authority_case.authority_screenshot.sha256),
    ).length;
    const overallPass =
      passedRuns === options.runs && assetBundleConsistent;
    const receipt = {
      schema_version: RECEIPT_SCHEMA,
      status: overallPass
        ? "PASS_LOCAL_REVIEW_UI_VERIFIED"
        : "FAIL_CLOSED",
      generated_at_utc: new Date().toISOString(),
      request: {
        url: options.url,
        target_url: manifest.targetUrl,
        manifest_path: options.manifestPath,
        output_path: options.outputPath,
        runs: options.runs,
        viewports: options.viewports,
        node_version: process.version,
      },
      manifest: manifest.evidence,
      browser_runs: browserRuns,
      summary: {
        requested_runs: options.runs,
        completed_runs: browserRuns.length,
        passed_runs: passedRuns,
        failed_runs: browserRuns.length - passedRuns,
        authority_passed_runs: authorityPassedRuns,
        authority_screenshot_count: authorityScreenshotCount,
        asset_bundle_consistent: assetBundleConsistent,
        asset_bundle_sha256:
          assetBundleConsistent && fingerprints.length ? fingerprints[0] : null,
        console_warning_count: browserRuns.reduce(
          (total, item) => total + (item.console?.warning_count || 0),
          0,
        ),
        console_error_count: browserRuns.reduce(
          (total, item) => total + (item.console?.error_count || 0),
          0,
        ),
      },
      errors: browserRuns.flatMap((item) => item.errors || []),
      boundaries: {
        local_ui_verification_only: true,
        source_scope: manifest.payload.source_scope,
        production_release_allowed: false,
        machine_write_permitted: false,
        customer_validation: "NOT_CLAIMED",
        factory_shadow_metrics: "NOT_MEASURED_PENDING_ADJUDICATION",
        submission_eligible: false,
      },
      claim_boundary:
        "This receipt proves only a local served-UI run bound to the frozen synthetic semifinal manifest and hashed same-origin build assets. It is not factory shadow evidence, customer acceptance, production deployment, official submission, or production release.",
    };
    const emitted = await emitReceipt(receipt, options.outputPath);
    if (emitted.writeError) return 3;
    return overallPass ? 0 : 2;
  } catch (error) {
    const failure = makeFailureReceipt(error, argv);
    if (manifest?.evidence) failure.manifest = manifest.evidence;
    const emitted = await emitReceipt(failure, options.outputPath);
    return emitted.writeError ? 3 : 2;
  }
}

execute(process.argv.slice(2))
  .then((code) => {
    process.exitCode = code;
  })
  .catch(async (error) => {
    const outputPath = outputPathFromRawArgs(process.argv.slice(2));
    const emitted = await emitReceipt(
      makeFailureReceipt(error, process.argv.slice(2)),
      outputPath,
    );
    process.exitCode = emitted.writeError ? 3 : 2;
  });
