# -*- coding: utf-8 -*-
"""Smoke-тест GUI без экрана (QT_QPA_PLATFORM=offscreen).

Проверяет: стопки колоды (клик + ON авт. OFF), свип по Set-картам, точки на
графике, фиксацию прибора у Meas-карты, сохранение/загрузку JSON с
миграцией старых карт, разбор цикла, ручной драг из колоды и в колоду.

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

# без железа: коробки на виртуальные порты (реальные USB-адреса стенда
# требуют pyusb, которого в тестовом окружении может не быть)
for b in win.devices:
    b.port = 'test_float'

# --- 0. колода: стопки по приборам + вертикальные карты ---
assert [(s.card_type, s.box.kind if s.box else 'sys') for s in win.deck_buttons] == [
    ('set', 'ps'), ('meas', 'ps'), ('on', 'ps'), ('meas', 'mm'), ('delay', 'sys'),
    ('sweep', 'sys')]
assert all(isinstance(s, StackWidget) for s in win.deck_buttons)
cv = win.views[win.sequence[0].id]
assert (cv.width(), cv.height()) == (150, 210), 'карта вертикальная, как КК'

# --- 1. клик по стопкам: карты добавляются; ON автоматически везёт OFF ---
win.sequence[:] = []
win.rebuild_strip()
win.add_card('set', box=win.devices[0])
win.add_card('meas', box=win.devices[0])
assert len(win.sequence) == 2
win.add_card('on', box=win.devices[0])
assert len(win.sequence) == 4, 'ON кладётся вместе с OFF'
assert win.sequence[2].type == 'on' and win.sequence[3].type == 'off'
win.selected = {win.sequence[2].id, win.sequence[3].id}
win.anchor_id = win.sequence[2].id
win.delete_selection()
assert len(win.sequence) == 2

# --- 2. прибор Meas-карты привязан к коробке стопки колоды ---
meas = win.sequence[1]                      # карта из стопки БП
win.selected = {meas.id}
win.anchor_id = meas.id
win.rebuild_params()
assert meas.params['device'] == win.devices[0].id and meas.params['kind'] == 'voltage'
mm_meas = new_card('meas', win.devices[1])  # из стопки «Мультиметр»
assert mm_meas.params['device'] == win.devices[1].id, 'Meas из ММ — всегда ММ'
assert mm_meas.params['kind'] == 'voltage_dc', mm_meas.params

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

# --- 3. свип по Set-картам: цикл сам ведёт Set, точки на графике уровня ---
win.selected = {win.sequence[0].id, win.sequence[1].id}
win.anchor_id = win.sequence[0].id
win._apply_wrap(win.sequence, 0, 1, ForLoop(mode='sweep', start='1', stop='2', step='1'))
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
rd = win.report_dialog
assert len(rd.plots) == 1, 'один свип — один график'
pts = rd.plots[0].series.get('БП ch1: измерить напряжение', [])
assert len(pts) == 2, pts
assert abs(pts[0][0] - 1.0) < 1e-6 and abs(pts[1][0] - 2.0) < 1e-6
assert rd.plots[0].x_name == 'V (свип), В'
assert rd.tabs.tabText(0) == 'Свип 1 · V (свип), В', rd.tabs.tabText(0)
assert rd.isVisible(), 'окно отчёта открылось'
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
csv_path, pngs = win.report_dialog.save_results()
assert os.path.exists(csv_path) and len(pngs) == 1 and os.path.exists(pngs[0]), \
    (csv_path, pngs)
content = open(csv_path, encoding='utf-8-sig').read()
assert 'измерить напряжение' in content and 'Время' in content
assert os.path.dirname(csv_path).endswith('output')
assert win.report_dialog.table.columnWidth(2) >= 150, 'ширина колонки подстроилась'

# --- 3d. вложенные свипы: у каждого уровня своя Set-карта и свой график ---
from card_tester.cards import count_sweeps, sweep_candidates
win.sequence[:] = []
win.rebuild_strip()
ps_box = win.devices[0]
set_a, set_b = new_card('set', ps_box), new_card('set', ps_box)
meas_in, meas_out = new_card('meas', ps_box), new_card('meas', ps_box)
inner = ForLoop(mode='sweep', start='1', stop='2', step='1',
                children=[set_b, meas_in])
outer = ForLoop(mode='sweep', start='1', stop='2', step='1',
                children=[set_a, inner, meas_out])
win.sequence[:] = [outer]
win.rebuild_strip()
assert count_sweeps(win.sequence) == 2, 'два уровня свипирования'
# свободные Set-карты: карты, занятые вложенными свипами, внешнему не достаются
assert sweep_candidates(outer) == [set_a]
assert sweep_candidates(inner) == [set_b]
win.selected = {outer.id}
win.anchor_id = outer.id
win.rebuild_params()          # настройки цикла привязывают Set-карту уровня
assert outer.target_id == set_a.id, 'внешний свип ведёт свою Set-карту'
win.selected = {inner.id}
win.anchor_id = inner.id
win.rebuild_params()
assert inner.target_id == set_b.id, 'внутренний свип ведёт свою Set-карту'
win.selected = set()
win.start_run()
deadline = time.time() + 90
while win.running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert not win.running, 'вложенная программа завершилась'
rd = win.report_dialog
assert len(rd.plots) == 2, 'графиков — по числу свипов'
lbl = 'БП ch1: измерить напряжение'
outer_pts = rd.plots[0].series.get(lbl, [])
inner_pts = rd.plots[1].series.get(lbl, [])
assert len(outer_pts) == 2, (outer_pts, 'внешний график — Meas внешнего уровня')
assert [p[0] for p in outer_pts] == [1.0, 2.0]
assert len(inner_pts) == 4, (inner_pts, 'внутренний график — 2×2 точки')
assert rd.tabs.count() == 2 and rd.right.isVisible()
csv3, pngs3 = rd.save_results()
assert len(pngs3) == 2 and all(os.path.exists(p) for p in pngs3), pngs3

# --- 3e. свип без Set-карты — не свип: числа свипов и графиков считают Set ---
win.sequence[:] = []
win.rebuild_strip()
win.sequence[:] = [ForLoop(mode='sweep', start='1', stop='3', step='1',
                           children=[new_card('meas', ps_box)])]   # Meas внутри, Set нет
win.rebuild_strip()
assert count_sweeps(win.sequence) == 0, 'свип без Set-карты не считается свипом'
win.start_run()
deadline = time.time() + 60
while win.running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert not win.running
rd = win.report_dialog
assert rd.plots == [] and not rd.right.isVisible(), 'свип без Set — графика нет'
assert rd.table.rowCount() == 0, 'свип пропущен, Meas внутри не выполнялась'
assert 'Свип недоступен' in '\n'.join(t for _s, _k, t in win.log_messages)

# --- 3f. сценарий сохранённой программы: все Set внутри самого вложенного
# из трёх циклов — каждому свипу достаётся своя Set-карта ---
def find_radio(prefix):
    """Радио-кнопка в панели параметров по началу подписи."""
    def scan(lay):
        for i in range(lay.count()):
            it = lay.itemAt(i)
            w = it.widget()
            if isinstance(w, QtWidgets.QRadioButton) and w.text().startswith(prefix):
                return w
            sub = it.layout()
            if sub is not None:
                r = scan(sub)
                if r is not None:
                    return r
        return None
    return scan(win.params_lay)

win.sequence[:] = []
win.rebuild_strip()
s1, s2, s3 = (new_card('set', ps_box), new_card('set', ps_box),
              new_card('set', ps_box))
s2.params['channel'] = '2'
s3.params['channel'] = '3'
m3 = new_card('meas', ps_box)
l3 = ForLoop(mode='sweep', start='1', stop='2', step='1',
             target_id=s1.id, children=[s1, s2, s3, m3])
l2 = ForLoop(mode='count', start='1', stop='2', step='1', children=[l3])
l1 = ForLoop(mode='count', start='1', stop='2', step='1', children=[l2])
win.sequence[:] = [l1]
win.rebuild_strip()
assert count_sweeps(win.sequence) == 1
# средний цикл: свип ДОСТУПЕН, хотя Set-карты лежат внутри вложенного свипа
win.selected = {l2.id}
win.anchor_id = l2.id
win.rebuild_params()
assert l2.target_id == s2.id, 'свипу досталась первая свободная Set-карта'
rb2 = find_radio('Свипирование')
assert rb2 is not None and rb2.isEnabled(), 'свип доступен для среднего цикла'
rb2.setChecked(True)
app.processEvents()
assert l2.mode == 'sweep', 'радио-кнопка включила свип'
# внешний цикл: осталась последняя свободная карта
win.selected = {l1.id}
win.anchor_id = l1.id
win.rebuild_params()
assert l1.target_id == s3.id, 'внешнему свипу — последняя свободная Set-карта'
rb1 = find_radio('Свипирование')
assert rb1 is not None and rb1.isEnabled(), 'свип доступен для внешнего цикла'
rb1.setChecked(True)
app.processEvents()
assert count_sweeps(win.sequence) == 3, 'три свипа — три уровня свипирования'
win.selected = set()
win.start_run()
deadline = time.time() + 120
while win.running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert not win.running, 'программа из трёх свипов завершилась'
rd = win.report_dialog
assert len(rd.plots) == 3, 'графиков по числу свипов'
assert rd.plots[0].series == {} and rd.plots[1].series == {}, \
    'Meas одна и внутри самого вложенного свипа'
pts3 = rd.plots[2].series.get('БП ch1: измерить напряжение', [])
assert len(pts3) == 8, (pts3, 'внутренний график: 2×2×2 точек')
texts3 = '\n'.join(t for _s, _k, t in win.log_messages)
assert 'карта внутри вложенного свипа' in texts3, \
    'внешние свипы применяют свои карты сами'
assert 'ch3: задать напряжение = 2 В' in texts3
assert 'ch2: задать напряжение = 2 В' in texts3

# возвращаем вложенную программу — дальше с ней работают секции 4 и 6
win.sequence[:] = [outer]
win.rebuild_strip()

# --- 4. сохранение/загрузка вложенной программы (константы + новые типы) ---
path = os.path.join(tempfile.gettempdir(), 'card_tester_smoke.json')
save_program(path, win.sequence, win.devices,
             [{'name': 'Vcc', 'value': '3.3'}])
seq2, st2, consts = load_program(path)
outer2 = seq2[0]
assert outer2.mode == 'sweep' and outer2.children[0].type == 'set'
inner2 = outer2.children[1]
assert isinstance(inner2, ForLoop) and inner2.mode == 'sweep', 'цикл в цикле сохранён'
assert inner2.children[0].type == 'set' and inner2.children[1].type == 'meas'
assert outer2.children[2].type == 'meas' and outer2.children[2].params['device'] == ps_box.id
assert outer2.target_id == outer2.children[0].id, 'привязка свипа пережила save/load'
assert inner2.target_id == inner2.children[0].id
assert count_sweeps(seq2) == 2
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

# --- 6. разбор циклов на любом уровне ---
win.selected = {win.sequence[0].id}
win.anchor_id = win.sequence[0].id
win.unwrap_loop()
# внешний разобран: [set, вложенный цикл(set, meas), meas]
assert len(win.sequence) == 3 and isinstance(win.sequence[1], ForLoop), \
    'внешний разобран, вложенный остался'
win.selected = {win.sequence[1].id}
win.anchor_id = win.sequence[1].id
win.unwrap_loop()
assert len(win.sequence) == 4 and not any(isinstance(it, ForLoop)
                                          for it in win.sequence), \
    'вложенный цикл тоже разбирается, все карты на ленте'

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
# прибор карты — из стопки, из которой её взяли (драг)
stack_mm = next(s for s in win.deck_buttons
                if s.box is not None and s.box.kind == 'mm')
win.begin_new_drag(stack_mm, stack_mm.card_type, g, box=stack_mm.box)
win._move_drag(g)
app.processEvents()
win._end_drag(g, commit=True)
meas_dragged = next(c for c in win.sequence if c.type == 'meas')
assert meas_dragged.params['device'] == stack_mm.box.id, \
    'Meas, взятая драгом из стопки Мультиметр, — прибор ММ'
assert meas_dragged.params['kind'] == 'voltage_dc', \
    'режим сразу корректный для ММ'
# убираем тестовую карту, чтобы не влиять на следующие секции
win.selected = {meas_dragged.id}
win.anchor_id = meas_dragged.id
win.delete_selection()
assert len(win.sequence) == 1, 'тестовая Meas удалена'

# --- 8. цикл в цикле: в чужой цикл вложить можно, в свой — нельзя ---
win.sequence[:] = []
win.rebuild_strip()
win.add_card('set', box=win.devices[0])
win.add_card('set', box=win.devices[0])
card1 = win.sequence[0]
win.selected = {card1.id}
win.anchor_id = card1.id
win._apply_wrap(win.sequence, 0, 0, ForLoop(mode='count', count='2'))
outer_l = win.sequence[0]
win.selected = {win.sequence[1].id}
win.anchor_id = win.sequence[1].id
win._apply_wrap(win.sequence, 1, 1, ForLoop(mode='count', count='3'))
inner_l = win.sequence[1]
iv, ov = win.views[inner_l.id], win.views[outer_l.id]
g_in = ov.body.mapToGlobal(ov.body.rect().center())
win.begin_move_drag(iv, inner_l.id, g_in)
assert win._mdrag is not None and win._mdrag['is_loop']
win._move_drag(g_in)   # курсор над телом ДРУГОГО цикла
app.processEvents()
assert win._hover_row is ov.body, 'чужое тело цикла доступно для цикла'
win._end_drag(g_in, commit=True)
assert inner_l in outer_l.children and len(win.sequence) == 1, \
    'цикл вложен в цикл'
# в своё тело (и тела своих вложенных циклов) вкладываться нельзя
ov = win.views[outer_l.id]
g_self = ov.body.mapToGlobal(ov.body.rect().center())
win.begin_move_drag(ov, outer_l.id, g_self)
win._move_drag(g_self)
app.processEvents()
assert win._hover_row is win.strip, 'своё тело для цикла недоступно'
win._end_drag(g_self, commit=True)
assert isinstance(win.sequence[0], ForLoop) \
    and {c.id for c in outer_l.children} == {card1.id, inner_l.id}, \
    'цикл остался на ленте с прежним содержимым'

# --- 8b. карту можно ВТЯНУТЬ в цикл (тело цикла приоритетнее ленты) ---
win.sequence[:] = []
win.rebuild_strip()
win.add_card('set', box=win.devices[0])
win.add_card('delay')
ids = [it.id for it in win.sequence]
win.selected = {ids[0]}
win.anchor_id = ids[0]
win._apply_wrap(win.sequence, 0, 0, ForLoop(mode='count', count='3'))
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
win.add_card('set', box=win.devices[0])
win.add_card('delay')
assert len(win.sequence) == 2
del_card = win.sequence[1]
del_view = win.views[del_card.id]
g5 = del_view.mapToGlobal(del_view.rect().center())
win.begin_move_drag(del_view, del_card.id, g5)
g_deck = win.deck_dock.mapToGlobal(win.deck_dock.rect().center())
pm0 = win._mdrag['ghost'].pixmap().toImage()
win._move_drag(g_deck)
app.processEvents()
assert win._deck_hover, 'курсор над колодой при переносе карты'
assert win._mdrag['ghost'].pixmap().toImage() != pm0, 'летящая карта покраснела'
assert win._hover_row is None, 'прорезь вставки над колодой не показывается'
win._end_drag(g_deck, commit=True)
app.processEvents()
assert win._mdrag is None
assert len(win.sequence) == 1 and win.sequence[0] is not del_card, \
    'карта удалена сбросом в колоду'
assert not win._deck_hover, 'подсветка колоды сброшена после удаления'
# цикл в колоду = разобрать (карты остаются)
win._apply_wrap(win.sequence, 0, 0, ForLoop(mode='count', count='2'))
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
win._apply_wrap(win.sequence, 0, 1, ForLoop(mode='count', count='3'))
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
win.sequence[:] = [new_card('set', ps_box)]
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
assert win.report_dialog.plots == [] and not win.report_dialog.right.isVisible(), \
    'свипов нет — графиков нет'

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
assert any(cs['port'] for cs in win.connection_settings().values()), '📂 восстанавливает подключение'
os.remove(p_save)

# --- 14. свип-карта: жёлтая, три отсека, дроп по правилам отсеков ---
# дальше гоняем на виртуальных приборах, чтобы не трогать стенд
next(b for b in win.devices if b.kind == 'ps').port = 'test_float'
next(b for b in win.devices if b.kind == 'mm').port = 'test_float'

from card_tester.main_window import SweepView
from card_tester.cards import SweepCard, sweep_units

win.sequence[:] = []
win.rebuild_strip()
win.add_card('sweep')
sw = win.sequence[0]
assert isinstance(sw, SweepCard)
sv = win.views[sw.id]
assert isinstance(sv, SweepView), 'у свип-карты свой вид с отсеками'
assert sv.row_x.sweep_role == 'x' and sv.row_mid.sweep_role == 'mid' \
    and sv.row_y.sweep_role == 'y'
assert sv.caption.text().startswith('⟲ свип')
# раскладка: отсеки — отдельные строки в _rows (тела циклов внутри — раньше)
assert sv.row_x in win._rows and sv.row_mid in win._rows and sv.row_y in win._rows

def drop_into(row, item_id, dx=0):
    """Перетаскивание карты item_id в строку row (все виды берутся свежие:
    любой дроп пересобирает ленту). dx — смещение точки от центра отсека."""
    local = row.rect().center() + QtCore.QPoint(dx, 0)
    g = row.mapToGlobal(local)
    win.begin_move_drag(win.views[item_id], item_id, g)
    win._move_drag(g)
    app.processEvents()
    win._end_drag(g, commit=True)
    app.processEvents()

# Set-карта → в X: принимается
set_x = new_card('set', ps_box)
win.sequence.append(set_x)
win.rebuild_strip()
drop_into(win.views[sw.id].row_x, set_x.id)
assert sw.x_cards == [set_x], 'Set-карта легла в отсек X'
# пустой и заполненный одной картой свипы одного размера: пустой отсек
# вмещает карту, дальше свип может только расти (но не сжиматься)
win.add_card('sweep')
sw_empty = win.sequence[-1]
assert win.views[sw.id].minimumSizeHint() \
    == win.views[sw_empty.id].minimumSizeHint() \
    and win.views[sw.id].sizeHint() == win.views[sw_empty.id].sizeHint(), \
    'пустой и заполненный свипы одного размера'
win.selected = {sw_empty.id}
win.anchor_id = sw_empty.id
win.delete_selection()
assert win.sequence[-1] is not sw_empty and sw in win.sequence, 'пустой свип удалён'
# вторая Set-карта в X — нельзя (ровно одна): остаётся на ленте
set_2 = new_card('set')
win.sequence.append(set_2)
win.rebuild_strip()
drop_into(win.views[sw.id].row_x, set_2.id)
assert sw.x_cards == [set_x] and set_2 in win.sequence, 'в X только одна карта'
# Set-карта в Y — нельзя
drop_into(win.views[sw.id].row_y, set_2.id)
assert sw.y_cards == [] and set_2 in win.sequence, 'Y принимает только Meas'
# две Meas → в Y, каждая — своя линия (БП и ММ — разные подписи)
mm_box = next(b for b in win.devices if b.kind == 'mm')
meas_y1, meas_y2 = new_card('meas', ps_box), new_card('meas', mm_box)
win.sequence += [meas_y1, meas_y2]
win.rebuild_strip()
drop_into(win.views[sw.id].row_y, meas_y1.id)
drop_into(win.views[sw.id].row_y, meas_y2.id, dx=30)   # правее карты — в конец
assert sw.y_cards == [meas_y1, meas_y2], 'обе Meas в отсеке Y'
# delay → в середину
delay_m = new_card('delay')
win.sequence.append(delay_m)
win.rebuild_strip()
drop_into(win.views[sw.id].row_mid, delay_m.id)
assert sw.mid_cards == [delay_m], 'delay в середине'
# свип-карту в собственные отсеки положить нельзя
sv = win.views[sw.id]
g_self = sv.row_mid.mapToGlobal(sv.row_mid.rect().center())
win.begin_move_drag(sv, sw.id, g_self)
win._move_drag(g_self)
app.processEvents()
assert win._hover_row is win.strip, 'свой отсек для свип-карты недоступен'
win._end_drag(g_self, commit=True)
# убираем лишнюю Set-карту с ленты
win.selected = {set_2.id}
win.anchor_id = set_2.id
win.delete_selection()
assert win.sequence == [sw], 'на ленте только свип-карта'

# --- 15. свип-карта: запуск на виртуальных приборах — график с линиями Y ---
sw.start, sw.stop, sw.step = '1', '2', '1'
win.views[sw.id].set_label()
assert 'свип 1 → 2' in win.views[sw.id].caption.text()
win.selected = {sw.id}
win.anchor_id = sw.id
win.rebuild_params()
assert 'Свип' in win.params_lay.itemAt(0).widget().text(), 'настройки свипа справа'
win.selected = set()
assert sweep_units(win.sequence) == [('card', sw.id)]
win.start_run()
deadline = time.time() + 60
while win.running and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert not win.running, 'программа со свип-картой завершилась'
rd = win.report_dialog
assert len(rd.plots) == 1, 'одна свип-карта — один график'
lbl_v = 'БП ch1: измерить напряжение'
lbl_mm = 'ММ: измерить V DC'
assert len(rd.plots[0].series.get(lbl_v, [])) == 2, 'точки линии БП'
assert len(rd.plots[0].series.get(lbl_mm, [])) == 2, 'точки линии ММ'
assert [p[0] for p in rd.plots[0].series[lbl_v]] == [1.0, 2.0]
assert rd.plots[0].x_name == 'V (свип), В'
assert rd.table.rowCount() == 4, 'все Meas в отчёте (2 точки × 2 линии)'
texts14 = '\n'.join(t for _s, _k, t in win.log_messages)
assert 'СВИП 1 → 2' in texts14 and 'линий Y: 2' in texts14, 'заголовок свипа'
assert 'задать напряжение = 2 В' in texts14, 'X ведётся свип-картой'

# --- 16. сохранение/загрузка свип-карты ---
path = os.path.join(tempfile.gettempdir(), 'card_tester_sweep.json')
save_program(path, win.sequence, win.devices, [])
seq_sw, _st, _c = load_program(path)
os.remove(path)
sw2 = seq_sw[0]
assert isinstance(sw2, SweepCard)
assert (sw2.start, sw2.stop, sw2.step) == ('1', '2', '1')
assert len(sw2.x_cards) == 1 and sw2.x_cards[0].type == 'set'
assert [c.type for c in sw2.y_cards] == ['meas', 'meas']
assert [c.type for c in sw2.mid_cards] == ['delay']
assert sweep_units(seq_sw) == [('card', sw2.id)]

# --- 17. разбор свип-карты: карты отсеков возвращаются на ленту ---
win.selected = {sw.id}
win.anchor_id = sw.id
win.unwrap_sweep()
assert not isinstance(win.sequence[0], SweepCard), 'свип разобран'
types = [it.type for it in win.sequence]
assert types.count('set') == 1 and types.count('delay') == 1 \
    and types.count('meas') == 2, 'карты отсеков на ленте'

print('GUI SMOKE TEST PASSED')
