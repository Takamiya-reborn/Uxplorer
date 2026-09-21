from __future__ import annotations

import os
import stat as stat_mod
import subprocess
from datetime import datetime
from pathlib import Path

from .file_logic import FileEntry

ROOT = Path("C:/Users").resolve()

# 快捷方式文件后缀（.lnk 普通 / .url Internet）
_SHORTCUT_SUFFIXES = {".lnk", ".url"}


def is_within_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == ROOT or ROOT in resolved.parents


def list_dir(path: Path, *, include_hidden: bool = False) -> list[FileEntry]:
    path = path.resolve()
    if not is_within_root(path):
        raise PermissionError(f"路径超出导航范围: {path}")

    entries: list[FileEntry] = []
    with os.scandir(path) as iterator:
        for directory_entry in iterator:
            try:
                lstat = directory_entry.stat(follow_symlinks=False)
            except OSError:
                continue
            hidden = _is_hidden(directory_entry.name, lstat)
            if hidden and not include_hidden:
                continue
            # 目标不可达的链接也要展示，size / 修改时间退化为链接自身的信息
            try:
                stat_result = directory_entry.stat()
            except OSError:
                stat_result = lstat
            is_shortcut = _is_shortcut(directory_entry, lstat)
            # 快捷方式按普通文件对待：不导航、不参与文件夹分组
            is_dir = not is_shortcut and directory_entry.is_dir()
            entries.append(
                FileEntry(
                    name=directory_entry.name,
                    path=Path(directory_entry.path),
                    is_dir=is_dir,
                    size=-1 if is_dir else stat_result.st_size,
                    modified=datetime.fromtimestamp(stat_result.st_mtime),
                    type_name=_type_name(is_dir, directory_entry.name, is_shortcut),
                    is_hidden=hidden,
                    is_shortcut=is_shortcut,
                )
            )
    return entries


def open_in_explorer(path: Path) -> None:
    """在 Windows 资源管理器中打开条目所在目录，并定位选中该条目。"""
    # /select 必须紧贴逗号后跟引号路径，不能用参数列表（list2cmdline 会在逗号后插空格）
    subprocess.Popen(f'explorer /select,"{path}"')


def show_properties(path: Path) -> None:
    """打开 Windows 的文件属性对话框（模态，关闭前阻塞）。"""
    import ctypes

    if os.name != "nt":
        return
    SHOP_FILEPATH = 0x2  # 按"文件系统路径"解释第二个参数
    ctypes.windll.shell32.SHObjectProperties(
        None, SHOP_FILEPATH, ctypes.c_wchar_p(str(path)), None
    )


def _is_hidden(name: str, lstat: os.stat_result) -> bool:
    if name.startswith("."):
        return True
    if os.name != "nt":
        return False
    return bool(
        getattr(lstat, "st_file_attributes", 0) & stat_mod.FILE_ATTRIBUTE_HIDDEN
    )


def _is_shortcut(directory_entry: os.DirEntry, lstat: os.stat_result) -> bool:
    if Path(directory_entry.name).suffix.lower() in _SHORTCUT_SUFFIXES:
        return True
    if os.name != "nt":
        return directory_entry.is_symlink()
    # 只把真正的链接（符号链接 / junction）算作快捷方式，
    # 排除 OneDrive 云占位等其它 reparse 点
    tag = getattr(lstat, "st_reparse_tag", 0)
    return tag in (stat_mod.IO_REPARSE_TAG_SYMLINK, stat_mod.IO_REPARSE_TAG_MOUNT_POINT)


def _type_name(is_dir: bool, name: str, is_shortcut: bool = False) -> str:
    if is_shortcut:
        if Path(name).suffix.lower() == ".url":
            return "Internet 快捷方式"
        return "快捷方式"
    if is_dir:
        return "文件夹"
    suffix = Path(name).suffix.lstrip(".").upper()
    return f"{suffix} 文件" if suffix else "文件"
