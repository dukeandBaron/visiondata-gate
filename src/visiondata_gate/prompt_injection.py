"""Deterministic preflight guard for untrusted model context.

This is a narrow, auditable defense-in-depth layer.  It detects a fixed family
of direct instruction, authority-escalation, exfiltration, tool-poisoning and
role-impersonation patterns (including simple base64/hex wrappers).  A match
blocks the optional model call and leaves the frozen Policy Judge untouched.
It is not represented as a universal prompt-injection solution.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
import html
import re
from typing import Literal
import unicodedata
import urllib.parse

from pydantic import BaseModel, ConfigDict, Field

from .evidence import canonical_json_bytes, sha256_bytes


class InjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InjectionMatch(InjectionModel):
    source_ref: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    representation: Literal["plain", "base64", "hex", "url"]
    decoding_chain: list[Literal["base64", "hex", "url"]] = Field(
        default_factory=list, max_length=2
    )
    category: Literal[
        "instruction_override",
        "policy_escalation",
        "secret_exfiltration",
        "tool_description_poisoning",
        "role_impersonation",
    ]
    rule_id: str = Field(min_length=1)


class PromptInjectionReceipt(InjectionModel):
    schema_version: Literal["visiondata-gate.prompt-injection-guard.v2"] = (
        "visiondata-gate.prompt-injection-guard.v2"
    )
    status: Literal[
        "CLEAR_LOCAL_RULESET",
        "BLOCKED_LOCAL_RULESET",
        "NOT_APPLICABLE_NO_MODEL_CALL",
    ]
    ruleset_sha256: str = Field(min_length=64, max_length=64)
    scan_input_sha256: str = Field(min_length=64, max_length=64)
    scanned_item_count: int = Field(ge=0)
    blocked_item_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    matched_categories: list[str] = Field(default_factory=list)
    matches: list[InjectionMatch] = Field(default_factory=list)
    remote_model_call_allowed: bool
    decoder_max_depth: Literal[2] = 2
    decoder_candidate_limit: Literal[32] = 32
    raw_content_retained: Literal[False] = False
    decision_authority: Literal["frozen_policy_judge_unchanged"] = (
        "frozen_policy_judge_unchanged"
    )
    limitation: str = (
        "Fixed deterministic rules and bounded decoding variants do not prove "
        "protection against adaptive or previously unseen prompt injection."
    )


_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_BASE64_TOKEN = re.compile(
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/])"
)
_HEX_TOKEN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{24,}(?![0-9A-Fa-f])")
_URL_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_MAX_DECODE_DEPTH = 2
_MAX_DECODE_CANDIDATES = 32
_MAX_ENCODED_TOKEN_CHARS = 16_384
_MAX_DECODED_BYTES = 8_192

DecodeKind = Literal["base64", "hex", "url"]
Representation = Literal["plain", "base64", "hex", "url"]


_RULES: tuple[
    tuple[
        str,
        Literal[
            "instruction_override",
            "policy_escalation",
            "secret_exfiltration",
            "tool_description_poisoning",
            "role_impersonation",
        ],
        re.Pattern[str],
    ],
    ...,
] = (
    (
        "override.en.v1",
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b.{0,80}"
            r"\b(previous|prior|system|developer|policy|instructions?|rules?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "override.zh.v1",
        "instruction_override",
        re.compile(
            r"(忽略|无视|忘掉|绕过|覆盖).{0,40}(之前|先前|系统|开发者|策略|规则|指令|提示)"
        ),
    ),
    (
        "policy.en.v1",
        "policy_escalation",
        re.compile(
            r"\b(policy judge|release gate|final decision|decision authority)\b"
            r".{0,80}\b(pass|approve|override|bypass|grant)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "policy.zh.v1",
        "policy_escalation",
        re.compile(
            r"(策略裁决|最终决定|发布门禁|决策权限).{0,40}(通过|批准|覆盖|绕过|授权)"
        ),
    ),
    (
        "exfil.en.v1",
        "secret_exfiltration",
        re.compile(
            r"\b(reveal|print|show|leak|exfiltrate|dump)\b.{0,80}"
            r"\b(system prompt|developer message|api[ -]?key|secret|access token)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "exfil.zh.v1",
        "secret_exfiltration",
        re.compile(
            r"(显示|打印|泄露|导出|窃取).{0,40}(系统提示词|开发者消息|API.?密钥|秘密|访问令牌)"
        ),
    ),
    (
        "tool.en.v1",
        "tool_description_poisoning",
        re.compile(
            r"\b(tool description|tool output|function result|plugin description)\b"
            r".{0,100}\b(ignore|execute|invoke|call|override|instruction)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "tool.zh.v1",
        "tool_description_poisoning",
        re.compile(
            r"(工具描述|工具输出|函数结果|插件说明).{0,50}(忽略|执行|调用|覆盖|指令)"
        ),
    ),
    (
        "role.en.v1",
        "role_impersonation",
        re.compile(
            r"\b(you are now|act as|switch role to|message from)\b.{0,60}"
            r"\b(system|developer|administrator|root|policy judge)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role.zh.v1",
        "role_impersonation",
        re.compile(
            r"(你现在是|扮演|切换角色为|来自).{0,40}(系统|开发者|管理员|超级用户|策略裁决器)"
        ),
    ),
)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(text))
    value = _ZERO_WIDTH.sub("", value)
    return " ".join(value.split())


def _printable_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    printable = sum(
        character.isprintable() or character.isspace() for character in text
    )
    return text if printable / len(text) >= 0.9 else None


def _decode_token(kind: DecodeKind, token: str) -> str | None:
    if len(token) > _MAX_ENCODED_TOKEN_CHARS:
        return None
    try:
        if kind == "base64":
            raw = base64.b64decode(token, validate=True)
        elif kind == "hex":
            if len(token) % 2:
                return None
            raw = bytes.fromhex(token)
        else:
            raw = urllib.parse.unquote_to_bytes(token)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > _MAX_DECODED_BYTES:
        return None
    rendered = _printable_text(raw)
    return _normalize(rendered) if rendered is not None else None


def _representations(
    text: str,
) -> list[tuple[Representation, str, tuple[DecodeKind, ...]]]:
    """Return a bounded breadth-first set of decoded representations.

    Depth and candidate caps keep encoded untrusted context from turning the
    preflight guard into an unbounded decoder.  The chain is retained as safe
    metadata while raw or decoded content is never written to the receipt.
    """

    normalized = _normalize(text)
    values: list[tuple[Representation, str, tuple[DecodeKind, ...]]] = [
        ("plain", normalized, ())
    ]
    queue: list[tuple[str, tuple[DecodeKind, ...]]] = [(normalized, ())]
    seen: set[tuple[str, tuple[DecodeKind, ...]]] = {(normalized, ())}
    decoders: tuple[tuple[DecodeKind, re.Pattern[str]], ...] = (
        ("base64", _BASE64_TOKEN),
        ("hex", _HEX_TOKEN),
    )
    while queue and len(values) < _MAX_DECODE_CANDIDATES:
        candidate, chain = queue.pop(0)
        if len(chain) >= _MAX_DECODE_DEPTH:
            continue
        for kind, pattern in decoders:
            for token in pattern.findall(candidate):
                decoded = _decode_token(kind, token)
                if not decoded:
                    continue
                next_chain = (*chain, kind)
                key = (decoded, next_chain)
                if key in seen:
                    continue
                seen.add(key)
                values.append((kind, decoded, next_chain))
                if len(values) >= _MAX_DECODE_CANDIDATES:
                    break
                queue.append((decoded, next_chain))
            if len(values) >= _MAX_DECODE_CANDIDATES:
                break
        if (
            len(values) < _MAX_DECODE_CANDIDATES
            and len(_URL_ESCAPE.findall(candidate)) >= 2
        ):
            decoded = _decode_token("url", candidate)
            if decoded:
                next_chain = (*chain, "url")
                key = (decoded, next_chain)
                if key not in seen:
                    seen.add(key)
                    values.append(("url", decoded, next_chain))
                    if len(values) < _MAX_DECODE_CANDIDATES:
                        queue.append((decoded, next_chain))
    return values


def ruleset_sha256() -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "schema_version": "visiondata-gate.prompt-injection-guard.v2",
                "rules": [
                    {
                        "rule_id": rule_id,
                        "category": category,
                        "pattern": pattern.pattern,
                    }
                    for rule_id, category, pattern in _RULES
                ],
                "decoder_policy": {
                    "max_depth": _MAX_DECODE_DEPTH,
                    "candidate_limit": _MAX_DECODE_CANDIDATES,
                    "encoded_token_char_limit": _MAX_ENCODED_TOKEN_CHARS,
                    "decoded_byte_limit": _MAX_DECODED_BYTES,
                    "decoders": ["base64", "hex", "url"],
                    "normalizers": [
                        "html_unescape",
                        "NFKC",
                        "zero_width_removal",
                        "whitespace_collapse",
                    ],
                },
            }
        )
    )


def scan_untrusted_context(
    items: Mapping[str, str],
    *,
    model_call_applicable: bool = True,
) -> PromptInjectionReceipt:
    """Hash and scan untrusted context; never retain the supplied raw text."""

    matches: list[InjectionMatch] = []
    blocked_refs: set[str] = set()
    digests: list[dict[str, str]] = []
    for source_ref, raw in sorted(items.items()):
        content_sha256 = sha256_bytes(raw.encode("utf-8"))
        digests.append({"source_ref": source_ref, "content_sha256": content_sha256})
        seen: set[tuple[str, tuple[DecodeKind, ...]]] = set()
        for representation, candidate, decoding_chain in _representations(raw):
            for rule_id, category, pattern in _RULES:
                key = (rule_id, decoding_chain)
                if key in seen or not pattern.search(candidate):
                    continue
                seen.add(key)
                blocked_refs.add(source_ref)
                matches.append(
                    InjectionMatch(
                        source_ref=source_ref,
                        content_sha256=content_sha256,
                        representation=representation,
                        decoding_chain=list(decoding_chain),
                        category=category,
                        rule_id=rule_id,
                    )
                )
    matches.sort(
        key=lambda item: (
            item.source_ref,
            item.rule_id,
            item.representation,
            item.decoding_chain,
        )
    )
    if not model_call_applicable:
        status: Literal[
            "CLEAR_LOCAL_RULESET",
            "BLOCKED_LOCAL_RULESET",
            "NOT_APPLICABLE_NO_MODEL_CALL",
        ] = "NOT_APPLICABLE_NO_MODEL_CALL"
    else:
        status = "BLOCKED_LOCAL_RULESET" if matches else "CLEAR_LOCAL_RULESET"
    return PromptInjectionReceipt(
        status=status,
        ruleset_sha256=ruleset_sha256(),
        scan_input_sha256=sha256_bytes(canonical_json_bytes(digests)),
        scanned_item_count=len(items),
        blocked_item_count=len(blocked_refs),
        match_count=len(matches),
        matched_categories=sorted({item.category for item in matches}),
        matches=matches,
        remote_model_call_allowed=model_call_applicable and not matches,
    )


def context_from_facts(facts: Sequence[object]) -> dict[str, str]:
    """Extract ``ref``/``text`` pairs without importing the grounding module."""

    output: dict[str, str] = {}
    for item in facts:
        ref = getattr(item, "ref", None)
        text = getattr(item, "text", None)
        if isinstance(ref, str) and isinstance(text, str):
            output[ref] = text
    return output


__all__ = [
    "InjectionMatch",
    "PromptInjectionReceipt",
    "context_from_facts",
    "ruleset_sha256",
    "scan_untrusted_context",
]
