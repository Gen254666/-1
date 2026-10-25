from __future__ import annotations


def build_watermark(
    *,
    username: str,
    export_id: str,
    export_time: str,
    scope: str,
) -> str:
    return (
        f"> 导出人：{username} ｜ 导出时间：{export_time} ｜ "
        f"导出编号：{export_id} ｜ {scope}仅限内部使用，请勿外传"
    )


def apply_watermark(markdown: str, watermark: str) -> str:
    return f"{watermark}\n\n{markdown.rstrip()}\n\n{watermark}\n"
