"""Render a Pydantic model as a compact field spec instead of JSON Schema.

Pydantic's `model_json_schema()` is correct but extremely verbose. Every
`Optional[str]` becomes:

    "customer_name": {
      "anyOf": [{"type": "string"}, {"type": "null"}],
      "default": null,
      "description": "...",
      "title": "Customer Name"
    }

For the 27-field complaint schema that is ~2,050 tokens, sent on *every*
extraction call. The same information as a field list is around a quarter of
that, and models follow it just as well - the descriptions are what actually
steer extraction, not the JSON Schema envelope.

This matters because Groq's free tier allows 200,000 tokens per day, and the
agent makes several calls per complaint.
"""
from __future__ import annotations

import types
import typing
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

_SIMPLE = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _render_type(annotation: Any, nested: list[type[BaseModel]]) -> str:
    """Describe a type in a few words, collecting nested models to expand."""
    origin = get_origin(annotation)

    # Optional[X] / X | None
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        rendered = "|".join(_render_type(a, nested) for a in args)
        return f"{rendered}|null" if len(args) < len(get_args(annotation)) else rendered

    if origin is Literal:
        return "one of: " + ", ".join(repr(v) for v in get_args(annotation))

    if origin in (list, typing.List):
        (inner,) = get_args(annotation) or (str,)
        return f"array of {_render_type(inner, nested)}"

    if origin in (dict, typing.Dict):
        return "object"

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation not in nested:
            nested.append(annotation)
        return annotation.__name__

    if annotation in _SIMPLE:
        return _SIMPLE[annotation]

    return getattr(annotation, "__name__", str(annotation))


def _render_model(model: type[BaseModel], nested: list[type[BaseModel]]) -> list[str]:
    lines = []
    for name, field in model.model_fields.items():
        type_text = _render_type(field.annotation, nested)
        required = "required" if field.is_required() else "optional"

        bits = [f"- {name} ({type_text}, {required})"]
        if field.description:
            bits.append(f": {field.description}")
        lines.append("".join(bits))
    return lines


def compact_schema(model: type[BaseModel]) -> str:
    """Return a terse, complete field spec for `model`.

    Nested models are expanded once, after the top-level fields.
    """
    nested: list[type[BaseModel]] = []
    lines = _render_model(model, nested)

    # Expand nested models breadth-first; the list grows as we walk it.
    seen: set[type[BaseModel]] = set()
    index = 0
    while index < len(nested):
        sub = nested[index]
        index += 1
        if sub in seen:
            continue
        seen.add(sub)
        lines.append("")
        lines.append(f"{sub.__name__} fields:")
        lines.extend("  " + line for line in _render_model(sub, nested))

    return "\n".join(lines)
