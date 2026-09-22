from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import api, prompt_bot
from .delegates import CardDelegate
from .models import FileListModel, Role
from . import theme
from .theme import apply_theme

# 列顺序与 CardDelegate 绘制顺序一致：名称 / 修改时间 / 类型 / 大小
_SORT_FIELDS = ("name", "modified", "type", "size")
_SORT_LABELS = ("名称", "修改时间", "类型", "大小")
_SEARCH_DEBOUNCE_MS = 300


class _FileListView(QListView):
    """带空状态提示的列表。"""

    # 视口实际宽度（扣掉滚动条后），表头据此对齐列边界
    viewportResized = Signal(int)

    # 右键某个条目时发出（模型索引 + 菜单弹出的全局坐标），菜单内容由 MainWindow 组装
    itemContextMenuRequested = Signal(QModelIndex, QPoint)

    def __init__(self) -> None:
        super().__init__()
        self._empty_label = QLabel(self)
        self._empty_label.setObjectName("emptyState")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.hide()
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            self.viewportResized.emit(event.size().width())
        return super().eventFilter(obj, event)

    def set_empty_text(self, text: str | None) -> None:
        if text is None:
            self._empty_label.hide()
        else:
            self._empty_label.setText(text)
            self._empty_label.setGeometry(self.rect())
            self._empty_label.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._empty_label.isVisible():
            self._empty_label.setGeometry(self.rect())

    def contextMenuEvent(self, event) -> None:
        index = self.indexAt(event.pos())
        if index.isValid():
            self.itemContextMenuRequested.emit(index, event.globalPos())
        # 空白处不弹菜单，交回默认处理


class _SortHeaderButton(QAbstractButton):
    """Windows 11 风格的表头按钮。

    自绘悬停 / 按下背景与排序箭头：QToolButton 拼文字箭头在窄窗口下会被裁剪，
    QSS 方形 hover 背景也不贴近系统观感，这里改为圆角、上下留边的绘制方式。
    """

    _HOVER_INSET = 3  # 悬停背景上下内缩，模拟 Windows 的悬浮块
    _RADIUS = 4
    _ARROW_GAP = 6

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._sort_state = 0  # 0 未排序，1 升序，-1 降序
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_sort_state(self, state: int) -> None:
        if state != self._sort_state:
            self._sort_state = state
            self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._label) + 40, 32)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # 背景：悬停 / 按下时绘制圆角色块，平时透明
        if self.isDown():
            bg = theme.HEADER_PRESS_BG
        elif self.underMouse():
            bg = theme.HEADER_HOVER_BG
        else:
            bg = None
        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(
                rect.adjusted(0, self._HOVER_INSET, 0, -self._HOVER_INSET),
                self._RADIUS,
                self._RADIUS,
            )

        # 文字：激活列用主色，其余用次级色。
        # 文字必须从列左缘开始画（无内缩），才能与行内容对齐。
        text_color = theme.TEXT_PRIMARY if self._sort_state else theme.TEXT_SECONDARY
        painter.setPen(text_color)
        text_rect = rect
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._label,
        )

        if self._sort_state == 0:
            return
        # 箭头紧跟文字右侧，与 Windows 资源管理器一致
        fm = QFontMetrics(self.font())
        arrow_left = (
            text_rect.left() + fm.horizontalAdvance(self._label) + self._ARROW_GAP
        )
        cx, cy = arrow_left + 4, rect.center().y()
        painter.setPen(
            QPen(
                text_color,
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        if self._sort_state > 0:  # 升序
            painter.drawLine(cx - 4, cy + 2, cx, cy - 2)
            painter.drawLine(cx, cy - 2, cx + 4, cy + 2)
        else:  # 降序
            painter.drawLine(cx - 4, cy - 2, cx, cy + 2)
            painter.drawLine(cx, cy + 2, cx + 4, cy - 2)


class _FileHeader(QWidget):
    """文件列表表头。

    不用布局，而是按 theme.column_widths 手动定位各列按钮：
    行内容按视口宽度切列，滚动条出现 / 消失时视口宽度会变，
    QGridLayout 的 stretch 分配无法与其保持像素级一致。
    """

    def __init__(
        self, fields: list[tuple[str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fileHeader")
        self._content_width = -1  # 列区域宽度，即列表视口宽度
        self.buttons: dict[str, _SortHeaderButton] = {}
        for field, label in fields:
            self.buttons[field] = _SortHeaderButton(label, self)
        self.setFixedHeight(32)

    def set_content_width(self, width: int) -> None:
        if width != self._content_width:
            self._content_width = width
            self._relayout()

    def _relayout(self) -> None:
        if self._content_width < 0:
            return
        x = theme.TEXT_LEFT
        for button, width in zip(
            self.buttons.values(), theme.column_widths(self._content_width)
        ):
            button.setGeometry(x, 0, width, self.height())
            x += width

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Uxplorer")
        self.resize(1020, 660)
        self.setMinimumSize(640, 420)

        self._history: list[Path] = []
        self._hist_pos = -1
        self._current = api.ROOT
        self._show_hidden = False

        self._build_ui()
        self.navigate(api.ROOT)

    def _build_ui(self) -> None:
        # 工具栏
        toolbar = self.addToolBar("导航")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self._btn_back = self._nav_button("←", "后退 (Alt+←)", self.go_back)
        self._btn_fwd = self._nav_button("→", "前进 (Alt+→)", self.go_forward)
        self._btn_up = self._nav_button("↑", "上一级 (Alt+↑)", self.go_up)
        toolbar.addWidget(self._btn_back)
        toolbar.addWidget(self._btn_fwd)
        toolbar.addWidget(self._btn_up)
        toolbar.addSeparator()

        self._btn_hidden = QToolButton()
        self._btn_hidden.setText("显示隐藏项目")
        self._btn_hidden.setToolTip("显示 / 隐藏 隐藏项")
        self._btn_hidden.setCheckable(True)
        self._btn_hidden.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_hidden.toggled.connect(self._on_hidden_toggled)
        toolbar.addWidget(self._btn_hidden)

        toolbar.addSeparator()
        self._theme_is_dark = True
        self._theme_button = QToolButton()
        self._theme_button.setObjectName("themeButton")
        self._theme_button.setIcon(theme.lucide_icon("sun", "#f2f2f2"))
        self._theme_button.setToolTip("切换浅色主题")
        self._theme_button.setAutoRaise(True)
        self._theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_button.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self._theme_button)

        # 路径栏
        path_row = QWidget()
        path_row.setObjectName("pathRow")
        row_layout = QHBoxLayout(path_row)
        row_layout.setContentsMargins(12, 6, 12, 6)
        row_layout.setSpacing(2)
        self._crumb_layout = QHBoxLayout()
        self._crumb_layout.setSpacing(2)
        row_layout.addLayout(self._crumb_layout)
        row_layout.addStretch(1)

        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setPlaceholderText("搜索当前目录")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(240)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(
            lambda: self._model.set_filter(self._search.text())
        )
        self._search.textChanged.connect(self._search_timer.start)
        row_layout.addWidget(self._search)

        # 文件列表
        self._model = FileListModel(self)
        self._model.countsChanged.connect(self._on_counts_changed)

        self._view = _FileListView()
        self._view.setObjectName("fileList")
        self._view.setViewMode(QListView.ViewMode.ListMode)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setMovement(QListView.Movement.Static)
        self._view.setUniformItemSizes(True)
        self._view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSpacing(0)
        self._view.setMouseTracking(True)
        self._view.setItemDelegate(CardDelegate(self._view))
        self._view.setModel(self._model)
        self._view.activated.connect(self._on_activated)
        self._view.itemContextMenuRequested.connect(self._on_item_context_menu)

        self._header = _FileHeader(list(zip(_SORT_FIELDS, _SORT_LABELS)))
        self._sort_field = "name"
        self._sort_desc = False
        for field, label in zip(_SORT_FIELDS, _SORT_LABELS):
            title = self._header.buttons[field]
            title.setToolTip(f"按{label}排序")
            # 注意：clicked 会传出 checked(bool)，必须用仅关键字参数接住，
            # 否则字段名会被覆盖成 False，导致排序失效、指示箭头消失
            title.clicked.connect(
                lambda _checked=False, f=field: self._on_header_sort_clicked(f)
            )
        self._update_header_sort_indicators()
        # 视口宽度变化（窗口缩放 / 滚动条出现消失）时，表头按同一份几何重新对位
        self._view.viewportResized.connect(self._header.set_content_width)
        self._header.set_content_width(self._view.viewport().width())

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(path_row)
        central_layout.addWidget(self._header)
        central_layout.addWidget(self._view)
        self.setCentralWidget(central)

        self._path_label = QLabel()
        self.statusBar().addPermanentWidget(self._path_label)

        for seq, slot in (
            ("Alt+Left", self.go_back),
            ("Alt+Right", self.go_forward),
            ("Alt+Up", self.go_up),
        ):
            QShortcut(QKeySequence(seq), self, activated=slot)

    def _nav_button(self, text: str, tooltip: str, slot) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _on_header_sort_clicked(self, field: str) -> None:
        if field == self._sort_field:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_field = field
            self._sort_desc = False
        self._model.set_sort(self._sort_field, self._sort_desc)
        self._update_header_sort_indicators()

    def _update_header_sort_indicators(self) -> None:
        for field, button in self._header.buttons.items():
            if field == self._sort_field:
                button.set_sort_state(-1 if self._sort_desc else 1)
            else:
                button.set_sort_state(0)

    def _toggle_theme(self) -> None:
        self._theme_is_dark = not self._theme_is_dark
        theme_name = "dark" if self._theme_is_dark else "light"
        apply_theme(QApplication.instance(), theme_name)
        icon_name = "sun" if self._theme_is_dark else "moon"
        icon_color = "#f2f2f2" if self._theme_is_dark else "#5f6368"
        self._theme_button.setIcon(theme.lucide_icon(icon_name, icon_color))
        self._theme_button.setToolTip(
            "切换浅色主题" if self._theme_is_dark else "切换深色主题"
        )

    def navigate(self, path: Path) -> None:
        # 导航
        if not api.is_within_root(path):
            self.statusBar().showMessage("已锁定：只能在 C:\\Users 内导航")
            return
        try:
            entries = api.list_dir(path, include_hidden=self._show_hidden)
        except OSError as exc:
            self.statusBar().showMessage(f"无法打开文件夹：{exc.strerror or exc}")
            return

        self._current = path.resolve()
        if self._hist_pos < 0 or self._history[self._hist_pos] != self._current:
            del self._history[self._hist_pos + 1 :]
            self._history.append(self._current)
            self._hist_pos += 1

        self._populate(entries)
        self._update_chrome()

    def go_back(self) -> None:
        if self._hist_pos > 0:
            self._hist_pos -= 1
            self.navigate(self._history[self._hist_pos])

    def go_forward(self) -> None:
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self.navigate(self._history[self._hist_pos])

    def go_up(self) -> None:
        parent = self._current.parent
        if self._current != api.ROOT and api.is_within_root(parent):
            self.navigate(parent)

    def _populate(self, entries: list[api.FileEntry]) -> None:
        self._model.set_entries(entries)

    def _on_activated(self, index) -> None:
        entry = index.data(Role.EntryRole)
        if entry is not None and entry.is_dir:
            self.navigate(entry.path)

    def _on_item_context_menu(self, index: QModelIndex, global_pos: QPoint) -> None:
        # Windows 惯例：右键点在未选中的条目上时，先把选择切换到该条目
        if not self._view.selectionModel().isSelected(index):
            self._view.setCurrentIndex(index)
        entry = index.data(Role.EntryRole)
        if entry is None:
            return
        menu = QMenu(self._view)
        # Windows 上 QSS 的 border-radius 需要透明背景才能真正裁出圆角
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        icon_color = theme.TEXT_SECONDARY.name()
        menu.addAction(
            theme.lucide_icon("folder-open", icon_color, 16),
            "在资源管理器中打开",
            lambda: api.open_in_explorer(entry.path),
        )
        menu.addAction(
            theme.lucide_icon("info", icon_color, 16),
            "属性",
            lambda: api.show_properties(entry.path),
        )
        menu.addSeparator()
        menu.addAction(
            theme.lucide_icon("copy", icon_color, 16),
            "生成提示词并复制",
            self._copy_prompt_for_selection,
        )
        menu.exec(global_pos)

    def _copy_prompt_for_selection(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        prompt = prompt_bot.build_prompt(
            entries,
            self._current,
            self._model.risk_report,
        )
        QApplication.clipboard().setText(prompt)
        self.statusBar().showMessage(f"提示词已复制（{len(entries)} 个条目）")

    def _selected_entries(self) -> list[api.FileEntry]:
        """按行号排序去重的选中条目；单选与多选统一走这里。"""
        rows = sorted({index.row() for index in self._view.selectedIndexes()})
        entries = []
        for row in rows:
            entry = self._model.index(row, 0).data(Role.EntryRole)
            if entry is not None:
                entries.append(entry)
        return entries

    def _on_counts_changed(self, total: int, shown: int) -> None:
        if total == 0:
            self._view.set_empty_text("此文件夹为空")
        elif shown == 0:
            self._view.set_empty_text("无匹配项")
        else:
            self._view.set_empty_text(None)
        text = f"{shown} / {total} 个项目" if shown != total else f"{total} 个项目"
        self.statusBar().showMessage(text)

    def _on_hidden_toggled(self, checked: bool) -> None:
        self._show_hidden = checked
        self.navigate(self._current)

    def _update_chrome(self) -> None:
        self._btn_back.setEnabled(self._hist_pos > 0)
        self._btn_fwd.setEnabled(self._hist_pos < len(self._history) - 1)
        self._btn_up.setEnabled(
            self._current != api.ROOT and api.is_within_root(self._current.parent)
        )
        self.setWindowTitle(f"Uxplorer — {self._current}")
        self._path_label.setText(str(self._current))
        self._rebuild_crumbs()

    def _rebuild_crumbs(self) -> None:
        while self._crumb_layout.count():
            child = self._crumb_layout.takeAt(0).widget()
            if child is not None:
                child.deleteLater()

        parts = self._current.parts
        for i, part in enumerate(parts):
            path = Path(*parts[: i + 1])
            label = "C:" if i == 0 else part
            if i > 0:
                sep = QLabel("›")
                sep.setObjectName("crumbSep")
                self._crumb_layout.addWidget(sep)
            if path == self._current:
                current = QLabel(label)
                current.setObjectName("crumbCurrent")
                self._crumb_layout.addWidget(current)
            else:
                btn = QPushButton(label)
                btn.setObjectName("crumbButton")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setEnabled(api.is_within_root(path))
                btn.clicked.connect(lambda _=False, p=path: self.navigate(p))
                self._crumb_layout.addWidget(btn)
        self._crumb_layout.addStretch(1)
