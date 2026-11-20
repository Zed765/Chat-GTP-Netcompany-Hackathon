"""Reads policy YAML while remembering the line of every key, so validation can point at it."""

import re
from dataclasses import dataclass
from typing import Any, cast

import yaml

Path = tuple[str | int, ...]

_BOOL_TAG = "tag:yaml.org,2002:bool"


class YamlSyntaxError(ValueError):
    def __init__(self, message: str, line: int | None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


class _Loader(yaml.SafeLoader):
    """Safe loading with YAML 1.2 booleans, so `off` stays the word the policy means, and
    without anchors and aliases: a few lines of nested aliases stand for millions of nodes."""

    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
        event = cast(yaml.Event, self.peek_event())  # type: ignore[no-untyped-call]
        if isinstance(event, yaml.NodeEvent) and event.anchor is not None:
            kind = "alias" if isinstance(event, yaml.AliasEvent) else "anchor"
            raise YamlSyntaxError(
                f"Anchors and aliases are not supported in a policy, and this is an {kind}: "
                "write the value out where it is used",
                event.start_mark.line + 1 if event.start_mark else None,
            )
        return super().compose_node(parent, index)


_Loader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != _BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    _BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


@dataclass(frozen=True)
class Source:
    data: Any
    lines: dict[Path, int]
    duplicate_keys: tuple[Path, ...]

    def locate(self, path: Path) -> tuple[Path, int | None]:
        """The deepest part of `path` that exists in the text, and its line."""
        while path and path not in self.lines:
            path = path[:-1]
        return path, self.lines.get(path)


def load(text: str) -> Source:
    try:
        loader = _Loader(text)
        try:
            node = loader.get_single_node()
            data = loader.construct_document(node) if node is not None else None
        finally:
            loader.dispose()
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        raise YamlSyntaxError(
            f"This is not valid YAML: {exc.problem or 'syntax error'}",
            mark.line + 1 if mark else None,
        ) from exc
    except yaml.YAMLError as exc:
        raise YamlSyntaxError("This is not valid YAML", None) from exc
    except RecursionError as exc:
        raise YamlSyntaxError("This is not valid YAML: it is nested too deeply", None) from exc
    lines: dict[Path, int] = {}
    duplicates: list[Path] = []
    if node is not None:
        _index(node, (), lines, duplicates)
    return Source(data=data, lines=lines, duplicate_keys=tuple(duplicates))


def _index(node: yaml.Node, path: Path, lines: dict[Path, int], duplicates: list[Path]) -> None:
    lines[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            key = str(key_node.value)
            child = (*path, key)
            if key in seen:
                duplicates.append(child)
            seen.add(key)
            _index(value_node, child, lines, duplicates)
            lines[child] = key_node.start_mark.line + 1
    elif isinstance(node, yaml.SequenceNode):
        for position, item in enumerate(node.value):
            _index(item, (*path, position), lines, duplicates)


def format_path(path: Path) -> str:
    """`("rules", 2, "when", "data")` becomes `rules[2].when.data`."""
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else f".{part}" if text else part
    return text or "(document)"
