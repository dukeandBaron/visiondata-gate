/**
 * Minimal RFC 8785 JSON Canonicalization Scheme encoder for JSON values.
 *
 * Response contracts are parsed before they reach this helper, so the input
 * domain is deliberately limited to JSON primitives, arrays, and plain
 * objects.  Object keys are ordered with JavaScript's UTF-16 lexical order,
 * and number serialization is delegated to JSON.stringify as required by
 * RFC 8785 / ECMAScript.
 */
function assertUnicodeScalarString(value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) {
        throw new TypeError("JCS does not permit an unpaired high surrogate");
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new TypeError("JCS does not permit an unpaired low surrogate");
    }
  }
}

export function canonicalizeJcs(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") {
    assertUnicodeScalarString(value);
    return JSON.stringify(value);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("JCS does not permit non-finite numbers");
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new TypeError("JCS integer exceeds the browser safe-integer domain");
    }
    return Object.is(value, -0) ? "0" : JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalizeJcs(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const object = value as Record<string, unknown>;
    const fields = Object.keys(object)
      .sort()
      .map((key) => {
        assertUnicodeScalarString(key);
        return `${JSON.stringify(key)}:${canonicalizeJcs(object[key])}`;
      });
    return `{${fields.join(",")}}`;
  }
  throw new TypeError(`JCS cannot encode ${typeof value}`);
}

export async function sha256HexUtf8(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is unavailable");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function detachedJcsSha256(
  value: Record<string, unknown>,
  digestField: string,
): Promise<string> {
  const payload = { ...value };
  delete payload[digestField];
  return sha256HexUtf8(canonicalizeJcs(payload));
}
