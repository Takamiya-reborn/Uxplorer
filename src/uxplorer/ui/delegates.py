from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core.file_logic import format_size
from . import theme
from .models import Role


class CardDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # standardIcon() / lucide_icon() 每次调用都会生成新图标，
        # paint() 逐行高频触发时开销极大，需缓存
        self._icon_cache: dict[str, QIcon] = {}

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, theme.ROW_HEIGHT)

    def _icon(self, entry) -> QIcon:
        # 快捷方式按普通文件对待，仅用带链接角的图标区分
        kind = "shortcut" if entry.is_shortcut else ("dir" if entry.is_dir else "file")
        icon = self._icon_cache.get(kind)
        if icon is None:
            if kind == "shortcut":
                # 中性灰在深浅主题下均可用
                icon = theme.lucide_icon("file-symlink", "#8a909e", 16)
            else:
                icon = QApplication.style().standardIcon(
                    QStyle.StandardPixmap.SP_DirIcon
                    if kind == "dir"
                    else QStyle.StandardPixmap.SP_FileIcon
                )
            self._icon_cache[kind] = icon
        return icon

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        entry_name = index.data(Qt.ItemDataRole.DisplayRole)
        if entry_name is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # 背景优先级：选中 > 悬停 > 风险等级（高危浅红 / 存疑浅黄 / 安全浅绿）
        if selected:
            bg = theme.CARD_SELECTED_BG
        elif hovered:
            bg = theme.CARD_HOVER_BG
        else:
            bg = theme.risk_background(index.data(Role.RiskRole))
        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRect(row)

        # 一圈细边框：风险色加深一点，选中/悬停时也保留，避免相邻条目连成一片
        border = theme.risk_border(index.data(Role.RiskRole))
        if border is not None:
            painter.setPen(QPen(border, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(row.adjusted(0, 0, -1, -1))

        entry = index.data(Role.EntryRole)
        if entry is None:
            painter.restore()
            return

        # 列几何与表头共用 theme.column_widths，保证行内容与表头严格对齐
        name_w, modified_w, type_w, size_w = theme.column_widths(row.width())
        x = row.left() + theme.TEXT_LEFT
        top, height = row.top(), row.height()
        name_rect = QRect(x, top, name_w, height)
        x += name_w
        modified_rect = QRect(x, top, modified_w, height)
        x += modified_w
        type_rect = QRect(x, top, type_w, height)
        x += type_w
        size_rect = QRect(x, top, size_w, height)

        icon = self._icon(entry)
        icon.paint(painter, row.left() + theme.PADDING, row.center().y() - 8, 16, 16)
        painter.setFont(option.font)
        painter.setPen(
            theme.TEXT_DIR if entry.is_dir else theme.TEXT_PRIMARY
        )
        text = QFontMetrics(option.font).elidedText(
            entry_name, Qt.TextElideMode.ElideMiddle, name_rect.width() - 28
        )
        painter.drawText(
            name_rect.left(),
            name_rect.top(),
            name_rect.width(),
            name_rect.height(),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.setPen(theme.TEXT_SECONDARY)
        modified = entry.modified.strftime("%Y/%m/%d %H:%M") if entry.modified else ""
        painter.drawText(modified_rect, Qt.AlignmentFlag.AlignVCenter, modified)
        painter.drawText(type_rect, Qt.AlignmentFlag.AlignVCenter, entry.type_name)
        if not entry.is_dir:
            painter.drawText(size_rect, Qt.AlignmentFlag.AlignVCenter, format_size(entry.size))
        painter.restore()
