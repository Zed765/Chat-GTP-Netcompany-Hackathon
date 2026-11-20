"""Reads a request field by field, so that nothing the gateway has not looked at is forwarded.

Every string in a request is one of three things:

- free text the model reads (content, instructions, descriptions, tool results, function-call
  arguments): a `Slot`, which is detected and masked;
- a value from a closed set (a role, a type, a flag, a number): checked against that set;
- a string that steers the request and cannot carry a placeholder (a name, an ID, a stop
  sequence, the model, the names and literal values of a JSON schema): a `Name`, which
  detection reads as well and which has to come out clean.

Any other field is refused by name: a firewall that forwards what it did not look at would
show a masked trace while real values left by another door.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

USER_ROLE = "user"
_UNREADABLE = "the gateway cannot inspect it"
_UNEXPECTED = "it is not a value this field takes"
# A field or type name plain and short enough to repeat in an error message.
_PLAIN_NAME = re.compile(r"[A-Za-z_$][\w$.\-]{0,39}")


class UninspectedError(ValueError):
    """The request holds something the gateway will not forward."""

    def __init__(self, where: str, reason: str = _UNREADABLE) -> None:
        super().__init__(f"`{where}` is not forwarded: {reason}")
        self.where = where


@dataclass(frozen=True)
class Slot:
    """One free text, addressed by where it sits in the request."""

    holder: Any
    key: str | int
    authored: bool = False
    instructions: bool = False

    def read(self) -> str:
        return str(self.holder[self.key])

    def write(self, text: str) -> None:
        self.holder[self.key] = text


@dataclass(frozen=True)
class Name:
    """A string that cannot carry a placeholder, and the field it was read from."""

    where: str
    value: str


@dataclass(frozen=True)
class Reading:
    """What a request holds. Texts run from definitions to the conversation, oldest turn
    first, so the last text is the newest."""

    texts: tuple[Slot, ...]
    names: tuple[Name, ...]


@dataclass
class _Reader:
    opaque_allowed: bool
    texts: list[Slot] = field(default_factory=list)
    names: list[Name] = field(default_factory=list)
    speaker: str | None = None


# Reads `holder[key]`, which sits at `where` in the request.
Check = Callable[[_Reader, Any, Any, str], None]


def _at(where: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{where}[{key}]"
    return f"{where}.{key}" if where else key


def _plain(name: object, otherwise: str) -> str:
    return name if isinstance(name, str) and _PLAIN_NAME.fullmatch(name) else otherwise


def _record(reader: _Reader, node: Any, where: str, fields: Mapping[str, Check]) -> None:
    """An object whose every key must be a known field. `null` is a field left out."""
    if not isinstance(node, dict):
        raise UninspectedError(where, _UNEXPECTED)
    for position, key in enumerate(node):
        if key not in fields:
            raise UninspectedError(_at(where, _plain(key, f"<field {position + 1}>")))
    for key, check in fields.items():
        if node.get(key) is not None:
            check(reader, node, key, _at(where, key))


def _text(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    if not isinstance(holder[key], str):
        raise UninspectedError(where, _UNEXPECTED)
    reader.texts.append(Slot(holder, key, authored=reader.speaker == USER_ROLE))


def _instructions(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    if not isinstance(holder[key], str):
        raise UninspectedError(where, _UNEXPECTED)
    reader.texts.append(Slot(holder, key, instructions=True))


def _name(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    if not isinstance(holder[key], str):
        raise UninspectedError(where, _UNEXPECTED)
    reader.names.append(Name(where, holder[key]))


def _flag(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    if not isinstance(holder[key], bool):
        raise UninspectedError(where, _UNEXPECTED)


def _number(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    if isinstance(holder[key], bool) or not isinstance(holder[key], int | float):
        raise UninspectedError(where, _UNEXPECTED)


def _integer(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    if isinstance(holder[key], bool) or not isinstance(holder[key], int):
        raise UninspectedError(where, _UNEXPECTED)


def _empty(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    """A list the gateway forwards only when it holds nothing, such as annotations."""
    if holder[key] != []:
        raise UninspectedError(where)


def _opaque(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    """Content the gateway cannot read passes only to a tool the company trusts with it."""
    if not reader.opaque_allowed:
        raise UninspectedError(where)


def _checked(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    """A field its parent has already read."""


def _one_of(*allowed: str) -> Check:
    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        if not isinstance(holder[key], str) or holder[key] not in allowed:
            raise UninspectedError(where, _UNEXPECTED)

    return check


def _role(*allowed: str) -> Check:
    known = _one_of(*allowed)

    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        known(reader, holder, key, where)
        reader.speaker = holder[key]

    return check


def _object(fields: Mapping[str, Check]) -> Check:
    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        _record(reader, holder[key], where, fields)

    return check


def _each(item: Check) -> Check:
    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        if not isinstance(holder[key], list):
            raise UninspectedError(where, _UNEXPECTED)
        for index in range(len(holder[key])):
            item(reader, holder[key], index, _at(where, index))

    return check


def _turns(turn: Check) -> Check:
    """The messages or items of a conversation. Each starts with nobody speaking, so the
    role of one message never marks the text of the next."""

    def one(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        reader.speaker = None
        turn(reader, holder, key, where)
        reader.speaker = None

    return _each(one)


def _string_or(string: Check, otherwise: Check) -> Check:
    """A field that takes a string or something else, each read its own way."""

    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        (string if isinstance(holder[key], str) else otherwise)(reader, holder, key, where)

    return check


def _variant(kinds: Mapping[str, Mapping[str, Check] | None], default: str | None = None) -> Check:
    """An object whose `type` picks its fields. `None` marks a kind the gateway cannot
    read, such as an image."""
    tables = {
        kind: None if fields is None else {"type": _checked, **fields}
        for kind, fields in kinds.items()
    }

    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        node = holder[key]
        kind = node.get("type", default) if isinstance(node, dict) else None
        if not isinstance(kind, str) or kind not in tables:
            raise UninspectedError(f"{where} ({_plain(kind, 'unknown type')})")
        fields = tables[kind]
        if fields is not None:
            _record(reader, node, where, fields)
        elif not reader.opaque_allowed:
            raise UninspectedError(f"{where} ({kind})")

    return check


def _named(entry: Check) -> Check:
    """An object keyed by names the client chose, such as the properties of a schema. A
    name can hold anything, so an entry is addressed by its position."""

    def check(reader: _Reader, holder: Any, key: Any, where: str) -> None:
        if not isinstance(holder[key], dict):
            raise UninspectedError(where, _UNEXPECTED)
        for position, name in enumerate(holder[key]):
            reader.names.append(Name(f"{_at(where, position)} (name)", name))
            if holder[key][name] is not None:
                entry(reader, holder[key], name, _at(where, position))

    return check


def _literal(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    """A JSON value written into a schema: every string and number in it is a name."""
    value = holder[key]
    if isinstance(value, str):
        reader.names.append(Name(where, value))
    elif isinstance(value, list):
        _each(_literal)(reader, holder, key, where)
    elif isinstance(value, dict):
        _named(_literal)(reader, holder, key, where)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        reader.names.append(Name(where, str(value)))


def _schema(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    """A JSON Schema. Its descriptions are text; its names and literal values are names."""
    if not isinstance(holder[key], bool):
        _record(reader, holder[key], where, _SCHEMA)


def _schemas(reader: _Reader, holder: Any, key: Any, where: str) -> None:
    (_each(_schema) if isinstance(holder[key], list) else _schema)(reader, holder, key, where)


_SCHEMA_TYPE = _one_of("object", "array", "string", "number", "integer", "boolean", "null")
_SCHEMA: dict[str, Check] = {
    "$schema": _name,
    "$id": _name,
    "$ref": _name,
    "$defs": _named(_schema),
    "definitions": _named(_schema),
    "title": _name,
    "description": _text,
    "type": _string_or(_SCHEMA_TYPE, _each(_SCHEMA_TYPE)),
    "format": _name,
    "pattern": _name,
    "enum": _each(_literal),
    "const": _literal,
    "default": _literal,
    "examples": _each(_literal),
    "properties": _named(_schema),
    "required": _each(_name),
    "additionalProperties": _schema,
    "items": _schemas,
    "prefixItems": _each(_schema),
    "anyOf": _each(_schema),
    "oneOf": _each(_schema),
    "allOf": _each(_schema),
    "not": _schema,
    "minimum": _number,
    "maximum": _number,
    "exclusiveMinimum": _number,
    "exclusiveMaximum": _number,
    "multipleOf": _number,
    "minLength": _integer,
    "maxLength": _integer,
    "minItems": _integer,
    "maxItems": _integer,
    "minProperties": _integer,
    "maxProperties": _integer,
    "uniqueItems": _flag,
    "nullable": _flag,
    "readOnly": _flag,
    "writeOnly": _flag,
    "deprecated": _flag,
}

_EFFORT = _one_of("none", "minimal", "low", "medium", "high", "xhigh", "max")
_VERBOSITY = _one_of("low", "medium", "high")
_SUMMARY = _one_of("auto", "concise", "detailed")
_STATUS = _one_of("in_progress", "completed", "incomplete")
_SERVICE_TIER = _one_of("auto", "default", "flex", "scale", "priority", "fast")
_TOOL_CHOICE = _one_of("none", "auto", "required")
_FUNCTION_TYPE = _one_of("function")

# Images, audio and files cannot be inspected.
_UNREADABLE_PARTS = dict.fromkeys(("image_url", "input_image", "input_audio", "file", "input_file"))
_PARTS = _each(
    _variant(
        {
            "text": {"text": _text},
            "input_text": {"text": _text},
            "output_text": {"text": _text, "annotations": _empty, "logprobs": _empty},
            "refusal": {"refusal": _text},
            **_UNREADABLE_PARTS,
        }
    )
)
_CONTENT = _string_or(_text, _PARTS)
_JSON_SCHEMA: dict[str, Check] = {
    "name": _name,
    "description": _text,
    "schema": _schema,
    "strict": _flag,
}
_FUNCTION: dict[str, Check] = {
    "name": _name,
    "description": _text,
    "parameters": _schema,
    "strict": _flag,
}
_CALL: dict[str, Check] = {"name": _name, "arguments": _text}

_CHAT: dict[str, Check] = {
    "model": _name,
    "stream": _flag,
    "stream_options": _object({"include_usage": _flag, "include_obfuscation": _flag}),
    "temperature": _number,
    "top_p": _number,
    "n": _integer,
    "seed": _integer,
    "max_tokens": _integer,
    "max_completion_tokens": _integer,
    "presence_penalty": _number,
    "frequency_penalty": _number,
    "logprobs": _flag,
    "top_logprobs": _integer,
    "stop": _string_or(_name, _each(_name)),
    "reasoning_effort": _EFFORT,
    "verbosity": _VERBOSITY,
    "parallel_tool_calls": _flag,
    "store": _flag,
    "service_tier": _SERVICE_TIER,
    "tool_choice": _string_or(
        _TOOL_CHOICE, _object({"type": _FUNCTION_TYPE, "function": _object({"name": _name})})
    ),
    "tools": _each(_object({"type": _FUNCTION_TYPE, "function": _object(_FUNCTION)})),
    "functions": _each(_object(_FUNCTION)),
    "response_format": _variant(
        {"text": {}, "json_object": {}, "json_schema": {"json_schema": _object(_JSON_SCHEMA)}}
    ),
    "messages": _turns(
        _object(
            {
                "role": _role("system", "developer", "user", "assistant", "tool", "function"),
                "name": _name,
                "content": _CONTENT,
                "refusal": _text,
                "tool_calls": _each(
                    _object({"id": _name, "type": _FUNCTION_TYPE, "function": _object(_CALL)})
                ),
                "function_call": _object(_CALL),
                "tool_call_id": _name,
            }
        )
    ),
}

_RESPONSES: dict[str, Check] = {
    "model": _name,
    "instructions": _instructions,
    "stream": _flag,
    "stream_options": _object({"include_obfuscation": _flag}),
    "temperature": _number,
    "top_p": _number,
    "max_output_tokens": _integer,
    "max_tool_calls": _integer,
    "top_logprobs": _integer,
    "reasoning": _object(
        {
            "effort": _EFFORT,
            "summary": _SUMMARY,
            "generate_summary": _SUMMARY,
            "context": _one_of("auto", "current_turn", "all_turns"),
        }
    ),
    "parallel_tool_calls": _flag,
    "truncation": _one_of("auto", "disabled"),
    "include": _each(
        _one_of(
            "reasoning.encrypted_content",
            "message.output_text.logprobs",
            "message.input_image.image_url",
        )
    ),
    "store": _flag,
    "service_tier": _SERVICE_TIER,
    "tool_choice": _string_or(_TOOL_CHOICE, _object({"type": _FUNCTION_TYPE, "name": _name})),
    "tools": _each(_variant({"function": _FUNCTION})),
    "text": _object(
        {
            "format": _variant({"text": {}, "json_object": {}, "json_schema": _JSON_SCHEMA}),
            "verbosity": _VERBOSITY,
        }
    ),
    "input": _turns(
        _variant(
            {
                "message": {
                    "role": _role("user", "assistant", "system", "developer"),
                    "content": _CONTENT,
                    "id": _name,
                    "status": _STATUS,
                    "phase": _one_of("commentary", "final_answer"),
                },
                "function_call": {
                    "call_id": _name,
                    "name": _name,
                    "arguments": _text,
                    "id": _name,
                    "status": _STATUS,
                },
                "function_call_output": {
                    "call_id": _name,
                    "output": _CONTENT,
                    "id": _name,
                    "status": _STATUS,
                },
                # The model's own reasoning, sent back so a stateless call can continue.
                "reasoning": {
                    "id": _name,
                    "summary": _each(_variant({"summary_text": {"text": _text}})),
                    "content": _each(_variant({"reasoning_text": {"text": _text}})),
                    "encrypted_content": _opaque,
                    "status": _STATUS,
                },
            },
            default="message",
        )
    ),
}


def _read(payload: dict[str, Any], fields: Mapping[str, Check], opaque_allowed: bool) -> Reading:
    reader = _Reader(opaque_allowed)
    _record(reader, payload, "", fields)
    return Reading(tuple(reader.texts), tuple(reader.names))


def read_chat(payload: dict[str, Any], *, opaque_allowed: bool) -> Reading:
    """Every text and name of a Chat Completions request. `opaque_allowed` lets through
    images and other content the gateway cannot read, for a tool the company trusts with
    raw data."""
    return _read(payload, _CHAT, opaque_allowed)


def read_responses(payload: dict[str, Any], *, opaque_allowed: bool) -> Reading:
    """Every text and name of a Responses request. `input` must already be a list of items."""
    return _read(payload, _RESPONSES, opaque_allowed)
