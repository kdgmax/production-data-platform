"""Load version-controlled SQL shipped with the Python package."""

from importlib.resources import files


def read_sql(filename: str) -> str:
    return files("data_platform").joinpath("sql", filename).read_text(encoding="utf-8")

