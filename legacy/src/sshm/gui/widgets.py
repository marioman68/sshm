"""Custom-painted widgets: server list delegate, sparkline, metric cards, pills."""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from sshm.core.status import HostStatus
from sshm.core.themes import Theme
from sshm.gui.style import mix

ROLE_SERVER = Qt.ItemDataRole.UserRole.value + 1
ROLE_STATUS = Qt.ItemDataRole.UserRole.value + 2
ROLE_ID = Qt.ItemDataRole.UserRole.value + 3
ROLE_LINK = Qt.ItemDataRole.UserRole.value + 4   # "container on <host>" label, or None
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def state_color(theme: Theme, st: HostStatus | None) -> str:
    if st is None:
        return theme.muted
    if st.online:
        return theme.success
    return theme.warning if st.state == "degraded" else theme.danger


class ServerDelegate(QStyledItemDelegate):
    """Two-line card rows: status dot, name, tag chip, endpoint, latency / CPU."""

    ROW_H = 58

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = self.theme
        srv = index.data(ROLE_SERVER)
        st: HostStatus | None = index.data(ROLE_STATUS)
        if srv is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            p.fillPath(path, QColor(mix(t.surface, t.accent, 0.16 if selected else 0.07)))
            if selected:
                p.fillRect(QRectF(r.left(), r.top() + 12, 3, r.height() - 24), QColor(t.accent))

        # status dot
        color = QColor(state_color(t, st))
        cx, cy = r.left() + 20, r.center().y()
        glow = QColor(color)
        glow.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        if st is not None and st.online:
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), 8, 8)
        p.setBrush(color if st is None or st.online else Qt.BrushStyle.NoBrush)
        if st is not None and not st.online:
            p.setPen(QPen(color, 2))
        p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        p.setPen(Qt.PenStyle.NoPen)

        left = int(r.left() + 38)
        right = int(r.right() - 12)

        # right column: latency + cpu
        small = QFont(option.font)
        small.setPointSizeF(max(7.5, option.font.pointSizeF() - 1))
        p.setFont(small)
        fm_small = QFontMetrics(small)
        lat = st.latency_label if st else "…"
        p.setPen(QColor(t.text if st and st.online else t.muted))
        lat_w = fm_small.horizontalAdvance(lat)
        p.drawText(QRect(right - lat_w, int(r.top() + 9), lat_w, fm_small.height()), LEFT, lat)
        tel = st.telemetry if st else None
        if tel and tel.cpu is not None:
            bar_w, bar_h = 46, 4
            bx, by = right - bar_w, int(r.bottom() - 15)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.border))
            p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 2, 2)
            pct = max(0.0, min(100.0, tel.cpu))
            fill = t.success if pct < 70 else t.warning if pct < 90 else t.danger
            p.setBrush(QColor(fill))
            p.drawRoundedRect(QRectF(bx, by, bar_w * pct / 100, bar_h), 2, 2)
            label = f"{pct:.0f}%"
            p.setPen(QColor(t.muted))
            lw = fm_small.horizontalAdvance(label)
            p.drawText(QRect(bx - lw - 6, by - 5, lw, fm_small.height()), LEFT, label)
            right_used = bar_w + lw + 10
        else:
            right_used = 0
        right_used = max(right_used, lat_w) + 10

        # name + star + tag chip
        bold = QFont(option.font)
        bold.setWeight(QFont.Weight.DemiBold)
        p.setFont(bold)
        fm = QFontMetrics(bold)
        name_room = right - right_used - left
        tag_w = 0
        if srv.tag:
            tag_w = min(fm_small.horizontalAdvance(srv.tag) + 14, max(0, name_room // 3))
        star = "★ " if srv.favorite else ""
        name = fm.elidedText(star + srv.name, Qt.TextElideMode.ElideRight, max(20, name_room - tag_w - 8))
        p.setPen(QColor(t.text))
        p.drawText(QRect(left, int(r.top() + 7), name_room, fm.height()), LEFT, name)
        if star:
            p.setPen(QColor(t.warning))
            p.drawText(QRect(left, int(r.top() + 7), fm.horizontalAdvance("★"), fm.height()), LEFT, "★")
        if tag_w > 20:
            nx = left + fm.horizontalAdvance(name) + 8
            chip = QRectF(nx, r.top() + 9, tag_w, fm_small.height() + 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(mix(t.surface, t.info, 0.22)))
            p.drawRoundedRect(chip, chip.height() / 2, chip.height() / 2)
            p.setFont(small)
            p.setPen(QColor(t.info))
            p.drawText(chip.toRect(), Qt.AlignmentFlag.AlignCenter,
                       fm_small.elidedText(srv.tag, Qt.TextElideMode.ElideRight, tag_w - 10))

        # endpoint line (or "⬢ container on <host>")
        p.setFont(small)
        p.setPen(QColor(t.muted))
        link = index.data(ROLE_LINK)
        line = f"⬢ {link}" if link else srv.endpoint
        if link:
            p.setPen(QColor(t.info))
        ep = fm_small.elidedText(line, Qt.TextElideMode.ElideMiddle, right - right_used - left)
        p.drawText(QRect(left, int(r.bottom() - 7 - fm_small.height()), right - left, fm_small.height()), LEFT, ep)
        p.restore()


class Sparkline(QWidget):
    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.values: list[float] = []
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: list[float]) -> None:
        self.values = values[-60:]
        self.update()

    def paintEvent(self, _event) -> None:
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height() - 2
        step = w / (len(self.values) - 1)
        pts = [QPointF(i * step, 1 + h - (max(0.0, min(100.0, v)) / 100.0) * h) for i, v in enumerate(self.values)]
        area = QPolygonF([QPointF(0, h + 1), *pts, QPointF(w, h + 1)])
        fill = QColor(self.theme.accent)
        fill.setAlpha(45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPolygon(area)
        pen = QPen(QColor(self.theme.accent), 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF(pts))
        p.end()


class Meter(QWidget):
    """Thin rounded progress bar with threshold colours."""

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.pct: float | None = None
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_pct(self, pct: float | None) -> None:
        self.pct = pct
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.theme.border))
        p.drawRoundedRect(r, 4, 4)
        if self.pct is not None:
            pct = max(0.0, min(100.0, self.pct))
            t = self.theme
            p.setBrush(QColor(t.success if pct < 70 else t.warning if pct < 90 else t.danger))
            p.drawRoundedRect(QRectF(0, 0, max(8.0, r.width() * pct / 100), r.height()), 4, 4)
        p.end()


class MetricCard(QFrame):
    def __init__(self, title: str, theme: Theme, sparkline: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(6)
        cap = QLabel(title.upper())
        cap.setObjectName("Caption")
        lay.addWidget(cap)
        row = QHBoxLayout()
        self.value = QLabel("--")
        self.value.setObjectName("BigNumber")
        row.addWidget(self.value)
        row.addStretch()
        lay.addLayout(row)
        self.detail = QLabel("")
        self.detail.setObjectName("Muted")
        self.meter = Meter(theme)
        self.spark = Sparkline(theme) if sparkline else None
        if self.spark:
            lay.addWidget(self.spark)
        else:
            lay.addWidget(self.meter)
        lay.addWidget(self.detail)
        self.setMinimumWidth(170)

    def set(self, value: str, detail: str = "", pct: float | None = None, history: list[float] | None = None) -> None:
        self.value.setText(value)
        self.detail.setText(detail)
        self.meter.set_pct(pct)
        if self.spark is not None:
            self.spark.set_values(history or [])


class Pill(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Pill")

    def set_state(self, text: str, color: str, theme: Theme) -> None:
        self.setText(text)
        self.setStyleSheet(f"background: {mix(theme.surface, color, 0.22)}; color: {color};")


def hairline() -> QFrame:
    f = QFrame()
    f.setObjectName("Hairline")
    return f
