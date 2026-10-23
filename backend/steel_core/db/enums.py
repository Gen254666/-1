from enum import StrEnum

from sqlalchemy import Enum


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class PointScope(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class DatasetType(StrEnum):
    MARKET_QUOTE = "market_quote"
    INVENTORY = "inventory"


class VersionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


class ImportStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )
