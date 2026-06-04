"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.util import find_spec


is_msgspec_installed = find_spec("msgspec") is not None
is_pydantic_installed = find_spec("pydantic") is not None
