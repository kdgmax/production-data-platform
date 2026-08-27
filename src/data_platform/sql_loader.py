"""Load version-controlled SQL shipped with the Python package."""

from importlib.resources import files


def read_sql(*path_parts: str) -> str:
    return files("data_platform").joinpath("sql", *path_parts).read_text(encoding="utf-8")
