# -*- coding: utf-8 -*-
"""Smoke-тест GUI без экрана (QT_QPA_PLATFORM=offscreen).

Проверяет: стопки колоды (клик + ON авт. OFF), свип по Set-картам, точки на
графике, переключение прибора у Meas-карты, сохранение/загрузку JSON с
миграцией старых карт, разбор цикла, ручной драг из колоды.

Запуск:  python tests/test_gui_smoke.py
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from card_tester.qt import QtCore, QtGui, QtWidgets
from card_tester.main_window import MainWindow, StackWidget
from card_tester.cards import ForLoop, new_card
from card_tester.program_io import save_program, load_program

app = QtWidgets.QApplication([])
win = MainWindow()
win.show()
app.processEvents()

# --- 0. колода: стопки по приборам + вертикальные карты ---
assert [(s.card_type, s.device) for s in win.deck_buttons] == [
    ('set', 'ps'), ('meas', 'ps'), ('on', 'ps'), ('meas', 'mm'), ('delay', 'sys')]
assert all(isinstance(s, StackWidget) for s in win.deck_buttons)
cv = win.views[win.sequence[0].id]
assert (cv.width(), cv.height()) == (150, 210), 'карта вертикальная, как КК'

# --- 1. клик по стопкам: карты добавляются; ON автоматически везёт OFF ---
win.sequence[:] = []
win.rebuild_strip()
win.add_card('set')
win.add_card('meas')
assert len(win.sequence) == 2
win.add_card('on')
assert len(win.sequence) == 4, 'ON кладётся вместе с OFF'
assert win.sequence[2].type == 'on' and win.sequence[3].type == 'off'
win.selected = {win.sequence[2].id, win.sequence[3].id}
win.anchor_id = win.sequence[2].id
win.delete_selection()
assert len(win.sequence) == 2

# --- 2. у Meas-карты переключается прибор, режимы подстраиваются ---
meas = win.sequence[1]
win.selected = {meas.id}
win.anchor_id = meas.id
win.rebuild_params()
assert meas.params['device'] == 'ps' and meas.params['kind'] == 'voltage'
win._meas_device_changed(meas, 'mm')
assert meas.params['device'] == 'mm' and meas.params['kind'] == 'voltage_dc', \
    (meas.params['device'], meas.params['kind'])
win._meas_device_changed(meas, 'ps')
assert meas.params['kind'] == 'voltage'

# --- 2b. подсказки констант в полях Set-карты ---
set_card = win.sequence[0]
win.selected = {set_card.id}
win.anchor_id = set_card.id
win.rebuild_params()
assert win._completer_models, 'комплитер создан для полей Set-карты'
chan_model = win._completer_models[0][0]
chan_list = chan_model.stringList()
assert 'Vcc' in chan_list and '1' in chan_list and '2' in chan_list, chan_list
assert win._combo_editors and win._combo_editors[0][0].isEditable(), 'поле — кликабельный выпадающий список'

# --- 3. свип по Set-картам: цикл сам ведёт Set, точки на графике ---
win.selected = {win.sequence[0].id, win.sequence[1].id}
win.anchor_id = win.sequence[0].id
win._apply_wrap(0, 1, ForLoop(mode='sweep', start='1', stop='2', step='1'))
assert isinstance(win.sequence[0], ForLoop) and len(win.sequence) == 1
loop = win.sequence[0]
lv = win.views[loop.id]
assert lv.caption.text().startswith('⟳ свип'), lv.caption.text()
assert loop.target_id == loop.children[0].id, 'свип привязан к Set-карте'
assert 'qlineargradient' in lv.styleSheet() and 'dashed' not in lv.styleSheet()
assert not hasattr(win, 'plot_dock'), 'дока графика больше нет'
assert not win.report_dialog.isVisible(), 'до запуска окна отчёта нет'
win.start_run()
deadline = time.time() + 60
while win.running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert not win.running, 'программа завершилась'
pts = win.report_dialog.plot.series.get('БП ch1: измерить напряжение', [])
assert len(pts) == 2, pts
assert abs(pts[0][0] - 1.0) < 1e-6 and abs(pts[1][0] - 2.0) < 1e-6
assert win.report_dialog.plot.x_name == 'V (свип), В'
assert win.report_dialog.isVisible(), 'окно отчёта открылось'
texts = [t for _s, _k, t in win.log_messages]
assert 'Программа готово' in '\n'.join(texts)
assert not hasattr(win, 'log_view'), 'окна лога больше нет'

# --- 3b. отчёт измерений: таблица с временем замера ---
t = win.report_dialog.table
assert t.rowCount() == 2, t.rowCount()
import re as _re
for r in range(2):
    stamp = t.item(r, 0).text()
    assert _re.fullmatch(r'\d\d:\d\d:\d\d\.\d\d\d', stamp), stamp
    assert t.item(r, 1).text() == 'БП'
    assert 'измерить напряжение' in t.item(r, 2).text()
    assert t.item(r, 3).text().endswith('В')
assert 'Измерений: 2' in win.report_dialog.summary.text()

# --- 3c. сохранение результатов в папку output ---
csv_path, png_path = win.report_dialog.save_results()
assert os.path.exists(csv_path) and os.path.exists(png_path), (csv_path, png_path)
content = open(csv_path, encoding='utf-8-sig').read()
assert 'измерить напряжение' in content and 'Время' in content
assert os.path.dirname(csv_path).endswith('output')
assert win.report_dialog.table.columnWidth(2) >= 150, 'ширина колонки подстроилась'

# --- 4. сохранение/загрузка (константы + новые типы) ---
path = os.path.join(tempfile.gettempdir(), 'card_tester_smoke.json')
save_program(path, win.sequence, win.connection_settings(),
             [{'name': 'Vcc', 'value': '3.3'}])
seq2, st2, consts = load_program(path)
assert seq2[0].mode == 'sweep' and seq2[0].children[0].type == 'set'
assert seq2[0].children[1].type == 'meas' and seq2[0].children[1].params['device'] == 'ps'
assert consts[0]['name'] == 'Vcc' and consts[0]['value'] == '3.3'
os.remove(path)

# --- 5. миграция старых карт всех версий ---
old_path = os.path.join(tempfile.gettempdir(), 'card_tester_old.json')
with open(old_path, 'w', encoding='utf-8') as f:
    json.dump({
        'version': 1, 'connection': {},
        'sequence': [
            {'card': 'ps_set_voltage', 'params': {'channel': '1', 'voltage': '2.5'}},
            {'card': 'mm_meas_vdc', 'params': {}},
            {'card': 'ps_meas_i', 'params': {'channel': '2'}},
            {'card': 'ps_set', 'params': {'kind': 'current', 'channel': '1', 'value': '0.5'}},
            {'card': 'ps_on', 'params': {'channel': '1'}},
        ],
    }, f)
seq_old, _st, _c = load_program(old_path)
os.remove(old_path)
assert seq_old[0].type == 'set' and seq_old[0].params['kind'] == 'voltage'
assert seq_old[0].params['value'] == '2.5'
assert seq_old[1].type == 'meas' and seq_old[1].params['device'] == 'mm'
assert seq_old[1].params['kind'] == 'voltage_dc'
assert seq_old[2].type == 'meas' and seq_old[2].params['device'] == 'ps'
assert seq_old[2].params['kind'] == 'current'
assert seq_old[3].type == 'set' and seq_old[3].params['kind'] == 'current'
assert seq_old[4].type == 'on'

# --- 6. разбор цикла ---
win.selected = {win.sequence[0].id}
win.anchor_id = win.sequence[0].id
win.unwrap_loop()
assert len(win.sequence) == 2 and not isinstance(win.sequence[0], ForLoop)

# --- 7. ручной драг: взял карту из стопки — выложил на ленту ---
win.sequence[:] = []
win.rebuild_strip()
g = win.strip.mapToGlobal(win.strip.rect().center())
stack = next(s for s in win.deck_buttons if s.card_type == 'delay')
win.begin_new_drag(stack, 'delay', g)
assert win._mdrag is not None and win._mdrag['kind'] == 'new'
win._move_drag(g)
app.processEvents()
win._end_drag(g, commit=True)
app.processEvents()
assert win._mdrag is None
assert len(win.sequence) == 1 and win.sequence[0].type == 'delay', 'карта выложена на ленту'

# --- 8. цикл не блокирует карты: цикл нельзя вложить в цикл ---
win.add_card('set')
ids = [it.id for it in win.sequence]
win.selected = set(ids)
win.anchor_id = ids[0]
win._apply_wrap(0, 1, ForLoop(mode='count', count='3'))
loop2 = win.sequence[0]
lv2 = win.views[loop2.id]
g2 = lv2.body.mapToGlobal(lv2.body.rect().center())
win.begin_move_drag(lv2, loop2.id, g2)
assert win._mdrag is not None and win._mdrag['is_loop']
win._move_drag(g2)   # курсор над телом цикла
app.processEvents()
assert win._hover_row is win.strip, 'тело цикла для цикла недоступно — только лента'
win._end_drag(g2, commit=True)
assert isinstance(win.sequence[0], ForLoop), 'цикл остался на месте'

# --- 8b. карту можно ВТЯНУТЬ в цикл (тело цикла приоритетнее ленты) ---
win.sequence[:] = []
win.rebuild_strip()
win.add_card('set')
win.add_card('delay')
ids = [it.id for it in win.sequence]
win.selected = {ids[0]}
win.anchor_id = ids[0]
win._apply_wrap(0, 0, ForLoop(mode='count', count='3'))
loop3 = win.sequence[0]
delay_card = win.sequence[1]
delay_view = win.views[delay_card.id]
body3 = win.views[loop3.id].body
g3 = body3.mapToGlobal(body3.rect().center())
win.begin_move_drag(delay_view, delay_card.id, g3)
win._move_drag(g3)
app.processEvents()
assert win._hover_row is body3, 'курсор над телом цикла — строка должна быть телом'
win._end_drag(g3, commit=True)
assert delay_card in loop3.children, 'карта втянута в цикл'
assert len(loop3.children) == 2 and len(win.sequence) == 1
# и обратно: вытянуть из цикла на ленту
delay_view = win.views[delay_card.id]
body3 = win.views[loop3.id].body
g4 = delay_view.mapToGlobal(delay_view.rect().center())
win.begin_move_drag(delay_view, delay_card.id, g4)
g_top = win.strip.mapToGlobal(QtCore.QPoint(400, 30))
win._move_drag(g_top)
app.processEvents()
assert win._hover_row is win.strip
win._end_drag(g_top, commit=True)
assert delay_card in win.sequence and delay_card not in loop3.children, \
    'карта вытянута из цикла'

# --- 8c. клик по карте в цикле настраивает КАРТУ; клик по зоне — ЦИКЛ ---
def press(w, local):
    g = w.mapToGlobal(local)
    ev = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress,
                           QtCore.QPointF(local), QtCore.QPointF(g),
                           QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.KeyboardModifier())
    w.mousePressEvent(ev)

card_in_loop = loop3.children[0]
card_view = win.views[card_in_loop.id]
zone = win.views[loop3.id]
press(card_view, QtCore.QPoint(30, 30))
assert win.selected == {card_in_loop.id}, \
    'клик по карте в цикле выделяет именно карту'
assert win._resolve(next(iter(win.selected))) is card_in_loop
press(zone, QtCore.QPoint(5, 5))
assert win.selected == {loop3.id}, 'клик по жёлтой зоне выделяет цикл'

# --- 8d. карту с ленты можно «положить в колоду» — удалится ---
win.sequence[:] = []
win.rebuild_strip()
win.add_card('set')
win.add_card('delay')
assert len(win.sequence) == 2
del_card = win.sequence[1]
del_view = win.views[del_card.id]
g5 = del_view.mapToGlobal(del_view.rect().center())
win.begin_move_drag(del_view, del_card.id, g5)
g_deck = win.deck_dock.mapToGlobal(win.deck_dock.rect().center())
win._move_drag(g_deck)
app.processEvents()
assert win._deck_hover, 'колода подсвечена при наведении с картой'
assert win._hover_row is None, 'прорезь вставки над колодой не показывается'
win._end_drag(g_deck, commit=True)
app.processEvents()
assert win._mdrag is None
assert len(win.sequence) == 1 and win.sequence[0] is not del_card, \
    'карта удалена сбросом в колоду'
assert not win._deck_hover, 'подсветка колоды сброшена после удаления'
# цикл в колоду = разобрать (карты остаются)
win._apply_wrap(0, 0, ForLoop(mode='count', count='2'))
loop4 = win.sequence[0]
lv4 = win.views[loop4.id]
g6 = lv4.body.mapToGlobal(lv4.body.rect().center())
win.begin_move_drag(lv4, loop4.id, g6)
win._move_drag(g_deck)
app.processEvents()
win._end_drag(g_deck, commit=True)
app.processEvents()
assert not isinstance(win.sequence[0], ForLoop) and len(win.sequence) == 1, \
    'сброс цикла в колоду разбирает цикл, карты остаются'

# --- 9. карты не накладываются: соседние рамки не пересекаются ---
def no_overlap(row):
    views = [v for v in row._views if v is not row._drag_view]
    for a, b in zip(views, views[1:]):
        ga, gb = a.geometry(), b.geometry()
        assert ga.right() < gb.left(), f'наложение карт: {ga} vs {gb}'

win.sequence[:] = [new_card('set'), new_card('on'), new_card('off'),
                   new_card('delay'), new_card('meas')]
win.selected = {win.sequence[0].id, win.sequence[1].id}
win.anchor_id = win.sequence[0].id
win._apply_wrap(0, 1, ForLoop(mode='count', count='3'))
app.processEvents()
no_overlap(win.strip)
for it in win.sequence:
    if isinstance(it, ForLoop):
        body = win.views[it.id].body
        no_overlap(body)
        for v in body._views:
            assert v.x() + v.width() <= win.views[it.id].width() + 1, \
                'карта вылезает за ширину цикла'

# --- 10. ON/OFF удаляются вместе ---
win.sequence[:] = [new_card('set'), new_card('on'), new_card('off'),
                   new_card('meas')]
win.rebuild_strip()
on_id, off_id = win.sequence[1].id, win.sequence[2].id
win.selected = {on_id}
win.anchor_id = on_id
win.delete_selection()
assert [it.type for it in win.sequence] == ['set', 'meas'], \
    'OFF удалилась вместе с ON'
# удаление OFF тоже забирает ON
win.sequence[:] = [new_card('set'), new_card('on'), new_card('off'),
                   new_card('meas')]
win.rebuild_strip()
win.selected = {win.sequence[2].id}
win.anchor_id = win.sequence[2].id
win.delete_selection()
assert [it.type for it in win.sequence] == ['set', 'meas'], \
    'ON удалилась вместе с OFF'
# разведённые ON и OFF удаляются независимо
win.sequence[:] = [new_card('on'), new_card('set'), new_card('off')]
win.rebuild_strip()
win.selected = {win.sequence[0].id}
win.anchor_id = win.sequence[0].id
win.delete_selection()
assert [it.type for it in win.sequence] == ['set', 'off'], \
    'разведённая пара удаляется независимо'

# --- 11. колесо мыши листает ленту по горизонтали ---
win.sequence[:] = [new_card(t) for t in ('set', 'on', 'off', 'delay', 'meas',
                                         'set', 'meas', 'delay')]
win.rebuild_strip()
for _ in range(5):
    app.processEvents()
sb = win._strip_area.horizontalScrollBar()
assert sb.maximum() > 0, 'лента шире окна — есть что скроллить'
v0 = sb.value()
wheel = QtGui.QWheelEvent(QtCore.QPointF(10, 10), QtCore.QPointF(100, 100),
                          QtCore.QPoint(0, 0), QtCore.QPoint(0, -120),
                          QtCore.Qt.MouseButton.NoButton,
                          QtCore.Qt.KeyboardModifier(),
                          QtCore.Qt.ScrollPhase.NoScrollPhase, False)
assert win.eventFilter(win._strip_area.viewport(), wheel) is True
assert sb.value() > v0, 'колесо вниз — лента вправо'
wheel2 = QtGui.QWheelEvent(QtCore.QPointF(10, 10), QtCore.QPointF(100, 100),
                           QtCore.QPoint(0, 0), QtCore.QPoint(0, 120),
                           QtCore.Qt.MouseButton.NoButton,
                           QtCore.Qt.KeyboardModifier(),
                           QtCore.Qt.ScrollPhase.NoScrollPhase, False)
assert win.eventFilter(win._strip_area.viewport(), wheel2) is True
assert sb.value() < sb.maximum(), 'колесо вверх — лента назад'

# --- 12. ошибки попадают в окно отчёта ---
win.sequence[:] = [new_card('set')]
win.rebuild_strip()
win.sequence[0].params['value'] = 'abc'   # не число — будет ошибка
win.start_run()
deadline = time.time() + 60
while win.running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert not win.running
assert win.report_dialog.isVisible(), 'окно отчёта при ошибке тоже открыто'
assert win.report_dialog.error_box.isVisible(), 'поле ошибок показано'
assert 'не число' in win.report_dialog.error_box.toPlainText()
assert win.report_dialog.table.rowCount() == 0, 'до ошибки Meas нет'

# --- 13. Сохранить/Открыть работают через кнопки (диалог подменяется) ---
import card_tester.main_window as _mw
os.makedirs(_mw.PRESETS_DIR, exist_ok=True)
p_save = os.path.join(_mw.PRESETS_DIR, 'smoke_test.json')
QtWidgets.QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (p_save, 'JSON (*.json)'))
win.sequence[:] = [new_card('set'), new_card('delay')]
win.rebuild_strip()
win.save_dialog()
assert os.path.exists(p_save), '💾 сохранил файл в presets'
QtWidgets.QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (p_save, 'JSON (*.json)'))
win.sequence[:] = []
win.rebuild_strip()
win.open_dialog()
assert [it.type for it in win.sequence] == ['set', 'delay'],     '📂 восстанавливает программу (карты)'
assert win.constants, '📂 восстанавливает константы'
assert win.connection_settings()['ps']['port'], '📂 восстанавливает подключение'
os.remove(p_save)

print('GUI SMOKE TEST PASSED')
