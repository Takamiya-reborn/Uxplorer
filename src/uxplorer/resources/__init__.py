"""静态资源统一入口。

所有随包分发的静态资源（规则库 rules.db、主题样式表 qss/ 等）都集中
在本目录下，通过本模块访问；新增资源也应放在这里。基于 __file__ 定位
而非 importlib.resources，以便兼容 Nuitka 打包（standalone / onefile
下 __file__ 均指向真实路径）。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["resource_path", "read_text"]

_RESOURCES_DIR = Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """返回包内静态资源的绝对路径，如 resource_path("qss", "dark.qss")。"""
    return _RESOURCES_DIR.joinpath(*parts)


def read_text(name: str) -> str:
    """以 UTF-8 读取包内文本资源，如 read_text("qss/dark.qss")。"""
    return resource_path(*name.split("/")).read_text(encoding="utf-8")
