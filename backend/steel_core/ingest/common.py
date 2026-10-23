from dataclasses import dataclass


@dataclass(frozen=True)
class ParseIssue:
    row_no: int | None
    field: str | None
    message: str
