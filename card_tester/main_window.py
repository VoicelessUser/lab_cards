# -*- coding: utf-8 -*-
"""Главное окно «колоды приборов».

Перетаскивание ручное (как в Hearthstone): карту «берёшь» из колоды или ленты,
она летит за курсором, место вставки подсвечивается линией, соседние карты
разъезжаются; «выкладываешь» на ленту или в цикл. Всплывающих окон нет —
настройки карты и цикла всегда справа. Лог-окна нет: во время запуска
пользователь видит график свипа и последнюю строку статуса.
"""
import copy
import csv
import logging
import math
import os
from datetime import datetime

from .qt import (QtCore, QtGui, QtWidgets, Signal,
                 QAction, QShortcut, mouse_pos)
from .cards import (Card, ForLoop, CATALOG, C_LOOP, DEVICE_LABELS,
                    new_card, describe, summarize, loop_label, find_container,
                    remove_items, expand_on_off_pairs, collect_set_cards,
                    card_color, card_device_label, card_icon,
                    meas_kind_options, stats_rows)
from .runner import RunThread, IdnThread, PS_MODELS, MM_MODELS
from .program_io import save_program, load_program

KIND_COLORS = {
    'info': '#111827', 'meas': '#047857', 'ok': '#047857',
    'error': '#b91c1c', 'warn': '#b45309', 'loop': '#6d28d9', 'hw': '#6b7280',
}

# папка пресетов (рядом с пакетом card_tester)
PRESETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'presets')
# папка результатов запуска
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'output')

# подключённые приборы стенда (порты определены сканированием VISA, *IDN? отвечают)
DEFAULT_PS = {'model': 'DP832A',    # Rigol DP832 (прошивка отвечает как DP832A)
              'port': 'USB0::0x1AB1::0x0E11::DP8B262201226::INSTR'}
DEFAULT_MM = {'model': 'AKIP2101',  # AKIP-2101/2102-SC
              'port': 'USB0::0xF4EC::0xEE38::SDM35GBD6R2181::INSTR'}


# ---------------------------------------------------------------- значки
def make_icon(kind, size=16, color='#FFFFFF'):
    """Мини-значок прибора: 'ps' — молния, 'mm' — мультиметр, 'sys' — часы."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(1.6)
    p.setPen(pen)
    p.setBrush(QtGui.QBrush(QtGui.QColor(color)))
    s = size
    if kind == 'ps':      # молния
        poly = QtGui.QPolygonF([
            QtCore.QPointF(s * 0.58, s * 0.05), QtCore.QPointF(s * 0.18, s * 0.55),
            QtCore.QPointF(s * 0.45, s * 0.55), QtCore.QPointF(s * 0.40, s * 0.95),
            QtCore.QPointF(s * 0.82, s * 0.38), QtCore.QPointF(s * 0.52, s * 0.38)])
        p.drawPolygon(poly)
    elif kind == 'mm':    # корпус мультиметра с экраном и щупами
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(int(s * 0.12), int(s * 0.22), int(s * 0.76), int(s * 0.62), 2, 2)
        p.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        p.drawRect(int(s * 0.26), int(s * 0.34), int(s * 0.48), int(s * 0.16))
        p.drawLine(int(s * 0.3), int(s * 0.84), int(s * 0.3), int(s * 0.97))
        p.drawLine(int(s * 0.7), int(s * 0.84), int(s * 0.7), int(s * 0.97))
    elif kind == 'sys':   # часы
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(int(s * 0.1), int(s * 0.1), int(s * 0.8), int(s * 0.8))
        p.drawLine(int(s * 0.5), int(s * 0.5), int(s * 0.5), int(s * 0.26))
        p.drawLine(int(s * 0.5), int(s * 0.5), int(s * 0.68), int(s * 0.58))
    p.end()
    return pm


def _lighten(hex_color, f):
    c = QtGui.QColor(hex_color)
    r = int(c.red() + (255 - c.red()) * f)
    g = int(c.green() + (255 - c.green()) * f)
    b = int(c.blue() + (255 - c.blue()) * f)
    return f'#{r:02x}{g:02x}{b:02x}'


# ---------------------------------------------------------------- рисунок прибора
def paint_instrument_art(p, r, device):
    """Большой рисунок в середине карты: корпус прибора.

    'ps'  — источник питания: тёмный корпус, экран с осциллограммой,
            ручки регулировки, клеммы;
    'mm'  — мультиметр: вертикальный корпус, крупный дисплей, диск
            переключения, гнёзда щупов;
    'sys' — песочные часы (Delay).
    """
    rx, ry, rw, rh = r.x(), r.y(), r.width(), r.height()
    if device == 'ps':
        body = QtCore.QRectF(rx + rw * 0.06, ry + rh * 0.06, rw * 0.88, rh * 0.88)
        p.setPen(QtGui.QPen(QtGui.QColor('#171b22'), 1.5))
        p.setBrush(QtGui.QColor('#2E3440'))
        p.drawRoundedRect(body, 6, 6)
        # экран с осциллограммой
        disp = QtCore.QRectF(body.x() + body.width() * 0.08, body.y() + body.height() * 0.10,
                             body.width() * 0.52, body.height() * 0.30)
        p.setBrush(QtGui.QColor('#0e1a11'))
        p.setPen(QtGui.QPen(QtGui.QColor('#0a0f0b'), 1))
        p.drawRoundedRect(disp, 3, 3)
        wave = QtGui.QPolygonF()
        for i in range(13):
            t = i / 12
            wave.append(QtCore.QPointF(
                disp.x() + 3 + t * (disp.width() - 6),
                disp.center().y() - math.sin(t * math.pi * 3) * disp.height() * 0.3))
        p.setPen(QtGui.QPen(QtGui.QColor('#ffd166'), 1.6))
        p.drawPolyline(wave)
        p.setPen(QtGui.QPen(QtGui.QColor('#7cff9b')))
        f = p.font()
        f.setBold(True)
        f.setPointSize(7)
        p.setFont(f)
        p.drawText(disp, int(QtCore.Qt.AlignmentFlag.AlignRight
                             | QtCore.Qt.AlignmentFlag.AlignVCenter), ' 3.3V ')
        # ручки
        for ky in (0.28, 0.58):
            cx = body.x() + body.width() * 0.78
            cy = body.y() + body.height() * ky
            rad = body.width() * 0.075
            p.setBrush(QtGui.QColor('#4C566A'))
            p.setPen(QtGui.QPen(QtGui.QColor('#171b22'), 1.5))
            p.drawEllipse(QtCore.QPointF(cx, cy), rad, rad)
            p.setPen(QtGui.QPen(QtGui.QColor('#d8dee9'), 1.4))
            p.drawLine(QtCore.QPointF(cx, cy),
                       QtCore.QPointF(cx + rad * 0.7, cy - rad * 0.7))
        # клеммы
        for tx, col in ((0.22, '#d64545'), (0.45, '#20242b'), (0.68, '#3f9d55')):
            p.setBrush(QtGui.QColor(col))
            p.setPen(QtGui.QPen(QtGui.QColor('#171b22'), 1.2))
            p.drawEllipse(QtCore.QPointF(body.x() + body.width() * tx,
                                         body.y() + body.height() * 0.84),
                          body.width() * 0.055, body.width() * 0.055)
        # вентиляция
        p.setPen(QtGui.QPen(QtGui.QColor('#3b4252'), 1.2))
        for i in range(3):
            yy = body.y() + body.height() * (0.50 + i * 0.09)
            p.drawLine(QtCore.QPointF(body.x() + body.width() * 0.10, yy),
                       QtCore.QPointF(body.x() + body.width() * 0.34, yy))
    elif device == 'mm':
        body = QtCore.QRectF(rx + rw * 0.24, ry + rh * 0.05, rw * 0.52, rh * 0.90)
        p.setPen(QtGui.QPen(QtGui.QColor('#2b1118'), 1.5))
        p.setBrush(QtGui.QColor('#6B2D3C'))
        p.drawRoundedRect(body, 8, 8)
        # дисплей
        disp = QtCore.QRectF(body.x() + body.width() * 0.12, body.y() + body.height() * 0.09,
                             body.width() * 0.76, body.height() * 0.26)
        p.setBrush(QtGui.QColor('#0e1a11'))
        p.setPen(QtGui.QPen(QtGui.QColor('#0a0f0b'), 1))
        p.drawRoundedRect(disp, 3, 3)
        p.setPen(QtGui.QPen(QtGui.QColor('#7cff9b')))
        f = p.font()
        f.setBold(True)
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(disp, int(QtCore.Qt.AlignmentFlag.AlignCenter), '3.30')
        # диск переключения
        dc = QtCore.QPointF(body.center().x(), body.y() + body.height() * 0.60)
        rad = body.width() * 0.26
        p.setBrush(QtGui.QColor('#ECEFF4'))
        p.setPen(QtGui.QPen(QtGui.QColor('#2b1118'), 1.5))
        p.drawEllipse(dc, rad, rad)
        p.setPen(QtGui.QPen(QtGui.QColor('#2b1118'), 2))
        p.drawLine(dc, QtCore.QPointF(dc.x() + rad * 0.75, dc.y() - rad * 0.45))
        for ang in (0, 90, 180, 270):
            a = math.radians(ang + 45)
            p.drawPoint(QtCore.QPointF(dc.x() + math.cos(a) * rad * 0.85,
                                       dc.y() + math.sin(a) * rad * 0.85))
        # гнёзда щупов
        for tx, col in ((0.28, '#d64545'), (0.56, '#20242b'), (0.76, '#4c566a')):
            p.setBrush(QtGui.QColor(col))
            p.setPen(QtGui.QPen(QtGui.QColor('#2b1118'), 1.2))
            p.drawEllipse(QtCore.QPointF(body.x() + body.width() * tx,
                                         body.y() + body.height() * 0.88),
                          body.width() * 0.06, body.width() * 0.06)
    else:  # 'sys' — песочные часы
        p.setPen(QtGui.QPen(QtGui.QColor('#4C566A'), 2))
        p.setBrush(QtGui.QColor('#4C566A'))
        top_bar = QtCore.QRectF(rx + rw * 0.18, ry + rh * 0.10, rw * 0.64, rh * 0.06)
        bot_bar = QtCore.QRectF(rx + rw * 0.18, ry + rh * 0.84, rw * 0.64, rh * 0.06)
        p.drawRoundedRect(top_bar, 3, 3)
        p.drawRoundedRect(bot_bar, 3, 3)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        cx, mid_y = r.center().x(), r.center().y()
        hw, hh = rw * 0.30, rh * 0.34
        p.drawPolyline([QtCore.QPointF(cx - hw, ry + rh * 0.16),
                        QtCore.QPointF(cx + hw, ry + rh * 0.16),
                        QtCore.QPointF(cx, mid_y),
                        QtCore.QPointF(cx - hw, ry + rh * 0.84),
                        QtCore.QPointF(cx + hw, ry + rh * 0.84),
                        QtCore.QPointF(cx, mid_y),
                        QtCore.QPointF(cx - hw, ry + rh * 0.16)])
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor('#E0B15E'))
        p.drawPolygon([QtCore.QPointF(cx - hw * 0.55, ry + rh * 0.82),
                       QtCore.QPointF(cx + hw * 0.55, ry + rh * 0.82),
                       QtCore.QPointF(cx, mid_y + hh * 0.12)])
        p.drawPolygon([QtCore.QPointF(cx - hw * 0.45, ry + rh * 0.18),
                       QtCore.QPointF(cx + hw * 0.45, ry + rh * 0.18),
                       QtCore.QPointF(cx, mid_y - hh * 0.10)])


# ---------------------------------------------------------------- стили
def loop_qss(selected):
    """Зона цикла: жёлтый градиент ПОД картами (подсветка), не окно."""
    border = '3px solid #F5B301' if selected else '1px solid #E3A008'
    top = '#FFF7DB' if not selected else '#FFFBEB'
    bottom = '#FFC940' if not selected else '#FFD75E'
    return f"""
    QFrame#loopFrame {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {top}, stop:1 {bottom});
        border: {border}; border-radius: 12px; }}
    QLabel#loopCaption {{ color: #7A5200; font-weight: bold; font-size: 7pt;
        border: none; background: transparent; }}
    """


# ---------------------------------------------------------------- строки карт
class CardRowWidget(QtWidgets.QWidget):
    """Строка карт с ручной раскладкой и подсветкой места вставки.

    Используется как лента программы (верхний уровень) и как тело цикла.
    Перетаскивание ручное (без QDrag): строка только показывает прорезь
    (prepare_drag/_set_hover/clear_hover/finish_drag) и считает индекс.
    """

    MARGIN_L = 12
    MARGIN_R = 12
    MARGIN_T = 10
    MARGIN_B = 10
    SPACING = 8
    GAP = 46          # ширина «разъезда» под место вставки

    def __init__(self, win, container):
        super().__init__()
        self.win = win
        self.container = container          # список модели: sequence или loop.children
        self._views = []
        self._drag_view = None              # перетаскиваемая карта (исключается)
        self._drag_index = None             # индекс прорези в этой строке
        self._gap_x = None
        self._anims = []

        self._indicator = QtWidgets.QFrame(self)
        self._indicator.setFixedWidth(5)
        self._indicator.setStyleSheet(
            f'background: {C_LOOP}; border: none; border-radius: 2px;')
        self._indicator.hide()

        self._hint = QtWidgets.QLabel('', self)
        self._hint.setObjectName('rowHint')
        self._hint.setStyleSheet('QLabel#rowHint { color: #9ca3af; font-size: 10pt; }')

    # --------------------------------------------------------- раскладка
    def set_items(self, views):
        for v in self._views:
            v.setParent(None)
            v.deleteLater()
        self._views = []
        for v in views:
            v.setParent(self)
            v.show()
            self._views.append(v)
        if self._views:
            self._hint.hide()
        else:
            if self.container is self.win.sequence:
                self._hint.setText('Возьмите карту из колоды (внизу) и выложите сюда,\n'
                                   'или кликните по карте в колоде — она добавится в конец.')
            else:
                self._hint.setText('выложите карты в цикл')
                self._hint.setStyleSheet('QLabel#rowHint { color: #A16207; font-size: 10pt; }')
            self._hint.adjustSize()
            self._hint.move(self.MARGIN_L + 4, self.MARGIN_T)
            self._hint.show()
        self.relayout()

    def _view_width(self, v):
        return max(v.minimumSizeHint().width(), 20)

    def _view_height(self, v):
        return max(v.minimumSizeHint().height(), 20)

    def _active_views(self):
        return [v for v in self._views if v is not self._drag_view]

    def _layout_positions(self):
        A = self._active_views()
        g = self._drag_index
        xs = []
        x = self.MARGIN_L
        gap_x = None
        for j, v in enumerate(A):
            if g is not None and j == g:
                gap_x = x
                x += self.GAP
            xs.append(x)
            x += self._view_width(v) + self.SPACING
        if g is not None and g >= len(A):
            gap_x = x
        return A, xs, gap_x

    def minimumSizeHint(self):
        A, xs, gap_x = self._layout_positions()
        if A:
            w = xs[-1] + self._view_width(A[-1]) + self.MARGIN_R
        elif self._views:
            w = self.MARGIN_L + self._view_width(self._views[0]) + self.MARGIN_R
        else:
            w = max(self._hint.width() + 40, 420)
        h = self.MARGIN_T + max(
            [self._view_height(v) for v in self._views] or [self._hint.height() or 70]
        ) + self.MARGIN_B
        if gap_x is not None:
            w += self.GAP
        return QtCore.QSize(w, h)

    def relayout(self, animate=False):
        A, xs, gap_x = self._layout_positions()
        self._gap_x = gap_x
        for a in self._anims:
            a.stop()
        self._anims = []
        for j, v in enumerate(A):
            target = QtCore.QPoint(xs[j], self.MARGIN_T)
            if not animate:
                v.move(target)
            elif v.pos() != target:
                an = QtCore.QPropertyAnimation(v, b'pos', self)
                an.setDuration(130)
                an.setEndValue(target)
                an.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                an.start()
                self._anims.append(an)
        self._update_indicator()
        # лента (верхний уровень): сообщаем scrollarea, что минимальный
        # размер изменился — иначе она «залипает» на ширине окна и колесу
        # нечего крутить (карты за краем недоступны)
        if self.container is self.win.sequence:
            self.updateGeometry()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.relayout()

    # --------------------------------------------------------- индикатор
    def _update_indicator(self):
        if (self._drag_index is not None and self.win._hover_row is self
                and self._gap_x is not None):
            self._indicator.setGeometry(
                self._gap_x - 2, 4, 5, max(20, self.height() - 8))
            self._indicator.show()
            self._indicator.raise_()
        else:
            self._indicator.hide()

    def _index_for_x(self, x):
        A, xs, _gap = self._layout_positions()
        idx = 0
        for j, v in enumerate(A):
            if x >= xs[j] + self._view_width(v) / 2:
                idx = j + 1
        return idx

    # --------------------------------------------------------- прорезь
    def _set_hover(self, x):
        idx = self._index_for_x(x)
        if idx != self._drag_index:
            self._drag_index = idx
            self.relayout(animate=True)
        self._update_indicator()

    def clear_hover(self):
        if self.win._hover_row is self:
            self.win._hover_row = None
        if self._drag_view is not None:
            self._drag_index = self._views.index(self._drag_view)
        else:
            self._drag_index = None
        self.relayout(animate=True)
        self._update_indicator()

    def prepare_drag(self, view):
        self._drag_view = view
        self._drag_index = self._views.index(view)
        self.relayout(animate=True)
        self._update_indicator()

    def finish_drag(self):
        self._drag_view = None
        self._drag_index = None
        self.relayout(animate=True)
        self._update_indicator()


# ---------------------------------------------------------------- виджеты карт
class CardView(QtWidgets.QFrame):
    """Коллекционная карта (как в ККГ): вертикальная, сверху баннер с названием,
    в середине большой рисунок прибора, ниже тёмная панель параметров (статы),
    внизу подпись прибора. Цвет карты — по типу действия (Meas всегда зелёная).

    Всё нарисовано в paintEvent — никаких «табличек».
    """

    W, H = 150, 210

    def __init__(self, card, win):
        super().__init__()
        self.card = card
        self.win = win
        self.setFixedSize(self.W, self.H)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._press_pos = None

    def minimumSizeHint(self):
        # без layout у paint-карты Qt вернул бы «пусто», и раскладчик
        # ставил бы карты вплотную — карты накладывались друг на друга
        return QtCore.QSize(self.W, self.H)

    def sizeHint(self):
        return QtCore.QSize(self.W, self.H)

    def refresh_style(self):
        self.update()

    def refresh_body(self):
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.W, self.H
        color = card_color(self.card)
        sel = self.win.is_selected(self.card.id)

        # корпус карты: вертикальный градиент цвета действия
        grad = QtGui.QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QtGui.QColor(_lighten(color, 0.60 if sel else 0.45)))
        grad.setColorAt(1.0, QtGui.QColor(_lighten(color, 0.25 if sel else 0.0)))
        pen = QtGui.QPen(QtGui.QColor('#F5B301'), 3) if sel \
            else QtGui.QPen(QtGui.QColor('#3A3A42'), 2)
        p.setPen(pen)
        p.setBrush(QtGui.QBrush(grad))
        p.drawRoundedRect(QtCore.QRectF(1.5, 1.5, w - 3, h - 3), 14, 14)

        # баннер с названием (как рамка имени на КК)
        banner = QtCore.QRectF(10, 9, w - 20, 26)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(12, 12, 16, 215))
        p.drawRoundedRect(banner, 8, 8)
        p.setBrush(QtGui.QColor(color))
        p.drawRoundedRect(QtCore.QRectF(banner.x(), banner.bottom() - 2.5,
                                        banner.width(), 2.5), 1, 1)
        p.setPen(QtGui.QPen(QtGui.QColor('#ffffff')))
        f = p.font()
        f.setBold(True)
        f.setPointSize(10)
        p.setFont(f)
        p.drawText(banner, int(QtCore.Qt.AlignmentFlag.AlignCenter),
                   CATALOG[self.card.type]['title'])

        # рисунок прибора в середине
        art = QtCore.QRectF(9, 41, w - 18, 94)
        p.setPen(QtGui.QPen(QtGui.QColor(color).darker(160), 1))
        p.setBrush(QtGui.QColor('#FAF7EE'))
        p.drawRoundedRect(art, 8, 8)
        paint_instrument_art(p, art.adjusted(6, 5, -6, -5), card_icon(self.card))

        # тёмная панель параметров (как статы на КК)
        st = QtCore.QRectF(9, h - 64, w - 18, 44)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(12, 12, 16, 228))
        p.drawRoundedRect(st, 8, 8)
        f = p.font()
        f.setBold(False)
        f.setPointSize(7)
        p.setFont(f)
        align_l = int(QtCore.Qt.AlignmentFlag.AlignLeft
                      | QtCore.Qt.AlignmentFlag.AlignVCenter)
        align_r = int(QtCore.Qt.AlignmentFlag.AlignRight
                      | QtCore.Qt.AlignmentFlag.AlignVCenter)
        y = st.top() + 5
        for label, value in stats_rows(self.card)[:3]:
            row = QtCore.QRectF(st.x() + 8, y, st.width() - 16, 12)
            p.setPen(QtGui.QPen(QtGui.QColor('#c9cdd4')))
            p.drawText(row, align_l, label)
            p.setPen(QtGui.QPen(QtGui.QColor('#ffffff')))
            f2 = p.font()
            f2.setBold(True)
            p.setFont(f2)
            p.drawText(row, align_r, value)
            f2.setBold(False)
            p.setFont(f2)
            y += 13.5

        # подпись прибора внизу
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 225)))
        f3 = p.font()
        f3.setBold(True)
        f3.setPointSize(7)
        p.setFont(f3)
        p.drawText(QtCore.QRectF(0, h - 17, w, 13),
                   int(QtCore.Qt.AlignmentFlag.AlignCenter),
                   card_device_label(self.card))

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press_pos = mouse_pos(ev)
            self.win.on_item_clicked(self.card.id, ev.modifiers())
        # клик принадлежит карте: не отдаём его жёлтой зоне цикла,
        # иначе она перебивала выделение и настройки карты (справа)
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        # двойной клик по карте не должен выделять цикл
        ev.accept()

    def mouseMoveEvent(self, ev):
        if (self._press_pos is not None
                and ev.buttons() & QtCore.Qt.MouseButton.LeftButton
                and not self.win.running
                and (mouse_pos(ev) - self._press_pos).manhattanLength() > 12):
            self.win.begin_move_drag(self, self.card.id,
                                     ev.globalPosition().toPoint())
            return
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._press_pos = None
        ev.accept()

    def _menu(self, pos):
        win = self.win
        win.on_item_clicked(self.card.id, QtCore.Qt.KeyboardModifier())
        m = QtWidgets.QMenu(self)
        m.addAction('◀ Влево', lambda: win.move_selected(-1))
        m.addAction('▶ Вправо', lambda: win.move_selected(+1))
        m.addAction('Дублировать', win.duplicate_selected)
        m.addSeparator()
        m.addAction('⟳ Обернуть в цикл', win.wrap_in_loop)
        m.addSeparator()
        m.addAction('Удалить', win.delete_selection)
        m.exec(self.mapToGlobal(pos))


class LoopView(QtWidgets.QFrame):
    """Зона цикла: жёлтая градиентная подложка ПОД картами. Клик по ней
    выделяет цикл (настройки справа), клики по картам работают как обычно."""

    def __init__(self, loop, win):
        super().__init__()
        self.loop = loop
        self.win = win
        self.setObjectName('loopFrame')
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(9, 4, 9, 7)
        lay.setSpacing(2)
        self.caption = QtWidgets.QLabel('⟳ ' + loop_label(loop))
        self.caption.setObjectName('loopCaption')
        lay.addWidget(self.caption)
        self.body = CardRowWidget(win, loop.children)
        lay.addWidget(self.body, 1)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._press_pos = None
        self.refresh_style()

    def set_label(self):
        self.caption.setText('⟳ ' + loop_label(self.loop))

    def refresh_style(self):
        self.setStyleSheet(loop_qss(self.win.is_selected(self.loop.id)))

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press_pos = mouse_pos(ev)
            self.win.on_item_clicked(self.loop.id, ev.modifiers())
        # клик по жёлтой зоне — настройка цикла (справа); карты принимают
        # свои клики сами и до зоны они не доходят
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        # нет всплывающих окон: показать настройки цикла справа
        self.win.on_item_clicked(self.loop.id, QtCore.Qt.KeyboardModifier())
        ev.accept()

    def mouseMoveEvent(self, ev):
        if (self._press_pos is not None
                and ev.buttons() & QtCore.Qt.MouseButton.LeftButton
                and not self.win.running
                and (mouse_pos(ev) - self._press_pos).manhattanLength() > 12):
            self.win.begin_move_drag(self, self.loop.id,
                                     ev.globalPosition().toPoint())
            return
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._press_pos = None
        ev.accept()

    def _menu(self, pos):
        win = self.win
        win.on_item_clicked(self.loop.id, QtCore.Qt.KeyboardModifier())
        m = QtWidgets.QMenu(self)
        m.addAction('Настройки цикла (справа)',
                    lambda: win.on_item_clicked(self.loop.id, QtCore.Qt.KeyboardModifier()))
        m.addAction('Разобрать цикл', win.unwrap_loop)
        m.addSeparator()
        m.addAction('◀ Влево', lambda: win.move_selected(-1))
        m.addAction('▶ Вправо', lambda: win.move_selected(+1))
        m.addSeparator()
        m.addAction('Удалить', win.delete_selection)
        m.exec(self.mapToGlobal(pos))


# ---------------------------------------------------------------- колода
# Стопки колоды по приборам: у каждого прибора свой набор стопок,
# карты отличаются рисунком прибора, но стиль один (Meas всегда зелёная).
DECK_GROUPS = [
    ('БП', [('set', 'Set', 'ps'), ('meas', 'Meas', 'ps'), ('on', 'ON/OFF', 'ps')]),
    ('Мультиметр', [('meas', 'Meas', 'mm')]),
    ('Система', [('delay', 'Delay', 'sys')]),
]


class StackWidget(QtWidgets.QFrame):
    """Стопка вертикальных карт одного типа у прибора в колоде.

    Клик — добавить карту в конец программы; карту можно ВЗЯТЬ из стопки
    и ВЫЛОЖИТЬ на ленту/в цикл — за курсором летит «призрак» карты.
    """

    W, H = 112, 156

    def __init__(self, card_type, title, device, win):
        super().__init__()
        self.card_type = card_type
        self.title = title
        self.device = device              # прибор стопки ('ps'/'mm'/'sys')
        self.color = CATALOG[card_type]['color']
        self.win = win
        self._press = None
        self._dragging = False
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def minimumSizeHint(self):
        return QtCore.QSize(self.W, self.H)

    def sizeHint(self):
        return QtCore.QSize(self.W, self.H)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        face = QtCore.QRectF(4, 4, self.W - 16, self.H - 22)
        # нижние карты стопки
        for dx, dy in ((12, 8), (6, 4)):
            p.setPen(QtGui.QPen(QtGui.QColor('#3A3A42'), 2))
            p.setBrush(QtGui.QBrush(QtGui.QColor(_lighten(self.color, 0.12))))
            p.drawRoundedRect(face.adjusted(dx, dy, dx, dy), 10, 10)
        # верхняя карта стопки (мини-лицо)
        grad = QtGui.QLinearGradient(face.x(), face.y(), face.x(), face.bottom())
        grad.setColorAt(0.0, QtGui.QColor(_lighten(self.color, 0.45)))
        grad.setColorAt(1.0, QtGui.QColor(self.color))
        p.setBrush(QtGui.QBrush(grad))
        p.setPen(QtGui.QPen(QtGui.QColor('#3A3A42'), 2))
        p.drawRoundedRect(face, 10, 10)
        # мини-баннер
        banner = QtCore.QRectF(face.x() + 5, face.y() + 5, face.width() - 10, 18)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(12, 12, 16, 200))
        p.drawRoundedRect(banner, 5, 5)
        p.setPen(QtGui.QPen(QtGui.QColor('#ffffff')))
        f = p.font()
        f.setBold(True)
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(banner, int(QtCore.Qt.AlignmentFlag.AlignCenter), self.title)
        # мини-рисунок прибора
        art = QtCore.QRectF(face.x() + 5, face.y() + 27,
                            face.width() - 10, face.height() - 66)
        p.setPen(QtGui.QPen(QtGui.QColor(self.color).darker(160), 1))
        p.setBrush(QtGui.QColor('#FAF7EE'))
        p.drawRoundedRect(art, 5, 5)
        paint_instrument_art(p, art.adjusted(4, 3, -4, -3), self.device)
        # мини-блок статов
        st = QtCore.QRectF(face.x() + 5, face.bottom() - 36, face.width() - 10, 30)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(12, 12, 16, 210))
        p.drawRoundedRect(st, 5, 5)
        p.setPen(QtGui.QPen(QtGui.QColor('#c9cdd4')))
        f2 = p.font()
        f2.setPointSize(6)
        p.setFont(f2)
        p.drawText(QtCore.QRectF(st.x() + 4, st.y() + 2, st.width() - 8, 12),
                   int(QtCore.Qt.AlignmentFlag.AlignLeft
                       | QtCore.Qt.AlignmentFlag.AlignVCenter),
                   'ПАРАМЕТРЫ')
        p.drawText(QtCore.QRectF(st.x() + 4, st.y() + 15, st.width() - 8, 12),
                   int(QtCore.Qt.AlignmentFlag.AlignLeft
                       | QtCore.Qt.AlignmentFlag.AlignVCenter),
                   card_device_label(new_card(self.card_type))
                   if self.card_type != 'meas' else DEVICE_LABELS[self.device])
        f3 = p.font()
        f3.setPointSize(8)
        p.setFont(f3)

    def _drag_pixmap(self):
        card = new_card(self.card_type)
        if self.card_type == 'meas':
            card.params['device'] = self.device
        tmp = CardView(card, self.win)
        pix = tmp.grab()
        tmp.setParent(None)
        tmp.deleteLater()
        return pix

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = mouse_pos(ev)
            self._dragging = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if (self._press is not None
                and ev.buttons() & QtCore.Qt.MouseButton.LeftButton
                and not self.win.running
                and not self._dragging
                and (mouse_pos(ev) - self._press).manhattanLength() > 12):
            self._dragging = True
            self.win.begin_new_drag(self, self.card_type,
                                    ev.globalPosition().toPoint())
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        was_click = self._press is not None and not self._dragging
        self._press = None
        self._dragging = False
        if (was_click and ev.button() == QtCore.Qt.MouseButton.LeftButton
                and not self.win.running):
            self.win.add_card(self.card_type, device=self.device)
        super().mouseReleaseEvent(ev)


# ---------------------------------------------------------------- график
PALETTE = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd',
           '#ff7f0e', '#17becf', '#8c564b', '#e377c2']


class PlotWidget(QtWidgets.QWidget):
    """График реального времени без внешних зависимостей (QPainter).

    X — свипируемый параметр, Y — измерения; каждая Meas-карта — своя кривая.
    """

    M_L, M_R, M_T, M_B = 52, 14, 30, 36

    def __init__(self):
        super().__init__()
        self.series = {}
        self.colors = {}
        self.x_name = ''
        self._color_i = 0
        self.setMinimumSize(300, 220)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QtGui.QColor('#ffffff'))
        self.setPalette(pal)

    def clear(self):
        self.series = {}
        self.colors = {}
        self.x_name = ''
        self._color_i = 0
        self.update()

    def add_point(self, var_name, label, x, y):
        self.x_name = var_name or 'X'
        if label not in self.series:
            self.series[label] = []
            self.colors[label] = PALETTE[self._color_i % len(PALETTE)]
            self._color_i += 1
        self.series[label].append((float(x), float(y)))
        self.update()

    def _bounds(self):
        xs = [p[0] for pts in self.series.values() for p in pts]
        ys = [p[1] for pts in self.series.values() for p in pts]
        if not xs:
            return 0.0, 1.0, 0.0, 1.0
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if x1 - x0 < 1e-12:
            x0, x1 = x0 - 1.0, x1 + 1.0
        if y1 - y0 < 1e-12:
            y0, y1 = y0 - 1.0, y1 + 1.0
        px = (x1 - x0) * 0.08
        py = (y1 - y0) * 0.08
        return x0 - px, x1 + px, y0 - py, y1 + py

    @staticmethod
    def _ticks(a, b, n=4):
        raw = (b - a) / n
        if raw <= 0:
            return [a]
        mag = 10 ** math.floor(math.log10(raw))
        step = 10 * mag
        for m in (1, 2, 5, 10):
            if raw <= m * mag:
                step = m * mag
                break
        t = math.ceil(a / step) * step
        out = []
        while t <= b + 1e-12:
            out.append(t)
            t += step
        return out

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QtGui.QColor('#ffffff'))
        x0, x1, y0, y1 = self._bounds()

        def fx(x):
            return self.M_L + (x - x0) / (x1 - x0) * (w - self.M_L - self.M_R)

        def fy(y):
            return h - self.M_B - (y - y0) / (y1 - y0) * (h - self.M_T - self.M_B)

        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        align_c = int(QtCore.Qt.AlignmentFlag.AlignHCenter)
        align_r = int(QtCore.Qt.AlignmentFlag.AlignRight
                      | QtCore.Qt.AlignmentFlag.AlignVCenter)
        p.setPen(QtGui.QPen(QtGui.QColor('#e5e7eb')))
        for t in self._ticks(x0, x1):
            X = int(fx(t))
            p.drawLine(X, self.M_T, X, h - self.M_B)
        for t in self._ticks(y0, y1):
            Y = int(fy(t))
            p.drawLine(self.M_L, Y, w - self.M_R, Y)
        p.setPen(QtGui.QPen(QtGui.QColor('#374151')))
        for t in self._ticks(x0, x1):
            p.drawText(int(fx(t)) - 22, h - self.M_B + 4, 44, 12, align_c, f'{t:g}')
        for t in self._ticks(y0, y1):
            p.drawText(2, int(fy(t)) - 6, self.M_L - 6, 12, align_r, f'{t:g}')
        p.setPen(QtGui.QPen(QtGui.QColor('#9ca3af')))
        p.drawLine(self.M_L, self.M_T, self.M_L, h - self.M_B)
        p.drawLine(self.M_L, h - self.M_B, w - self.M_R, h - self.M_B)
        p.setPen(QtGui.QPen(QtGui.QColor('#6b7280')))
        p.drawText(w - self.M_R - 70, h - self.M_B + 4, 70, 12,
                   int(QtCore.Qt.AlignmentFlag.AlignRight), self.x_name or 'X')
        for label, pts in self.series.items():
            if not pts:
                continue
            color = QtGui.QColor(self.colors[label])
            pen = QtGui.QPen(color)
            pen.setWidthF(2)
            p.setPen(pen)
            if len(pts) > 1:
                for i in range(1, len(pts)):
                    p.drawLine(QtCore.QPointF(fx(pts[i - 1][0]), fy(pts[i - 1][1])),
                               QtCore.QPointF(fx(pts[i][0]), fy(pts[i][1])))
            p.setBrush(QtGui.QBrush(color))
            for (px, py) in pts:
                p.drawEllipse(QtCore.QPointF(fx(px), fy(py)), 3, 3)
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        y_leg = 6
        for label in self.series:
            color = QtGui.QColor(self.colors[label])
            p.setPen(QtGui.QPen(color))
            p.setBrush(QtGui.QBrush(color))
            p.drawRect(self.M_L + 2, y_leg + 3, 8, 8)
            p.setPen(QtGui.QPen(QtGui.QColor('#111827')))
            name = label if len(label) <= 40 else label[:39] + '…'
            p.drawText(self.M_L + 14, y_leg, w - self.M_L - self.M_R - 14, 14,
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter), name)
            y_leg += 14
        p.end()


# ---------------------------------------------------------------- окно
# ---------------------------------------------------------------- окно отчёта
class RunReportDialog(QtWidgets.QDialog):
    """Всплывающее окно при запуске программы: таблица измерений,
    график свипа и ошибки (если есть)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Запуск программы — отчёт')
        self.resize(1020, 640)
        lay = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.setSpacing(6)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ['Время', 'Прибор', 'Измерение', 'Значение'])
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.resizeSection(0, 105)
        hh.resizeSection(1, 55)
        hh.resizeSection(2, 300)
        f = self.table.font()
        f.setPointSize(9)
        self.table.setFont(f)
        lv.addWidget(self.table, 1)
        bottom = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel('Измерений: 0')
        save_btn = QtWidgets.QPushButton('💾 Сохранить результаты')
        save_btn.setFixedHeight(28)
        save_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton { background: #2f6fd6; color: white; font-weight: bold;
                border: none; border-radius: 6px; padding: 0 12px; }
            QPushButton:hover { border: 2px solid #F5B301; }""")
        save_btn.clicked.connect(self.save_results)
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(save_btn)
        lv.addLayout(bottom)
        self.error_box = QtWidgets.QPlainTextEdit()
        self.error_box.setReadOnly(True)
        self.error_box.setPlaceholderText('Ошибок нет')
        self.error_box.setMaximumHeight(96)
        fe = self.error_box.font()
        fe.setPointSize(8)
        self.error_box.setFont(fe)
        self.error_box.setStyleSheet(
            'QPlainTextEdit { color: #b91c1c; background: #fff2f2;'
            ' border: 1px solid #f2b8b8; border-radius: 6px; }')
        self.error_box.hide()
        lv.addWidget(self.error_box)
        lay.addWidget(left, 1)

        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(4, 4, 4, 4)
        self.plot = PlotWidget()
        rv.addWidget(self.plot, 1)
        lay.addWidget(right, 1)

    def begin_run(self):
        self.table.setRowCount(0)
        self.plot.clear()
        self.error_box.clear()
        self.error_box.hide()
        self.summary.setText('Измерений: 0')

    def add_meas(self, label, text, stamp):
        if label.startswith('БП'):
            device = 'БП'
        elif label.startswith('ММ'):
            device = 'ММ'
        else:
            device = '—'
        t = self.table
        r = t.rowCount()
        t.insertRow(r)
        for col, val in enumerate((stamp, device, label, text)):
            t.setItem(r, col, QtWidgets.QTableWidgetItem(val))
        t.scrollToBottom()
        # автоподстройка ширины колонок под содержимое
        t.resizeColumnsToContents()
        hh = t.horizontalHeader()
        hh.resizeSection(0, max(t.columnWidth(0), 90))
        hh.resizeSection(1, max(t.columnWidth(1), 55))
        hh.resizeSection(2, min(max(t.columnWidth(2), 150), 560))

    def add_point(self, var, label, x, y):
        self.plot.add_point(var, label, x, y)

    def add_error(self, text):
        self.error_box.appendPlainText(text)
        if not self.error_box.isVisible():
            self.error_box.show()

    def finish(self, ok, msg):
        n = self.table.rowCount()
        self.summary.setText(f'Измерений: {n} · программа {msg}')

    def save_results(self):
        """Сохраняет отчёт в папку output: CSV с измерениями и PNG графика."""
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        base = os.path.join(OUTPUT_DIR,
                            'report_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
        csv_path = base + '.csv'
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(['Время', 'Прибор', 'Измерение', 'Значение'])
            for r in range(self.table.rowCount()):
                w.writerow([self.table.item(r, c).text() if self.table.item(r, c) else ''
                            for c in range(4)])
            w.writerow([])
            w.writerow([self.summary.text()])
            errs = self.error_box.toPlainText().strip()
            if errs:
                w.writerow([])
                w.writerow(['ОШИБКИ'])
                for line in errs.splitlines():
                    w.writerow([line])
        png_path = base + '.png'
        self.plot.grab().save(png_path)
        self.summary.setText(
            f'Измерений: {self.table.rowCount()} · сохранено: {os.path.basename(csv_path)}'
            ' (+ график)')
        return csv_path, png_path


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Программа проверки приборов — колода карт')
        self.resize(1280, 800)
        self.sequence = []          # list[Card | ForLoop], слева направо
        self.selected = set()       # id выделенных карт
        self.anchor_id = None
        self.views = {}             # id -> виджет
        self.running = False
        self._run_thread = None
        self._idn_threads = {}
        self._hover_row = None      # строка под курсором при перетаскивании
        self._deck_hover = False    # курсор над колодой: «положить = удалить»
        self._rows = []             # все CardRowWidget (верхняя + тела циклов)
        self._mdrag = None          # ручное перетаскивание (карта «в руке»)
        self.constants = [{'name': 'Vcc', 'value': '3.3'}]   # общие константы
        self._completer_models = []   # модели подсказок (обновляются при правке констант)
        self._combo_editors = []      # редактируемые списки значений в параметрах
        self.log_messages = []      # (время, вид, текст) — вместо окна лога

        self._log_bridge = LogBridge()
        self._log_bridge.sig.connect(self.append_log)
        self._hw_handler = HwHandler(self._log_bridge)
        self._hw_handler.setLevel(logging.WARNING)
        logging.getLogger('hw').addHandler(self._hw_handler)

        self._build_toolbar()
        self._build_docks()
        self._build_status()
        self.report_dialog = RunReportDialog(self)
        self._apply_example()
        self.update_actions()

    # ---------------------------------------------------------------- UI
    def _build_toolbar(self):
        tb = self.addToolBar('main')
        tb.setMovable(False)

        self.act_loop = QAction('⟳ Цикл', self)
        self.act_loop.triggered.connect(self.wrap_in_loop)
        self.act_save = QAction('💾 Сохранить', self)
        self.act_save.triggered.connect(self.save_dialog)
        self.act_open = QAction('📂 Открыть', self)
        self.act_open.triggered.connect(self.open_dialog)

        tb.addAction(self.act_loop)
        tb.addSeparator()
        tb.addAction(self.act_save)
        tb.addAction(self.act_open)

    def _build_docks(self):
        self._build_connection_panel()   # self.conn_box — в левую панель

        # --- константы и подключение (слева) ---
        self.left_dock = QtWidgets.QDockWidget('Константы и подключение', self)
        self.left_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
        left_child = QtWidgets.QWidget()
        left_lay = QtWidgets.QVBoxLayout(left_child)
        left_lay.setSpacing(8)
        left_lay.addWidget(self._build_constants_panel())
        left_lay.addWidget(self.conn_box)
        left_lay.addStretch(1)
        self.left_dock.setWidget(self._vscroll(left_child))
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        # --- колода (снизу у стола): у каждого прибора свои стопки ---
        self.deck_dock = QtWidgets.QDockWidget('Колода', self)
        self.deck_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
        deck_child = QtWidgets.QWidget()
        deck_lay = QtWidgets.QHBoxLayout(deck_child)
        deck_lay.setContentsMargins(8, 4, 8, 4)
        deck_lay.setSpacing(20)
        self.deck_buttons = []
        for gtitle, stacks in DECK_GROUPS:
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(3)
            cap = QtWidgets.QLabel(f'<b>{gtitle}</b>')
            cap.setStyleSheet('color: #6b7280;')
            col.addWidget(cap)
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            for card_type, stack_title, device in stacks:
                st = StackWidget(card_type, stack_title, device, self)
                st.setFixedSize(StackWidget.W, StackWidget.H)
                st.setToolTip(describe(new_card(card_type)))
                row.addWidget(st)
                self.deck_buttons.append(st)
            col.addLayout(row)
            col.addStretch(1)
            wrap = QtWidgets.QWidget()
            wrap.setLayout(col)
            deck_lay.addWidget(wrap)
        deck_lay.addStretch(1)
        # колода тоже скроллится колесом, если окно узкое
        self._deck_area = QtWidgets.QScrollArea()
        self._deck_area.setWidgetResizable(True)
        self._deck_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._deck_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._deck_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._deck_area.setWidget(deck_child)
        self.deck_dock.setWidget(self._deck_area)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.deck_dock)
        self.resizeDocks([self.deck_dock], [210], QtCore.Qt.Orientation.Vertical)

        # --- параметры (справа): только выбранная карта / цикл ---
        self.params_dock = QtWidgets.QDockWidget('Параметры', self)
        self.params_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
        params_child = QtWidgets.QWidget()
        self.params_lay = QtWidgets.QVBoxLayout(params_child)
        self.params_lay.setSpacing(8)
        self.params_dock.setWidget(self._vscroll(params_child))
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.params_dock)

        # --- лента программы (центр) ---
        self._strip_area = QtWidgets.QScrollArea()
        self._strip_area.setWidgetResizable(True)
        self._strip_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.strip = CardRowWidget(self, self.sequence)
        self._strip_area.setWidget(self.strip)
        self.setCentralWidget(self._strip_area)

        sc = QShortcut(
            QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Delete), self._strip_area)
        sc.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.delete_selection)
        sc_esc = QShortcut(QtGui.QKeySequence('Escape'), self._strip_area)
        sc_esc.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_esc.activated.connect(self.clear_selection)

        # --- колесо мыши: лента и колода крутятся по горизонтали ---
        self._wheel_viewports = {}
        for sa in (self._strip_area, self._deck_area):
            self._wheel_viewports[sa.viewport()] = sa
            sa.viewport().installEventFilter(self)
            sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _vscroll(self, widget):
        """Вертикальный скролл для панелей (колесо мыши работает нативно)."""
        sa = QtWidgets.QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(widget)
        return sa

    def eventFilter(self, obj, ev):
        # колесо мыши над лентой/колодой → горизонтальная прокрутка
        if (ev.type() == QtCore.QEvent.Type.Wheel
                and obj in getattr(self, '_wheel_viewports', {})):
            sa = self._wheel_viewports[obj]
            sb = sa.horizontalScrollBar()
            d = ev.angleDelta().x() or ev.angleDelta().y()
            if d and sb.maximum() > 0:
                sb.setValue(sb.value() - int(d))
                ev.accept()
                return True
        return super().eventFilter(obj, ev)

    def _build_connection_panel(self):
        """Панель подключения (модель + порт под каждый прибор) — слева."""
        box = QtWidgets.QGroupBox('Подключение')
        form = QtWidgets.QFormLayout(box)

        self.cb_ps = QtWidgets.QComboBox()
        self.cb_ps.addItems(PS_MODELS)
        self.cb_ps.setCurrentText(DEFAULT_PS['model'])
        self.ed_ps_port = QtWidgets.QLineEdit(DEFAULT_PS['port'])
        self.btn_ps_check = QtWidgets.QPushButton('Проверить (*IDN?)')
        self.btn_ps_check.clicked.connect(lambda: self.check_connection('ps'))
        form.addRow('БП (модель)', self.cb_ps)
        h1 = QtWidgets.QHBoxLayout()
        h1.addWidget(self.ed_ps_port)
        h1.addWidget(self.btn_ps_check)
        form.addRow('БП порт', h1)

        self.cb_mm = QtWidgets.QComboBox()
        self.cb_mm.addItems(MM_MODELS)
        self.cb_mm.setCurrentText(DEFAULT_MM['model'])
        self.ed_mm_port = QtWidgets.QLineEdit(DEFAULT_MM['port'])
        self.btn_mm_check = QtWidgets.QPushButton('Проверить (*IDN?)')
        self.btn_mm_check.clicked.connect(lambda: self.check_connection('mm'))
        form.addRow('ММ (модель)', self.cb_mm)
        h2 = QtWidgets.QHBoxLayout()
        h2.addWidget(self.ed_mm_port)
        h2.addWidget(self.btn_mm_check)
        form.addRow('ММ порт', h2)

        hint = QtWidgets.QLabel('Настроен стенд: БП Rigol DP832A + мультиметр AKIP-2101 '
                                '(VISA-адреса определены автоматически). '
                                'Порт test_float — виртуальный режим без железа.')
        hint.setWordWrap(True)
        form.addRow(hint)

        self.conn_box = box

    # ---------------------------------------------------------------- константы
    def _build_constants_panel(self):
        """Слева: общие константы (имя = значение), доступны в полях карт."""
        box = QtWidgets.QGroupBox('Константы')
        v = QtWidgets.QVBoxLayout(box)
        v.setSpacing(4)
        self._const_rows_lay = QtWidgets.QVBoxLayout()
        self._const_rows_lay.setSpacing(4)
        v.addLayout(self._const_rows_lay)
        btn_add = QtWidgets.QPushButton('+ Добавить константу')
        btn_add.clicked.connect(lambda: self._add_constant())
        v.addWidget(btn_add)
        hint = QtWidgets.QLabel('Имя константы можно писать в полях карт вместо числа, '
                                'напр. напряжение = Vcc')
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._render_constants()
        return box

    def _render_constants(self):
        self._purge_layout(self._const_rows_lay)
        for item in self.constants:
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            ed_name = QtWidgets.QLineEdit(item['name'])
            ed_name.setPlaceholderText('имя')
            ed_name.setFixedWidth(72)
            ed_val = QtWidgets.QLineEdit(item['value'])
            ed_val.setPlaceholderText('значение')
            eq = QtWidgets.QLabel('=')
            ed_name.textEdited.connect(lambda t, it=item: it.__setitem__('name', t))
            ed_val.textEdited.connect(lambda t, it=item: it.__setitem__('value', t))
            del_btn = QtWidgets.QPushButton('✕')
            del_btn.setFixedSize(22, 22)
            del_btn.clicked.connect(lambda _=False, it=item: self._del_constant(it))
            h.addWidget(ed_name)
            h.addWidget(eq)
            h.addWidget(ed_val, 1)
            h.addWidget(del_btn)
            self._const_rows_lay.addWidget(row)
        self._const_rows_lay.addStretch(1)
        self._refresh_completers()

    def _add_constant(self, name='', value=''):
        if self.running:
            return
        self.constants.append({'name': name, 'value': value})
        self._render_constants()

    def _del_constant(self, item):
        if self.running:
            return
        self.constants.remove(item)
        self._render_constants()

    def _refresh_completers(self):
        """Подсказки и списки во всех полях карт следят за списком констант."""
        names = set(self._constants_dict().keys())
        for model, extra in self._completer_models:
            model.setStringList(sorted(names | extra))
        for cb, extra in self._combo_editors:
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(sorted(names | extra))
            cb.setCurrentText(cur)
            cb.blockSignals(False)

    def _constants_dict(self):
        return {it['name'].strip(): it['value'].strip()
                for it in self.constants if it['name'].strip()}

    def _build_status(self):
        self.status = QtWidgets.QLabel('Готово')
        self.statusBar().addWidget(self.status, 1)
        # Пуск — в правом нижнем углу окна
        self.run_btn = QtWidgets.QPushButton('▶ Пуск')
        self.run_btn.setFixedSize(120, 30)
        self.run_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.run_btn.setStyleSheet("""
            QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #34c759, stop:1 #1e9e5a); color: white; font-weight: bold;
                border: 2px solid #166534; border-radius: 8px; font-size: 10pt; }
            QPushButton:hover { border-color: #F5B301; }
            QPushButton:disabled { background: #b3b3b3; border-color: #8a8a8a; }""")
        self.run_btn.clicked.connect(self.start_run)
        self.statusBar().addPermanentWidget(self.run_btn)

    def _apply_example(self):
        self.sequence[:] = [
            new_card('set'),
            new_card('on'),
            new_card('off'),
            new_card('delay'),
            new_card('meas'),
        ]
        self.rebuild_strip()
        self.rebuild_params()
        self.append_log('Пример программы создан. Возьмите карту из стопки колоды '
                        'мышью и выложите на ленту или в цикл.', 'info')

    # ---------------------------------------------------------------- лента
    def _make_view(self, item):
        if isinstance(item, ForLoop):
            v = LoopView(item, self)
            v.body.set_items([self._make_view(c) for c in item.children])
            self._rows.append(v.body)
        else:
            v = CardView(item, self)
        self.views[item.id] = v
        return v

    def rebuild_strip(self):
        self.views = {}
        self._rows = []
        self._hover_row = None
        top_views = [self._make_view(it) for it in self.sequence]
        self._rows.append(self.strip)
        self.strip.set_items(top_views)
        self.update_selection()

    # ---------------------------------------------------------------- выбор
    def is_selected(self, item_id):
        return item_id in self.selected

    def on_item_clicked(self, item_id, modifiers):
        ctrl = bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier)
        top_ids = [it.id for it in self.sequence]
        if shift and self.anchor_id in top_ids and item_id in top_ids:
            a, b = sorted((top_ids.index(self.anchor_id), top_ids.index(item_id)))
            self.selected = set(top_ids[a:b + 1])
        elif ctrl:
            if item_id in self.selected:
                self.selected.discard(item_id)
            else:
                self.selected.add(item_id)
            self.anchor_id = item_id
        else:
            self.selected = {item_id}
            self.anchor_id = item_id
        self.update_selection()
        self.rebuild_params()
        self.update_actions()

    def clear_selection(self):
        self.selected = set()
        self.update_selection()
        self.rebuild_params()
        self.update_actions()

    def update_selection(self):
        for _id, v in self.views.items():
            v.refresh_style()

    def selected_top_indexes(self):
        return sorted(i for i, it in enumerate(self.sequence) if it.id in self.selected)

    # ---------------------------------------------------------------- действия
    def add_card(self, card_type, device=None):
        """Клик по стопке колоды: карта добавляется в конец (ON авт. везёт OFF)."""
        self.add_card_at(self.sequence, len(self.sequence), card_type, device)
        sb = self._strip_area.horizontalScrollBar()
        sb.setValue(sb.maximum())

    def add_card_at(self, container, index, card_type, device=None):
        """Выкладывание карты в строку (drag-drop или клик).

        device — прибор для Meas-карты (из какой стопки взяли).
        При выкладывании ON рядом автоматически кладётся OFF.
        """
        if self.running:
            return
        cards = [new_card(card_type)]
        if card_type == 'on':
            cards.append(new_card('off'))
        if device and card_type == 'meas':
            for c in cards:
                c.params['device'] = device
        index = max(0, min(index, len(container)))
        for k, c in enumerate(cards):
            container.insert(index + k, c)
        self.selected = {cards[0].id}
        self.anchor_id = cards[0].id
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()

    def delete_selection(self):
        if self.running or not self.selected:
            return
        ids = expand_on_off_pairs(self.sequence, self.selected)   # ON/OFF — вместе
        n = remove_items(self.sequence, ids)
        self.selected = set()
        self.anchor_id = None
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()
        self.status.setText(f'Удалено карт: {n}')

    def duplicate_selected(self):
        if self.running or len(self.selected) != 1:
            return
        item_id = next(iter(self.selected))
        found = find_container(self.sequence, item_id)
        if not found:
            return
        lst, idx = found
        item = lst[idx]
        if isinstance(item, ForLoop):
            return
        import uuid as _uuid
        dup = copy.deepcopy(item)
        dup.id = _uuid.uuid4().hex[:8]
        lst.insert(idx + 1, dup)
        self.selected = {dup.id}
        self.anchor_id = dup.id
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()

    def move_selected(self, delta):
        if self.running or len(self.selected) != 1:
            self.status.setText('Перемещение — для одной выделенной карты')
            return
        found = find_container(self.sequence, next(iter(self.selected)))
        if not found:
            return
        lst, idx = found
        j = idx + delta
        if not 0 <= j < len(lst):
            return
        lst[idx], lst[j] = lst[j], lst[idx]
        self.rebuild_strip()
        self.update_actions()

    def move_item(self, item_id, target_list, index):
        """Перестановка при «выкладывании» карты (внутри строки или между строками)."""
        found = find_container(self.sequence, item_id)
        if not found:
            return
        lst, idx = found
        item = lst.pop(idx)
        index = max(0, min(index, len(target_list)))
        target_list.insert(index, item)
        self.selected = {item_id}
        self.anchor_id = item_id
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()

    # ---------------------------------------------------------------- ручной драг
    def _make_ghost(self, pixmap, gpos, offset):
        ghost = QtWidgets.QLabel(None, QtCore.Qt.WindowType.ToolTip
                                 | QtCore.Qt.WindowType.FramelessWindowHint
                                 | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        ghost.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        ghost.setPixmap(pixmap)
        ghost.setWindowOpacity(0.92)
        ghost.show()
        ghost.move(gpos - offset)
        return ghost

    def begin_move_drag(self, view, item_id, press_global):
        """Карту «взяли» с ленты/из цикла — она летит за курсором."""
        if self.running or self._mdrag is not None:
            return
        found = find_container(self.sequence, item_id)
        if not found:
            return
        lst, idx = found
        obj = lst[idx]
        offset = press_global - view.mapToGlobal(QtCore.QPoint(0, 0))
        state = {'kind': 'move', 'id': item_id, 'obj': obj,
                 'is_loop': isinstance(obj, ForLoop),
                 'source_view': view, 'source_row': view.parentWidget(),
                 'ghost': self._make_ghost(view.grab(), press_global, offset),
                 'offset': offset}
        self._mdrag = state
        src_row = state['source_row']
        if hasattr(src_row, 'prepare_drag'):
            src_row.prepare_drag(view)
        eff = QtWidgets.QGraphicsOpacityEffect(view)
        eff.setOpacity(0.35)
        view.setGraphicsEffect(eff)
        self.grabMouse()

    def begin_new_drag(self, btn, card_type, press_global, device=None):
        """Карту «взяли» из колоды — выкладываем на ленту/в цикл."""
        if self.running or self._mdrag is not None:
            return
        offset = press_global - btn.mapToGlobal(QtCore.QPoint(0, 0))
        offset = QtCore.QPoint(min(max(offset.x(), 0), CardView.W),
                               min(max(offset.y(), 0), CardView.H))
        state = {'kind': 'new', 'card_type': card_type, 'device': device,
                 'is_loop': False,
                 'ghost': self._make_ghost(btn._drag_pixmap(), press_global, offset),
                 'offset': offset}
        self._mdrag = state
        self.grabMouse()

    def _row_at(self, gpos):
        """Строка под курсором: тело цикла приоритетнее ленты — его рамка
        накрыта лентой, но точка внутри тела означает «внутрь цикла».
        Циклы нельзя вкладывать друг в друга."""
        cands = [r for r in self._rows
                 if r.isVisible() and r.rect().contains(r.mapFromGlobal(gpos))]
        if not cands:
            return None
        for row in cands:
            if row.container is not self.sequence:
                if not (self._mdrag and self._mdrag.get('is_loop')):
                    return row
        for row in cands:
            if row.container is self.sequence:
                return row
        return None

    def _move_drag(self, gpos):
        st = self._mdrag
        st['ghost'].move(gpos - st['offset'])
        # «положить обратно в колоду» = убрать из программы (карты с ленты)
        over_deck = st['kind'] == 'move' and self._deck_at(gpos)
        if over_deck != self._deck_hover:
            self._set_deck_hover(over_deck)
        if over_deck:
            if self._hover_row is not None:
                self._hover_row.clear_hover()
                self._hover_row = None
            return
        row = self._row_at(gpos)
        if row is not self._hover_row:
            if self._hover_row is not None:
                self._hover_row.clear_hover()
            self._hover_row = None
        if row is not None:
            self._hover_row = row
            row._set_hover(row.mapFromGlobal(gpos).x())

    def _end_drag(self, gpos, commit=True):
        st = self._mdrag
        # строку и индекс определяем ДО сброса состояния: правила
        # («цикл не вкладывается в цикл») учитывают текущий драг
        row = self._row_at(gpos) if commit else None
        idx = None
        if row is not None:
            idx = row._drag_index if row._drag_index is not None \
                else len(row._active_views())
        deck_drop = (row is None and commit
                     and st['kind'] == 'move' and self._deck_at(gpos))
        self._mdrag = None
        self.releaseMouse()
        st['ghost'].hide()
        st['ghost'].deleteLater()
        view = st.get('source_view')
        if view is not None:
            try:
                view.setGraphicsEffect(None)
                view.setVisible(True)
            except RuntimeError:
                pass
        for r in self._rows:
            r.finish_drag()
        self._hover_row = None
        if self._deck_hover:
            self._set_deck_hover(False)
        if row is None:
            if deck_drop:
                self._drop_delete(st)
            return
        if st['kind'] == 'new':
            self.add_card_at(row.container, idx, st['card_type'], st.get('device'))
        else:
            self.move_item(st['id'], row.container, idx)

    def _deck_at(self, gpos):
        """Курсор над зоной колоды (нижний док)?"""
        dock = self.deck_dock
        return dock.isVisible() and dock.rect().contains(dock.mapFromGlobal(gpos))

    def _set_deck_hover(self, on):
        """Подсветка колоды во время переноса: отпустить здесь = удалить карту."""
        self._deck_hover = on
        self.deck_dock.setStyleSheet(
            'QDockWidget::title { background: #dc2626; color: #ffffff; }' if on else '')
        self.status.setText('Отпустите карту над колодой — она будет удалена из программы'
                            if on else '')

    def _drop_delete(self, st):
        """Карту «положили обратно в колоду» — убрать из программы."""
        found = find_container(self.sequence, st['id'])
        if not found:
            return
        lst, idx = found
        item = lst[idx]
        if isinstance(item, ForLoop):
            # цикл в колоду не «кладётся»: разбираем, карты остаются на ленте
            self.selected = {st['id']}
            self.anchor_id = st['id']
            self.unwrap_loop()
            self.status.setText('Цикл разобран — карты остались на ленте')
            return
        ids = expand_on_off_pairs(self.sequence, {st['id']})   # ON/OFF — вместе
        n = remove_items(self.sequence, ids)
        for i in ids:
            self.selected.discard(i)
        self.anchor_id = None
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()
        self.status.setText(f'Карта убрана в колоду (удалено: {n})')
        self.append_log(f'Удалено перетаскиванием в колоду: {describe(item)}'
                        + (' (вместе с парой ON/OFF)' if n > 1 else ''), 'info')

    def mouseMoveEvent(self, ev):
        if self._mdrag is not None:
            self._move_drag(ev.globalPosition().toPoint())
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._mdrag is not None:
            self._end_drag(ev.globalPosition().toPoint(), commit=True)
            return
        super().mouseReleaseEvent(ev)

    # ---------------------------------------------------------------- циклы
    def wrap_in_loop(self):
        if self.running:
            return
        idxs = self.selected_top_indexes()
        if not idxs:
            QtWidgets.QMessageBox.information(
                self, 'Цикл', 'Выделите карты: клик, Ctrl+клик или Shift+клик.')
            return
        if len(idxs) != len(self.selected):
            QtWidgets.QMessageBox.warning(
                self, 'Цикл',
                'Обернуть в цикл можно только карты верхнего уровня.')
            return
        if idxs != list(range(idxs[0], idxs[-1] + 1)):
            QtWidgets.QMessageBox.warning(
                self, 'Цикл', 'Выделенные карты должны идти подряд.')
            return
        loop = ForLoop(mode='count', count='3')     # настройки — справа
        self._apply_wrap(idxs[0], idxs[-1], loop)

    def _apply_wrap(self, a, b, loop):
        loop.children = self.sequence[a:b + 1]
        self.sequence[a:b + 1] = [loop]
        # если внутри одна Set-карта — свип сразу привязывается к ней
        set_cards = collect_set_cards(loop.children)
        if len(set_cards) == 1:
            loop.target_id = set_cards[0].id
        self.selected = {loop.id}
        self.anchor_id = loop.id
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()
        self.append_log(f'Создан цикл: {loop_label(loop)} '
                        f'(карт внутри: {len(loop.children)}, настройки справа)', 'loop')

    def unwrap_loop(self):
        if self.running:
            return
        idxs = self.selected_top_indexes()
        if len(idxs) != 1 or not isinstance(self.sequence[idxs[0]], ForLoop):
            return
        loop = self.sequence.pop(idxs[0])
        self.sequence[idxs[0]:idxs[0]] = loop.children
        self.selected = {c.id for c in loop.children}
        self.anchor_id = next(iter(self.selected), None)
        self.rebuild_strip()
        self.rebuild_params()
        self.update_actions()
        self.append_log('Цикл разобран, карты сохранены', 'loop')

    # ---------------------------------------------------------------- параметры
    def rebuild_params(self):
        self._clear_params()

        items = [self._resolve(i) for i in self.selected]
        items = [it for it in items if it is not None]

        if not items:
            lab = QtWidgets.QLabel('Карта не выбрана.\n\nКликните карту в программе — '
                                   'здесь появятся её настройки.')
            lab.setWordWrap(True)
            self.params_lay.addWidget(lab)
        elif len(items) == 1 and isinstance(items[0], Card):
            self._build_card_params(items[0])
        elif len(items) == 1 and isinstance(items[0], ForLoop):
            self._build_loop_params(items[0])
        else:
            lab = QtWidgets.QLabel(f'Выделено карт: {len(items)}\n\n'
                                   '⟳ Цикл — обернуть выделенные подряд карты.')
            lab.setWordWrap(True)
            self.params_lay.addWidget(lab)
            for it in items[:12]:
                if isinstance(it, Card):
                    self.params_lay.addWidget(QtWidgets.QLabel('• ' + describe(it)))
        self.params_lay.addStretch(1)

    def _clear_params(self):
        lay = self.params_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                self._purge_layout(sub)
                sub.deleteLater()

    def _purge_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                self._purge_layout(sub)
                sub.deleteLater()

    def _resolve(self, item_id):
        found = find_container(self.sequence, item_id)
        return found[0][found[1]] if found else None

    def _enclosing_sweep(self, item_id):
        def walk(seq, in_sweep):
            for it in seq:
                if it.id == item_id:
                    return in_sweep
                if isinstance(it, ForLoop):
                    r = walk(it.children, in_sweep or it.mode == 'sweep')
                    if r:
                        return r
            return False
        return walk(self.sequence, False)

    def _value_editor(self, card, key, default, extra_options=()):
        """Поле значения: число или константа.

        Редактируемый выпадающий список: стрелка ▾ — кликабельный список
        констант, при вводе — подсказки. Для канала в списке ещё и 1/2/3.
        """
        names = sorted(set(self._constants_dict().keys()) | set(extra_options))
        cb = QtWidgets.QComboBox()
        cb.setEditable(True)
        cb.addItems(names)
        cb.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        cb.setCurrentText(str(card.params.get(key, default)))
        model = QtCore.QStringListModel(names)
        comp = QtWidgets.QCompleter(model)
        comp.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        cb.setCompleter(comp)
        self._completer_models.append((model, set(extra_options)))
        self._combo_editors.append((cb, set(extra_options)))
        cb.currentTextChanged.connect(
            lambda text, k=key, c=card: self._param_changed(c, k, text))
        return cb

    def _build_card_params(self, card):
        spec = CATALOG[card.type]
        lab = QtWidgets.QLabel(f'<b>{spec["title"]}</b> · {card_device_label(card)}')
        lab.setWordWrap(True)
        self.params_lay.addWidget(lab)
        is_meas = card.type == 'meas'
        device = card.params.get('device', 'ps') if is_meas else 'ps'
        form = QtWidgets.QFormLayout()
        for f in spec['fields']:
            key = f['key']
            if is_meas and key == 'kind':
                continue                      # режим добавим отдельно (зависит от прибора)
            if is_meas and key == 'device':
                cb = QtWidgets.QComboBox()
                for val, lab_opt in f['options']:
                    cb.addItem(lab_opt, val)
                cb.setCurrentIndex(max(0, cb.findData(str(card.params.get(key, 'ps')))))
                cb.currentTextChanged.connect(
                    lambda _t, cb=cb, c=card: self._meas_device_changed(c, cb.currentData()))
                form.addRow(f['label'], cb)
                continue
            if is_meas and key == 'channel' and device != 'ps':
                continue                      # канал есть только у БП
            if f.get('options'):
                cb = QtWidgets.QComboBox()
                for val, lab_opt in f['options']:
                    cb.addItem(lab_opt, val)
                cb.setCurrentIndex(max(0, cb.findData(str(card.params.get(key, f['default'])))))
                cb.currentTextChanged.connect(
                    lambda _t, cb=cb, k=key, c=card:
                    self._param_changed(c, k, cb.currentData()))
                form.addRow(f['label'], cb)
            else:
                # число или константа: выпадающий список + подсказки
                # (в канале ещё и 1/2/3)
                extra = ('1', '2', '3') if key == 'channel' else ()
                cb = self._value_editor(card, key, f['default'], extra)
                form.addRow(f['label'], cb)
        if is_meas:
            # режим Meas — опции зависят от выбранного прибора
            cb = QtWidgets.QComboBox()
            for val, lab_opt in meas_kind_options(device):
                cb.addItem(lab_opt, val)
            cb.setCurrentIndex(max(0, cb.findData(str(card.params.get('kind', 'voltage')))))
            cb.currentTextChanged.connect(
                lambda _t, cb=cb, c=card: self._param_changed(c, 'kind', cb.currentData()))
            form.addRow('Режим', cb)
        self.params_lay.addLayout(form)
        hint = QtWidgets.QLabel('Значение может быть числом или константой (слева); '
                                '▾ — выбрать константу из списка.')
        hint.setWordWrap(True)
        self.params_lay.addWidget(hint)
        if card.type == 'set' and self._enclosing_sweep(card.id):
            hint2 = QtWidgets.QLabel('Эта Set-карта внутри свипа: значение подставляет '
                                     'цикл (От/До/Шаг в его настройках).')
            hint2.setWordWrap(True)
            self.params_lay.addWidget(hint2)

    def _meas_device_changed(self, card, device):
        """У Meas-карты сменили прибор: пересобрать режимы и канал."""
        card.params['device'] = device
        valid = [v for v, _ in meas_kind_options(device)]
        if card.params.get('kind') not in valid:
            card.params['kind'] = valid[0]
        self.rebuild_params()

    def _param_changed(self, card, key, text):
        card.params[key] = text
        v = self.views.get(card.id)
        if v is not None:
            v.refresh_body()

    def _build_loop_params(self, loop):
        set_cards = collect_set_cards(loop.children)
        head = QtWidgets.QLabel(
            f'<b>Цикл</b> · карт внутри: {len(loop.children)} · Set-карт: {len(set_cards)}')
        head.setWordWrap(True)
        self.params_lay.addWidget(head)

        rb_count = QtWidgets.QRadioButton('Повторить N раз')
        rb_sweep = QtWidgets.QRadioButton('Свипирование (ведёт Set-карты)')
        rb_sweep.setEnabled(bool(set_cards))
        if not set_cards:
            rb_sweep.setToolTip('Свипирование недоступно: внутри цикла нет Set-карт (Set)')
        self.params_lay.addWidget(rb_count)
        self.params_lay.addWidget(rb_sweep)

        form_c = QtWidgets.QFormLayout()
        ed_count = QtWidgets.QLineEdit(str(loop.count))
        form_c.addRow('N =', ed_count)
        self.params_lay.addLayout(form_c)

        form_s = QtWidgets.QFormLayout()
        ed_start = QtWidgets.QLineEdit(str(loop.start))
        ed_stop = QtWidgets.QLineEdit(str(loop.stop))
        ed_step = QtWidgets.QLineEdit(str(loop.step))
        form_s.addRow('От', ed_start)
        form_s.addRow('До', ed_stop)
        form_s.addRow('Шаг', ed_step)
        # какую Set-карту ведёт свип — выбор из списка Set-карт внутри цикла
        if set_cards:
            cb_target = QtWidgets.QComboBox()
            for sc in set_cards:
                cb_target.addItem(summarize(sc), sc.id)
            i = cb_target.findData(loop.target_id)
            if i >= 0:
                cb_target.setCurrentIndex(i)
            else:
                loop.target_id = set_cards[0].id
            cb_target.currentIndexChanged.connect(
                lambda _i, l=loop, cb=cb_target:
                setattr(l, 'target_id', cb.currentData() or ''))
            form_s.addRow('Свипируемая карта', cb_target)
        self.params_lay.addLayout(form_s)

        hint = QtWidgets.QLabel('Свип сам подставляет значения во все Set-карты внутри '
                                'цикла; Meas-карты попадают на график (X — свип).')
        hint.setWordWrap(True)
        self.params_lay.addWidget(hint)

        def refresh():
            v = self.views.get(loop.id)
            if v is not None:
                v.set_label()
                v.updateGeometry()

        def sync():
            loop.mode = 'count' if rb_count.isChecked() else 'sweep'
            ed_count.setEnabled(rb_count.isChecked())
            for w in (ed_start, ed_stop, ed_step):
                w.setEnabled(rb_sweep.isChecked() and rb_sweep.isEnabled())
            refresh()

        def bind(ed, attr):
            ed.textEdited.connect(lambda t, l=loop, a=attr: (setattr(l, a, t), refresh()))

        rb_count.toggled.connect(lambda _on: sync())
        bind(ed_count, 'count')
        bind(ed_start, 'start')
        bind(ed_stop, 'stop')
        bind(ed_step, 'step')

        if loop.mode == 'sweep' and rb_sweep.isEnabled():
            rb_sweep.setChecked(True)
        else:
            rb_count.setChecked(True)
        sync()

        btn_unwrap = QtWidgets.QPushButton('Разобрать цикл')
        btn_unwrap.clicked.connect(self.unwrap_loop)
        self.params_lay.addWidget(btn_unwrap)
        btn_del = QtWidgets.QPushButton('Удалить')
        btn_del.clicked.connect(self.delete_selection)
        self.params_lay.addWidget(btn_del)

    def connection_settings(self):
        return {
            'ps': {'model': self.cb_ps.currentText(), 'port': self.ed_ps_port.text()},
            'mm': {'model': self.cb_mm.currentText(), 'port': self.ed_mm_port.text()},
        }

    def apply_settings(self, settings):
        ps = settings.get('ps', {})
        mm = settings.get('mm', {})
        i = self.cb_ps.findText(ps.get('model', ''))
        if i >= 0:
            self.cb_ps.setCurrentIndex(i)
        self.ed_ps_port.setText(ps.get('port', DEFAULT_PS['port']))
        i = self.cb_mm.findText(mm.get('model', ''))
        if i >= 0:
            self.cb_mm.setCurrentIndex(i)
        self.ed_mm_port.setText(mm.get('port', DEFAULT_MM['port']))

    # ---------------------------------------------------------------- проверка IDN
    def check_connection(self, group):
        if self.running or group in self._idn_threads:
            return
        if group == 'ps':
            model, port, btn = self.cb_ps.currentText(), self.ed_ps_port.text(), self.btn_ps_check
        else:
            model, port, btn = self.cb_mm.currentText(), self.ed_mm_port.text(), self.btn_mm_check
        btn.setEnabled(False)
        th = IdnThread(group, model, port)
        th.sig_log.connect(self.append_log)
        th.sig_done.connect(lambda _g, _r: btn.setEnabled(True))
        self._idn_threads[group] = th
        th.finished.connect(lambda g=group: self._idn_threads.pop(g, None))
        th.start()

    # ---------------------------------------------------------------- запуск
    def start_run(self):
        if self.running or not self.sequence:
            return
        seq_copy = copy.deepcopy(self.sequence)
        self._run_thread = RunThread(seq_copy, self.connection_settings(),
                                     self._constants_dict())
        self._run_thread.sig_log.connect(self.append_log)
        self._run_thread.sig_done.connect(self._run_finished)
        self._run_thread.sig_point.connect(self.report_dialog.add_point)
        self._run_thread.sig_meas.connect(self.report_dialog.add_meas)
        self.running = True
        self._set_ui_running(True)
        # всплывающее окно отчёта: таблица + график + ошибки
        self.report_dialog.begin_run()
        self.report_dialog.show()
        self.report_dialog.raise_()
        self.append_log('── Запуск программы ──', 'loop')
        self._run_thread.start()

    def _set_ui_running(self, on):
        for a in (self.act_loop, self.act_save, self.act_open):
            a.setEnabled(not on)
        self.run_btn.setEnabled(not on)
        for b in self.deck_buttons:
            b.setEnabled(not on)
        self.btn_ps_check.setEnabled(not on)
        self.btn_mm_check.setEnabled(not on)
        if on:
            self.status.setText('Выполняется программа…')
        else:
            self.status.setText('Готово')

    def _run_finished(self, ok, msg):
        self.running = False
        self._set_ui_running(False)
        self.append_log(f'Программа {msg}', 'ok' if ok else 'warn')
        self.status.setText('Готово' if ok else 'Программа прервана')
        self.report_dialog.finish(ok, msg)
    # ---------------------------------------------------------------- файлы
    def save_dialog(self):
        if self.running:
            return
        os.makedirs(PRESETS_DIR, exist_ok=True)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Сохранить программу',
            os.path.join(PRESETS_DIR, 'program.json'), 'JSON (*.json)')
        if not path:
            return
        try:
            save_program(path, self.sequence, self.connection_settings(),
                         self.constants)
            self.append_log(f'Программа сохранена: {path}', 'ok')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Сохранение', str(e))

    def open_dialog(self):
        if self.running:
            return
        os.makedirs(PRESETS_DIR, exist_ok=True)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Открыть программу', PRESETS_DIR, 'JSON (*.json)')
        if not path:
            return
        try:
            seq, settings, constants = load_program(path)
            self.sequence[:] = seq
            self.apply_settings(settings)
            self.constants = constants
            self._render_constants()
            self.selected = set()
            self.rebuild_strip()
            self.rebuild_params()
            self.update_actions()
            self.append_log(f'Программа загружена: {path} ({len(self.sequence)} элем.)', 'ok')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Открытие', f'Не удалось открыть: {e}')

    # ---------------------------------------------------------------- лог → статус/отчёт
    def append_log(self, text, kind='info'):
        """Окна лога нет: последняя строка — в статус, история — в память,
        ошибки — в окно отчёта."""
        stamp = datetime.now().strftime('%H:%M:%S')
        self.log_messages.append((stamp, kind, str(text)))
        if len(self.log_messages) > 400:
            del self.log_messages[:-400]
        self.status.setText(str(text))
        self.status.setStyleSheet(f'color: {KIND_COLORS.get(kind, "#111827")};')
        if kind == 'error' and hasattr(self, 'report_dialog'):
            self.report_dialog.add_error(text)

    # ---------------------------------------------------------------- actions
    def update_actions(self):
        self.run_btn.setEnabled(not self.running and bool(self.sequence))
        self.act_loop.setEnabled(
            not self.running and bool(self.selected_top_indexes()))
        self.act_save.setEnabled(not self.running)
        self.act_open.setEnabled(not self.running)

    def closeEvent(self, ev):
        if self._run_thread is not None and self._run_thread.isRunning():
            self._run_thread.request_stop()
            self._run_thread.wait(5000)
        self.report_dialog.close()
        logging.getLogger('hw').removeHandler(self._hw_handler)
        super().closeEvent(ev)


# ---------------------------------------------------------------- лог-мост
class LogBridge(QtCore.QObject):
    sig = Signal(str, str)


class HwHandler(logging.Handler):
    """Логи библиотеки lib_visa (логгер 'hw') → статус/память."""

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))

    def emit(self, record):
        try:
            self.bridge.sig.emit(self.format(record), 'hw')
        except Exception:
            pass
