const outcomeFrameMagic = "visiondata-gate.outcome-frame.v1\u0000";
const outcomeRootDomain = "visiondata-gate/outcome/root/v1";

class LosslessJsonNumber {
  readonly raw: string;

  constructor(raw: string) {
    this.raw = raw;
  }
}

type LosslessJsonValue =
  | null
  | boolean
  | string
  | LosslessJsonNumber
  | LosslessJsonValue[]
  | { [key: string]: LosslessJsonValue };

class LosslessJsonParser {
  private position = 0;
  private readonly source: string;

  constructor(source: string) {
    this.source = source;
  }

  parse(): LosslessJsonValue {
    const value = this.parseValue();
    this.skipWhitespace();
    if (this.position !== this.source.length) {
      throw new Error("JSON 响应包含多余内容");
    }
    return value;
  }

  private parseValue(): LosslessJsonValue {
    this.skipWhitespace();
    const current = this.source.charAt(this.position);
    if (current === "{") return this.parseObject();
    if (current === "[") return this.parseArray();
    if (current === '"') return this.parseString();
    if (current === "-" || (current >= "0" && current <= "9")) {
      return this.parseNumber();
    }
    if (this.consumeLiteral("true")) return true;
    if (this.consumeLiteral("false")) return false;
    if (this.consumeLiteral("null")) return null;
    throw new Error(`JSON 响应在偏移 ${this.position} 处无效`);
  }

  private parseObject(): { [key: string]: LosslessJsonValue } {
    const value: { [key: string]: LosslessJsonValue } = {};
    this.position += 1;
    this.skipWhitespace();
    if (this.source[this.position] === "}") {
      this.position += 1;
      return value;
    }
    while (this.position < this.source.length) {
      if (this.source[this.position] !== '"') {
        throw new Error(`JSON 对象在偏移 ${this.position} 处缺少成员名`);
      }
      const key = this.parseString();
      if (Object.prototype.hasOwnProperty.call(value, key)) {
        throw new Error(`JSON 响应包含重复成员 ${key}`);
      }
      this.skipWhitespace();
      if (this.source[this.position] !== ":") {
        throw new Error(`JSON 对象成员 ${key} 缺少冒号`);
      }
      this.position += 1;
      value[key] = this.parseValue();
      this.skipWhitespace();
      const separator = this.source[this.position];
      if (separator === "}") {
        this.position += 1;
        return value;
      }
      if (separator !== ",") {
        throw new Error(`JSON 对象在偏移 ${this.position} 处缺少分隔符`);
      }
      this.position += 1;
      this.skipWhitespace();
    }
    throw new Error("JSON 对象未闭合");
  }

  private parseArray(): LosslessJsonValue[] {
    const value: LosslessJsonValue[] = [];
    this.position += 1;
    this.skipWhitespace();
    if (this.source[this.position] === "]") {
      this.position += 1;
      return value;
    }
    while (this.position < this.source.length) {
      value.push(this.parseValue());
      this.skipWhitespace();
      const separator = this.source[this.position];
      if (separator === "]") {
        this.position += 1;
        return value;
      }
      if (separator !== ",") {
        throw new Error(`JSON 数组在偏移 ${this.position} 处缺少分隔符`);
      }
      this.position += 1;
    }
    throw new Error("JSON 数组未闭合");
  }

  private parseString(): string {
    const start = this.position;
    this.position += 1;
    while (this.position < this.source.length) {
      const current = this.source.charAt(this.position);
      if (current === '"') {
        this.position += 1;
        const decoded = JSON.parse(this.source.slice(start, this.position)) as unknown;
        if (typeof decoded !== "string") throw new Error("JSON 字符串解码失败");
        return decoded;
      }
      if (current === "\\") {
        this.position += 1;
        const escaped = this.source[this.position];
        if (escaped === "u") {
          const hex = this.source.slice(this.position + 1, this.position + 5);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) throw new Error("JSON Unicode 转义无效");
          this.position += 5;
          continue;
        }
        if (!escaped || !'"\\/bfnrt'.includes(escaped)) {
          throw new Error("JSON 字符串转义无效");
        }
        this.position += 1;
        continue;
      }
      if (current.charCodeAt(0) < 0x20) throw new Error("JSON 字符串包含控制字符");
      this.position += 1;
    }
    throw new Error("JSON 字符串未闭合");
  }

  private parseNumber(): LosslessJsonNumber {
    const match = this.source.slice(this.position).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (!match) throw new Error(`JSON 数字在偏移 ${this.position} 处无效`);
    this.position += match[0].length;
    return new LosslessJsonNumber(match[0]);
  }

  private consumeLiteral(literal: "true" | "false" | "null"): boolean {
    if (!this.source.startsWith(literal, this.position)) return false;
    this.position += literal.length;
    return true;
  }

  private skipWhitespace(): void {
    while (/\s/.test(this.source[this.position] ?? "")) this.position += 1;
  }
}

function compareUnicodeCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) => character.codePointAt(0) ?? 0);
  const rightPoints = Array.from(right, (character) => character.codePointAt(0) ?? 0);
  const count = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < count; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) return leftPoints[index]! - rightPoints[index]!;
  }
  return leftPoints.length - rightPoints.length;
}

function serializePythonCanonical(
  value: LosslessJsonValue,
  omittedTopLevelKeys: ReadonlySet<string>,
  depth = 0,
): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (value instanceof LosslessJsonNumber) return value.raw;
  if (Array.isArray(value)) {
    return `[${value.map((item) => serializePythonCanonical(item, omittedTopLevelKeys, depth + 1)).join(",")}]`;
  }
  const keys = Object.keys(value)
    .filter((key) => depth !== 0 || !omittedTopLevelKeys.has(key))
    .sort(compareUnicodeCodePoints);
  return `{${keys.map((key) => `${JSON.stringify(key)}:${serializePythonCanonical(value[key]!, omittedTopLevelKeys, depth + 1)}`).join(",")}}`;
}

function assertUnicodeScalarString(value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) throw new Error("JCS 字符串包含未配对高代理项");
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new Error("JCS 字符串包含未配对低代理项");
    }
  }
}

function serializeJcs(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") {
    assertUnicodeScalarString(value);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("JCS 不接受 NaN 或 Infinity");
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new Error("JCS 整数超出浏览器可安全校验范围");
    }
    const serialized = JSON.stringify(value);
    if (serialized === undefined) throw new Error("JCS 数字序列化失败");
    return serialized;
  }
  if (Array.isArray(value)) return `[${value.map(serializeJcs).join(",")}]`;
  if (typeof value !== "object" || value === undefined) throw new Error("JCS 响应包含非 JSON 值");
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  return `{${keys.map((key) => {
    assertUnicodeScalarString(key);
    return `${JSON.stringify(key)}:${serializeJcs(record[key])}`;
  }).join(",")}}`;
}

function concatBytes(parts: readonly Uint8Array[]): Uint8Array {
  const result = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error("当前浏览器不支持 Web Crypto SHA-256");
  const material = new Uint8Array(bytes.length);
  material.set(bytes);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", material.buffer);
  return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, "0")).join("");
}

export async function pythonCanonicalSha256FromJson(
  source: string,
  omittedTopLevelKeys: readonly string[] = [],
): Promise<string> {
  const parsed = new LosslessJsonParser(source).parse();
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed) || parsed instanceof LosslessJsonNumber) {
    throw new Error("受控回执必须是 JSON 对象");
  }
  const canonical = `${serializePythonCanonical(parsed, new Set(omittedTopLevelKeys))}\n`;
  return sha256Hex(new TextEncoder().encode(canonical));
}

export async function pythonCanonicalSha256FromJsonValue(
  source: string,
): Promise<string> {
  const parsed = new LosslessJsonParser(source).parse();
  const canonical = `${serializePythonCanonical(parsed, new Set())}\n`;
  return sha256Hex(new TextEncoder().encode(canonical));
}

export async function governedOutcomeRootSha256(value: unknown): Promise<string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Governed Outcome 必须是 JSON 对象");
  }
  const { outcome_root: _omitted, ...payload } = value as Record<string, unknown>;
  const payloadBytes = new TextEncoder().encode(serializeJcs(payload));
  const magicBytes = new TextEncoder().encode(outcomeFrameMagic);
  const domainBytes = new TextEncoder().encode(outcomeRootDomain);
  if (domainBytes.length > 0xffff) throw new Error("Outcome Root domain 过长");
  const domainLength = new Uint8Array(2);
  new DataView(domainLength.buffer).setUint16(0, domainBytes.length, false);
  const payloadLength = new Uint8Array(8);
  new DataView(payloadLength.buffer).setBigUint64(0, BigInt(payloadBytes.length), false);
  return sha256Hex(concatBytes([
    magicBytes,
    domainLength,
    domainBytes,
    payloadLength,
    payloadBytes,
  ]));
}
