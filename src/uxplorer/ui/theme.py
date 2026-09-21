from __future__ import annotations

from importlib.resources import files

import lucide
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from ..core.risk_analysis import RiskLevel

_QSS_DIR = files("uxplorer.ui").joinpath("qss")

# 颜色
ACCENT = QColor("#0067c0")
CARD_HOVER_BG = QColor("#f5f9fd")
CARD_SELECTED_BG = QColor("#cfe8ff")
# 风险等级行背景色（浅色主题默认值，深色主题在 apply_theme 中替换）
RISK_HIGH_BG = QColor("#fdecec")  # 高危：浅红
RISK_CAUTION_BG = QColor("#fdf3d5")  # 存疑：浅黄
RISK_SAFE_BG = QColor("#e6f4e8")  # 安全：浅绿
HEADER_HOVER_BG = QColor("#ececec")
HEADER_PRESS_BG = QColor("#e2e2e2")
TEXT_PRIMARY = QColor("#1f1f1f")
TEXT_SECONDARY = QColor("#5f6368")
TEXT_DIR = QColor("#1f1f1f")
DOT_COLOR_FALLBACK = QColor("#8a909e")

ROW_HEIGHT = 36
CARD_HEIGHT = ROW_HEIGHT
CARD_RADIUS = 6
DOT_DIAMETER = 8
TEXT_LEFT = 44
PADDING = 16

# 四列比例：名称 / 修改时间 / 类型 / 大小，与 Windows 资源管理器一致
_COLUMN_RATIOS = (5, 3, 2, 2)


def column_widths(total: int) -> tuple[int, ...]:
    """按总宽度返回各列宽度（名称 / 修改时间 / 类型 / 大小）。

    表头与行绘制必须共用这一份几何计算，否则列边界会出现像素级偏差。
    """
    content = max(total - TEXT_LEFT - PADDING, 0)
    ratio_sum = sum(_COLUMN_RATIOS)
    widths = [int(content * r / ratio_sum) for r in _COLUMN_RATIOS[:-1]]
    widths.append(content - sum(widths))  # 末列兜底，吃掉取整误差
    return tuple(widths)

# 类型颜色
TYPE_COLORS: dict[str, QColor] = {
    "folder": QColor("#dcb67a"),
    "image": QColor("#a074c4"),
    "video": QColor("#cb4b4b"),
    "audio": QColor("#4b9ecb"),
    "archive": QColor("#e08a3c"),
    "code": QColor("#519aba"),
    "doc": QColor("#6a9e5f"),
    "exec": QColor("#c94f6d"),
    "other": QColor("#8a909e"),
}


def type_color(category: str) -> QColor:
    return TYPE_COLORS.get(category, DOT_COLOR_FALLBACK)


def risk_background(level: RiskLevel | None) -> QColor | None:
    """风险等级对应的行背景色；无等级（分析失败）时返回 None。"""
    return {
        RiskLevel.HIGH: RISK_HIGH_BG,
        RiskLevel.QUESTIONABLE: RISK_CAUTION_BG,
        RiskLevel.SAFE: RISK_SAFE_BG,
    }.get(level)


# 边框相对背景的加深系数（百分比，越小越深）
_RISK_BORDER_FACTOR = 115


def risk_border(level: RiskLevel | None) -> QColor | None:
    """风险等级对应的边框色：背景色加深一点，用于区分相邻条目。"""
    bg = risk_background(level)
    return bg.darker(_RISK_BORDER_FACTOR) if bg is not None else None


def lucide_icon(name: str, color: str = "#5f6368", size: int = 18) -> QIcon:
    svg = lucide._render_icon(name, size=size, stroke=color)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    return QIcon(pixmap)


def apply_theme(app: QApplication, theme_name: str = "light") -> None:
    global ACCENT, CARD_HOVER_BG, CARD_SELECTED_BG, HEADER_HOVER_BG, HEADER_PRESS_BG, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIR
    global RISK_HIGH_BG, RISK_CAUTION_BG, RISK_SAFE_BG

    app.setStyle("Fusion")
    color_scheme = Qt.ColorScheme.Dark if theme_name == "dark" else Qt.ColorScheme.Light
    app.styleHints().setColorScheme(color_scheme)
    if theme_name == "dark":
        ACCENT = QColor("#3794ff")
        CARD_HOVER_BG = QColor("#2b2b2b")
        CARD_SELECTED_BG = QColor("#264f78")
        HEADER_HOVER_BG = QColor("#353535")
        HEADER_PRESS_BG = QColor("#404040")
        TEXT_PRIMARY = QColor("#f2f2f2")
        TEXT_SECONDARY = QColor("#bdbdbd")
        TEXT_DIR = QColor("#ffffff")
        # 深色主题下降低明度但保留色相，保证等级仍可辨识
        RISK_HIGH_BG = QColor("#4a2e2e")
        RISK_CAUTION_BG = QColor("#4a4429")
        RISK_SAFE_BG = QColor("#2c4634")
    else:
        ACCENT = QColor("#0067c0")
        CARD_HOVER_BG = QColor("#f5f9fd")
        CARD_SELECTED_BG = QColor("#cfe8ff")
        HEADER_HOVER_BG = QColor("#ececec")
        HEADER_PRESS_BG = QColor("#e2e2e2")
        TEXT_PRIMARY = QColor("#1f1f1f")
        TEXT_SECONDARY = QColor("#5f6368")
        TEXT_DIR = QColor("#1f1f1f")
        RISK_HIGH_BG = QColor("#fdecec")
        RISK_CAUTION_BG = QColor("#fdf3d5")
        RISK_SAFE_BG = QColor("#e6f4e8")
    qss_name = "dark.qss" if theme_name == "dark" else "light.qss"
    app.setStyleSheet(_QSS_DIR.joinpath(qss_name).read_text(encoding="utf-8"))


def apply_dark_theme(app: QApplication) -> None:
    """兼容旧入口。"""
    apply_theme(app, "dark")
