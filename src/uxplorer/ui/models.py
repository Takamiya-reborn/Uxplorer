from __future__ import annotations

import enum
import html
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from ..core.file_logic import (
    FileEntry,
    category_of,
    filter_entries,
    is_valid_sort_field,
    sort_entries_with_keys,
)
from ..core.risk_analysis import RiskReport, analyze_risk

FETCH_BATCH = 200


class Role(enum.IntEnum):
    EntryRole = Qt.ItemDataRole.UserRole + 1
    KindRole = Qt.ItemDataRole.UserRole + 2
    SortRole = Qt.ItemDataRole.UserRole + 3
    RiskRole = Qt.ItemDataRole.UserRole + 4


class FileListModel(QAbstractListModel):
    countsChanged = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._shown: list[FileEntry] = []
        self._kinds: list[str] = []
        self._keys: list[tuple] = []
        self._risks: dict[Path, RiskReport] = {}
        self._revealed = 0
        self._sort_field = "name"
        self._sort_desc = False
        self._needle = ""

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._revealed

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= self._revealed:
            return None
        row = index.row()
        entry = self._shown[row]
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(entry)
        if role == Role.EntryRole:
            return entry
        if role == Role.KindRole:
            return self._kinds[row]
        if role == Role.SortRole:
            return self._keys[row]
        if role == Role.RiskRole:
            report = self._risks.get(entry.path)
            return report.level if report else None
        return None

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        return not parent.isValid() and self._revealed < len(self._shown)

    def fetchMore(self, parent=QModelIndex()) -> None:
        if parent.isValid():
            return
        rest = len(self._shown) - self._revealed
        if rest <= 0:
            return
        take = min(FETCH_BATCH, rest)
        self.beginInsertRows(QModelIndex(), self._revealed, self._revealed + take - 1)
        self._revealed += take
        self.endInsertRows()

    def set_entries(self, entries: list[FileEntry]) -> None:
        self._entries = list(entries)
        self._risks = {}
        for entry in self._entries:
            try:
                self._risks[entry.path] = analyze_risk(entry.path)
            except (PermissionError, OSError):
                continue  # 分析失败的项目不着色
        self._reflow()

    def entries(self) -> list[FileEntry]:
        """当前目录的全部条目（未经搜索过滤），供提示词等复用。"""
        return list(self._entries)

    def risk_report(self, path: Path) -> RiskReport | None:
        return self._risks.get(path)

    def set_sort(self, field: str, descending: bool) -> None:
        if not is_valid_sort_field(field):
            return
        self._sort_field, self._sort_desc = field, descending
        self._reflow()

    def set_filter(self, needle: str) -> None:
        self._needle = needle.strip().lower()
        self._reflow()

    def _reflow(self) -> None:
        # 先过滤再排序：搜索时排序的数据量更小；排序键与条目成对传递，只计算一次
        filtered = filter_entries(self._entries, self._needle)
        keyed = sort_entries_with_keys(filtered, self._sort_field, self._sort_desc)

        self.beginResetModel()
        self._shown = [entry for _, entry in keyed]
        self._kinds = [category_of(entry) for entry in self._shown]
        self._keys = [key for key, _ in keyed]
        self._revealed = 0
        self.endResetModel()

        self.fetchMore(QModelIndex())
        self.countsChanged.emit(len(self._entries), len(self._shown))

    def _tooltip(self, entry: FileEntry) -> str:
        # 基本信息（名称/大小/修改时间）已在列表中展示，悬浮时只补充风险详情
        report = self._risks.get(entry.path)
        if report is None:
            return ""
        lines = [f"<b>风险等级：{report.level.label}</b>"]
        if report.is_container:
            lines.append("此目录为系统容器：本身不可删除或重命名，内部子项可独立管理")
        lines.append(
            f"删除风险：{report.delete_level.label}　修改风险：{report.modify_level.label}"
        )
        lines.append(html.escape(report.reason))
        if report.evidence:
            lines.append(html.escape(report.evidence))
        if report.advice:
            lines.append(f"建议：{html.escape(report.advice)}")
        return "<br/>".join(lines)
