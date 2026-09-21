from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath


@dataclass(frozen=True)
class FileEntry:
    """文件条目。"""

    name: str
    path: Path
    is_dir: bool
    size: int
    modified: datetime | None
    type_name: str
    is_hidden: bool
    is_shortcut: bool = False


_SORT_FIELDS = ("name", "size", "type", "modified")
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")
# 文件分类
_CATEGORY_SUFFIXES: dict[str, str] = {}
for category, suffixes in (
    ("image", "png jpg jpeg gif bmp svg webp ico tiff heic avif"),
    ("video", "mp4 mkv avi mov wmv flv webm m4v"),
    ("audio", "mp3 wav flac aac ogg wma m4a opus"),
    ("archive", "zip rar 7z tar gz bz2 xz iso cab"),
    (
        "code",
        "py c cpp h hpp cs java js jsx ts tsx go rs rb php sh bat ps1 "
        "html css json yaml yml toml ini lua sql",
    ),
    ("doc", "txt md pdf doc docx xls xlsx ppt pptx rtf odt csv log"),
    ("exec", "exe msi bat cmd com scr app"),
):
    for suffix in suffixes.split():
        _CATEGORY_SUFFIXES[suffix] = category


def is_valid_sort_field(field: str) -> bool:
    return field in _SORT_FIELDS


def natural_key(name: str) -> tuple:
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.lower())
        for token in re.split(r"(\d+)", name)
        if token
    )


def category_of(entry: FileEntry) -> str:
    if entry.is_shortcut:
        return "shortcut"
    if entry.is_dir:
        return "folder"
    suffix = PurePath(entry.name).suffix.lstrip(".").lower()
    return _CATEGORY_SUFFIXES.get(suffix, "other")


def sort_entries_with_keys(
    entries: list[FileEntry], field: str, descending: bool
) -> list[tuple[tuple, FileEntry]]:
    """返回 (排序键, 条目) 对，调用方可复用排序键，避免重复计算 natural_key。"""
    keyed = [(sort_key(entry, field), entry) for entry in entries]
    keyed.sort(key=lambda pair: pair[0], reverse=descending)
    keyed.sort(key=lambda pair: not pair[1].is_dir)  # 稳定排序，文件夹在前
    return keyed


def sort_key(entry: FileEntry, field: str) -> tuple:
    name_key = natural_key(entry.name)
    if field == "size":
        return (entry.size, name_key)
    if field == "type":
        return (entry.type_name.lower(), name_key)
    if field == "modified":
        return (entry.modified or datetime.min, name_key)
    return (name_key,)


def filter_entries(entries: list[FileEntry], needle: str) -> list[FileEntry]:
    """按名称子串过滤（needle 已小写化）。"""
    return [entry for entry in entries if not needle or needle in entry.name.lower()]


def format_size(size: int) -> str:
    value = float(size)
    for unit in _SIZE_UNITS:
        if value < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
