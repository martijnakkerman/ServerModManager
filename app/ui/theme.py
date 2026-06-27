"""A modern dark theme applied app-wide via a single stylesheet."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

# Palette constants reused by delegates.
BG = "#0f1115"
SURFACE = "#171a21"
SURFACE_2 = "#1e222b"
BORDER = "#2a2f3a"
TEXT = "#e6e8ec"
TEXT_DIM = "#9aa0ac"
ACCENT = "#5b8cff"
ACCENT_HOVER = "#6f9bff"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QDialog {{ background: {BG}; }}

QWidget#Toolbar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}

QLabel#PathLabel {{ color: {TEXT_DIM}; }}
QLabel#Heading {{ font-size: 15px; font-weight: 600; }}

QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 13px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: {SURFACE_2}; color: {TEXT_DIM}; }}

QComboBox, QLineEdit, QSpinBox {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {ACCENT};
}}
QComboBox:hover, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    outline: none;
}}

QTableView {{
    background: {SURFACE};
    alternate-background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: rgba(91,140,255,0.22);
    selection-color: {TEXT};
    outline: none;
}}
QTableView::item {{ padding: 6px 8px; border: none; }}
QHeaderView::section {{
    background: {SURFACE};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px;
    font-weight: 600;
}}
QTableView QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QTextBrowser, QTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px;
}}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QProgressBar {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    height: 14px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QStatusBar {{ background: {SURFACE}; color: {TEXT_DIM}; border-top: 1px solid {BORDER}; }}
QCheckBox {{ spacing: 8px; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_2))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(SURFACE_2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
