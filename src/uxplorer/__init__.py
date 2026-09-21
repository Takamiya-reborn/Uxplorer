import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Uxplorer")
    apply_theme(app, "dark")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
