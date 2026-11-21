"""Qt stylesheet and painted icons generated from the shared theme definitions."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication

from sshm.core.themes import Theme


def mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    r = round(ca.red() + (cb.red() - ca.red()) * t)
    g = round(ca.green() + (cb.green() - ca.green()) * t)
    bl = round(ca.blue() + (cb.blue() - ca.blue()) * t)
    return QColor(r, g, bl).name()


def on_color(hex_color: str) -> str:
    """Readable text colour (near-black or white) for a background."""
    c = QColor(hex_color)
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return "#0b0d12" if lum > 0.55 else "#ffffff"


def apply_palette(app: QApplication, t: Theme) -> None:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.surface,
        QPalette.ColorRole.AlternateBase: t.surface2,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.surface2,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: on_color(t.accent),
        QPalette.ColorRole.ToolTipBase: t.surface2,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.muted,
        QPalette.ColorRole.Link: t.accent,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.muted))
    app.setPalette(pal)


def stylesheet(t: Theme) -> str:
    hover = mix(t.surface2, t.accent, 0.12)
    accent_hover = mix(t.accent, "#ffffff", 0.12)
    accent_soft = mix(t.surface, t.accent, 0.18)
    danger_soft = mix(t.surface, t.danger, 0.18)
    on_accent = on_color(t.accent)
    return f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {t.bg}; }}
QWidget {{ color: {t.text}; font-size: 10pt; }}
QToolTip {{ background: {t.surface2}; color: {t.text}; border: 1px solid {t.border}; padding: 6px 8px;
           border-radius: 6px; }}

QFrame#Sidebar {{ background: {t.surface}; border-right: 1px solid {t.border}; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 700; color: {t.text}; }}
QLabel#BrandMark {{ color: {t.accent}; font-size: 15pt; font-weight: 800; }}
QLabel#Muted, QLabel#Caption {{ color: {t.muted}; }}
QLabel#Caption {{ font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#Title {{ font-size: 20pt; font-weight: 700; }}
QLabel#Endpoint {{ color: {t.muted}; font-family: monospace; font-size: 10pt; }}
QLabel#Value {{ font-weight: 600; }}
QLabel#Mono {{ font-family: monospace; }}
QLabel#BigNumber {{ font-size: 18pt; font-weight: 700; }}
QLabel#Pill {{ border-radius: 10px; padding: 2px 10px; font-weight: 700; font-size: 9pt; }}
QLabel#Chip {{ background: {accent_soft}; color: {t.accent}; border-radius: 9px; padding: 1px 8px;
              font-size: 9pt; font-weight: 600; }}
QLabel#Empty {{ color: {t.muted}; font-size: 11pt; }}
QLabel#EmptyTitle {{ font-size: 18pt; font-weight: 700; }}

QFrame#Card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
QFrame#Banner {{ background: {accent_soft}; border: 1px solid {mix(t.border, t.accent, 0.4)}; border-radius: 12px; }}
QFrame#Hairline {{ background: {t.border}; max-height: 1px; min-height: 1px; border: none; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {t.bg}; border: 1px solid {t.border}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {t.accent}; selection-color: {on_accent};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {t.accent};
}}
QLineEdit#Search {{ padding: 8px 12px; border-radius: 10px; background: {t.bg}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t.surface2}; border: 1px solid {t.border};
    selection-background-color: {hover}; selection-color: {t.text}; padding: 4px; }}

QPushButton, QToolButton {{
    background: {t.surface2}; border: 1px solid {t.border}; border-radius: 8px; padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover, QToolButton:hover {{ background: {hover}; border-color: {mix(t.border, t.accent, 0.5)}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.bg}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.muted}; background: {t.surface}; }}
QPushButton#Primary, QToolButton#Primary {{ background: {t.accent}; color: {on_accent}; border: 1px solid {t.accent}; }}
QPushButton#Primary:hover, QToolButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Danger {{ color: {t.danger}; }}
QPushButton#Danger:hover {{ background: {danger_soft}; border-color: {t.danger}; }}
QPushButton#Flat, QToolButton#Flat {{ background: transparent; border: 1px solid transparent; }}
QPushButton#Flat:hover, QToolButton#Flat:hover {{ background: {hover}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[popupMode="1"] {{ padding-right: 24px; }}
QToolButton::menu-button {{ border-left: 1px solid {mix(t.accent, '#000000', 0.25)}; width: 20px; }}

QListView#ServerList {{ background: transparent; border: none; }}
QListWidget, QTableWidget {{ background: {t.bg}; border: 1px solid {t.border}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: {hover}; color: {t.text}; }}
QListWidget::item:hover {{ background: {mix(t.bg, t.accent, 0.06)}; }}
QHeaderView::section {{ background: {t.surface}; color: {t.muted}; border: none; padding: 6px;
                        font-weight: 700; font-size: 9pt; }}

QTabWidget::pane {{ border: 1px solid {t.border}; border-radius: 12px; top: -1px; background: {t.surface}; }}
QTabBar::tab {{ background: transparent; color: {t.muted}; padding: 8px 16px; font-weight: 600;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
QTabBar::tab:hover {{ color: {t.text}; }}

QMenu {{ background: {t.surface2}; border: 1px solid {t.border}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {hover}; }}
QMenu::item:disabled {{ color: {t.muted}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {t.border};
                        background: {t.bg}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}

QProgressBar {{ background: {t.bg}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; color: {t.muted}; }}
QStatusBar QLabel {{ color: {t.muted}; padding: 0 8px; }}
QSplitter::handle {{ background: {t.border}; }}
"""


# ------------------------------------------------------------------- icons
def dot_icon(color: str, hollow: bool = False, size: int = 16) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    if hollow:
        p.setPen(QPen(c, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(3, 3, size - 6, size - 6))
    else:
        glow = QColor(c)
        glow.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
        p.setBrush(QBrush(c))
        p.drawEllipse(QRectF(4, 4, size - 8, size - 8))
    p.end()
    return QIcon(pix)


def app_icon(state: str = "none", accent: str = "#b48ead") -> QIcon:
    """Painted app/tray icon: a terminal tile with a status badge.

    state: 'ok' (all up), 'partial', 'down', or 'none'.
    """
    icon = QIcon()
    badge = {"ok": "#4ade80", "partial": "#fbbf24", "down": "#f87171"}.get(state)
    for size in (16, 22, 24, 32, 48, 64, 128):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 128.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(8 * s, 8 * s, 112 * s, 112 * s), 26 * s, 26 * s)
        p.fillPath(path, QColor("#1b1b29"))
        p.setPen(QPen(QColor(accent), max(1.5, 6 * s)))
        p.drawPath(path)
        pen = QPen(QColor("#e2e4f3"), max(1.5, 9 * s))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(x * s, y * s) for x, y in ((34, 44), (56, 64), (34, 84))]))
        p.drawLine(int(64 * s), int(86 * s), int(92 * s), int(86 * s))
        if badge:
            r = 22 * s if size >= 32 else 30 * s
            p.setPen(QPen(QColor("#1b1b29"), max(1.0, 6 * s)))
            p.setBrush(QColor(badge))
            p.drawEllipse(QRectF(128 * s - 2 * r - 4 * s, 128 * s - 2 * r - 4 * s, 2 * r, 2 * r))
        p.end()
        icon.addPixmap(pix)
    return icon


def themed_icon(*names: str) -> QIcon:
    for name in names:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    return QIcon()
