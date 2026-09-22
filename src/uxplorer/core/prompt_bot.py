"""把选中条目的路径与元数据拼装成可直接提交给大模型的提示词。

本应用不读取任何文件内容，也不调用外部模型：只做轻量的本地拼装，
用户拿到提示词后自行贴给自己信任的大模型或网页 Chat。
提示词会离开本机，因此其中所有路径与名称里的真实用户名
一律替换为 <用户名> 占位符。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .file_logic import FileEntry, format_size
from .risk_analysis import RiskReport, path_access_summary

__all__ = ["build_prompt"]

_PLACEHOLDER = "<用户名>"

# 真实用户名：模块加载时确定一次。取不到时跳过脱敏（如非 Windows 环境）。
_USER_NAME = os.environ.get("USERNAME") or Path.home().name
_USER_NAME_RE = re.compile(re.escape(_USER_NAME), re.IGNORECASE) if _USER_NAME else None


def build_prompt(
    entries: list[FileEntry],
    current_dir: Path,
    risk_report,
) -> str:
    """生成提示词。

    entries 是选中的条目；
    risk_report 是 Path -> RiskReport | None 的查询函数（见 FileListModel）。
    """
    if not entries:
        return ""
    lines = [
        f"我正在整理 Windows 用户目录（当前目录：{_sanitize_path(current_dir)}），"
        f"下面是选中的 {len(entries)} 个条目的元数据。",
        "请逐个分析：它们分别是什么用途、属于哪个程序或系统功能、"
        "手动删除或修改各有什么风险与后果。",
        "",
        "## 待分析条目",
    ]
    for index, entry in enumerate(entries, start=1):
        lines.append("")
        lines.extend(_entry_section(index, entry, risk_report(entry.path)))
    lines += [
        "",
        "以上信息均来自本地文件系统的元数据，未读取任何文件内容。",
    ]
    return "\n".join(lines)


def _entry_section(
    index: int, entry: FileEntry, report: RiskReport | None
) -> list[str]:
    """单个条目的小节：标题 + 元数据 + 本地风险分析结论。"""
    hidden = "（隐藏项目）" if entry.is_hidden else ""
    meta = [
        f"### {index}. {_sanitize_name(entry.name)}{hidden}",
        f"- 路径：{_sanitize_path(entry.path)}",
        f"- 类型：{entry.type_name}",
        # 文件夹不统计总大小，避免触发目录扫描
        f"- 大小：{'—' if entry.is_dir else format_size(entry.size)}",
    ]
    if entry.is_dir:
        # 文件夹的修改时间参考价值低；所有者与访问控制更能区分系统目录与用户数据
        access = path_access_summary(entry.path)
        if access:
            meta.append(f"- 访问控制：{_sanitize_text(access)}")
    elif entry.modified is not None:
        meta.append(f"- 修改时间：{entry.modified:%Y-%m-%d %H:%M}")
    meta.append(f"- 本地风险分析：{_risk_summary(report)}")
    return meta


def _risk_summary(report: RiskReport | None) -> str:
    """压缩 RiskReport 为一行结论；规则理由与建议中的用户名同样脱敏。"""
    if report is None:
        return "未分析"
    parts = [
        f"综合 {report.level.label}"
        f"（删除 {report.delete_level.label} / 修改 {report.modify_level.label}）"
    ]
    if report.reason:
        parts.append(_sanitize_text(report.reason))
    if report.advice:
        parts.append(f"建议：{_sanitize_text(report.advice)}")
    return "；".join(parts)


def _sanitize_path(path: Path) -> str:
    """逐段替换路径中等于用户名的段：C:\\Users\\<真名>\\... → C:\\Users\\<用户名>\\...

    Public / Default 等系统目录名不属于个人隐私，原样保留。
    """
    if _USER_NAME_RE is None:
        return str(path)
    parts = [
        _PLACEHOLDER if _USER_NAME_RE.fullmatch(part) else part for part in path.parts
    ]
    # parts[0] 是带反斜杠结尾的盘符（如 'C:\\'），拼回时先去掉结尾分隔符
    return "\\".join(part.rstrip("\\") for part in parts)


def _sanitize_name(name: str) -> str:
    """条目名等于用户名时替换为占位符（如浏览 C:\\Users 根目录时的个人目录名）。"""
    if _USER_NAME_RE is not None and _USER_NAME_RE.fullmatch(name):
        return _PLACEHOLDER
    return name


def _sanitize_text(text: str) -> str:
    """规则理由 / 建议等自由文本中的用户名子串替换（大小写不敏感）。"""
    if _USER_NAME_RE is None:
        return text
    return _USER_NAME_RE.sub(_PLACEHOLDER, text)
