# -*- coding: utf-8 -*-
"""Прогон программы проверки на виртуальных приборах, без GUI и железа.

Запуск:  python tests/test_runner.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from card_tester.cards import (Card, ForLoop, SweepCard, count_sweeps,
                               resolve_sweeps, sweep_units)
from card_tester.runner import execute_program

LOG = []
POINTS = []      # (уровень свипа, ось X, x, подпись, y)
RESULTS = []


def log(text, kind='info'):
    LOG.append((kind, text))
    print(f'[{kind:5s}] {text}')


def on_meas(level, var, x, label, y):
    POINTS.append((level, var, x, label, y))


def on_result(label, text, stamp):
    RESULTS.append((label, text, stamp))


def main():
    settings = {
        'ps': {'kind': 'ps', 'model': 'DP832A', 'port': 'test_float'},
        'mm': {'kind': 'mm', 'model': 'DM3068', 'port': 'test_float'},
    }
    constants = {'Vcc': '3.3'}

    # Свип: одна Set-карта внутри — свип ведёт её даже без явного выбора
    sweep_loop = ForLoop(mode='sweep', start='1', stop='3', step='1', children=[
        Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '1', 'value': '9.9'}),
        Card('delay', {'seconds': '0.2'}),
        Card('meas', {'device': 'ps', 'kind': 'voltage', 'channel': '1'}),
    ])
    # Свип с выбором Set-карты: ведётся только целевая (V), ток не трогается
    target_card = Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '1', 'value': '9.9'})
    other_card = Card('set', {'device': 'ps', 'kind': 'current', 'channel': '2', 'value': '0.25'})
    pick_loop = ForLoop(mode='sweep', start='1', stop='2', step='1',
                        target_id=target_card.id, children=[target_card, other_card])
    count_loop = ForLoop(mode='count', count='2', children=[
        Card('meas', {'device': 'mm', 'kind': 'voltage_dc'}),
        Card('delay', {'seconds': '0.1'}),
    ])
    sequence = [sweep_loop, pick_loop, count_loop,
                Card('set', {'device': 'ps', 'kind': 'current', 'channel': '1', 'value': '0.5'}),
                Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '3', 'value': 'Vcc'})]

    ok = execute_program(sequence, settings, log, lambda: False,
                         constants, on_meas, on_result)

    text = '\n'.join(t for _k, t in LOG)
    labels = [lbl for _lv, _v, _x, lbl, _y in POINTS]
    checks = [
        ('итоги ok', ok),
        ('СВИП 1 → 3', 'СВИП 1 → 3' in text),
        ('точки свипа', '— точка 3/3: 3' in text),
        ('график: 3 точки', len(POINTS) == 3),
        ('график: ось X', all(v == 'V (свип), В' for _lv, v, *_ in POINTS)),
        ('график: уровень 0', all(lv == 0 for lv, *_ in POINTS)),
        ('график: x = 1..3', [x for _lv, _v, x, _l, _y in POINTS] == [1.0, 2.0, 3.0]),
        ('график: подпись Meas', all('измерить напряжение' in l for l in labels)),
        ('отчёт: все Meas (5)', len(RESULTS) == 5),
        ('отчёт: время замера', all(
            __import__('re').fullmatch(r'\d\d:\d\d:\d\d\.\d\d\d', s)
            for _l, _t, s in RESULTS)),
        ('отчёт: подписи', any('измерить напряжение' in l for l, *_ in RESULTS)
         and any('измерить V DC' in l for l, *_ in RESULTS)),
        ('отчёт: значения', all(t for _l, t, _s in RESULTS)),
        ('выбор Set-карты для свипа', text.count('задать напряжение = 2 В') == 2),
        ('не-целевая не тронута', 'задать ток = 0.25 А' in text
         and 'задать ток = 2 А' not in text),
        ('повтор × 2', 'повтор × 2' in text),
        ('Set ток', 'задать ток = 0.5 А' in text),
        ('константа Vcc', 'задать напряжение = 3.3 В' in text),
        ('приборы отключены', 'приборы отключены' in text),
    ]

    # --- вложенные свипы: у каждого уровня своя Set-карта и свои точки ---
    LOG.clear()
    POINTS.clear()
    RESULTS.clear()
    set_a, set_b = (Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '1', 'value': '9.9'}),
                    Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '2', 'value': '9.9'}))
    inner = ForLoop(mode='sweep', start='1', stop='2', step='1',
                    children=[set_b,
                              Card('meas', {'device': 'ps', 'kind': 'voltage',
                                            'channel': '2'})])
    outer = ForLoop(mode='sweep', start='1', stop='2', step='1',
                    children=[set_a, inner,
                              Card('meas', {'device': 'ps', 'kind': 'voltage',
                                            'channel': '1'})])
    ok2 = execute_program([outer], settings, log, lambda: False,
                          constants, on_meas, on_result)
    text2 = '\n'.join(t for _k, t in LOG)
    lvl0 = [p for p in POINTS if p[0] == 0]
    lvl1 = [p for p in POINTS if p[0] == 1]
    checks += [
        ('вложенный: итоги ok', ok2),
        # заголовок свипа: внешний 1 раз + внутренний на каждой точке внешнего (2)
        ('вложенный: оба свипа в логе', text2.count('СВИП 1 → 2') == 3),
        # каждая Set-карта ведётся только своим свипом:
        ('вложенный: внешняя Set своя', text2.count('ch1: задать напряжение = 2 В') == 1),
        ('вложенный: внутренняя Set своя',
         # 2 точки + 1 раз в заголовке внутреннего свипа (значение с прошлого прохода)
         text2.count('ch2: задать напряжение = 2 В') == 3),
        ('вложенный: точки уровня 0', [x for _lv, _v, x, *_ in lvl0] == [1.0, 2.0]),
        ('вложенный: точки уровня 1 (2×2)',
         [x for _lv, _v, x, *_ in lvl1] == [1.0, 2.0, 1.0, 2.0]),
        # число свипов определяют Set-карты (свипируемые параметры), не Meas
        ('число свипов = по Set-картам', count_sweeps([outer]) == 2),
        ('свип без Set-карты — не свип',
         count_sweeps([ForLoop(mode='sweep', start='1', stop='3', step='1',
                               children=[Card('meas', {'device': 'ps'})])]) == 0),
    ]

    # --- раздача Set-карт: все Set внутри самого вложенного из трёх свипов
    # (сценарий сохранённой программы) — каждый свип получает свою переменную,
    # и переменные внешних свипов не перезаписываются внутренними ---
    LOG.clear()
    POINTS.clear()
    RESULTS.clear()
    s1 = Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '1', 'value': '9.9'})
    s2 = Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '2', 'value': '9.9'})
    s3 = Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '3', 'value': '9.9'})
    m3 = Card('meas', {'device': 'ps', 'kind': 'voltage', 'channel': '1'})
    l3 = ForLoop(mode='sweep', start='1', stop='2', step='1',
                 target_id=s1.id, children=[s1, s2, s3, m3])
    l2 = ForLoop(mode='sweep', start='1', stop='2', step='1', children=[l3])
    l1 = ForLoop(mode='sweep', start='1', stop='2', step='1', children=[l2])
    owners = resolve_sweeps([l1])
    ok3 = execute_program([l1], settings, log, lambda: False,
                          constants, on_meas, on_result)
    text3 = '\n'.join(t for _k, t in LOG)
    checks += [
        ('раздача: внешний → ch3', owners[l1.id] is s3),
        ('раздача: средний → ch2', owners[l2.id] is s2),
        ('раздача: внутренний → ch1', owners[l3.id] is s1),
        ('три свипа — три уровня', count_sweeps([l1]) == 3),
        ('итоги ok (3 уровня)', ok3),
        ('3 уровня: 2×2×2 = 8 точек', len(POINTS) == 8),
        ('все точки уровня 2', all(p[0] == 2 for p in POINTS)),
        ('переменные не перезаписаны статичными значениями',
         # 9.9 (исходное значение карт) встречается только в заголовках свипов,
         # ни одного шага с ним быть не должно
         all(line.lstrip().startswith('⟳')
             for line in text3.splitlines() if '9.9 В' in line)),
        ('внешние свипы применяют свои карты',
         'ch3: задать напряжение = 2 В' in text3
         and 'ch2: задать напряжение = 2 В' in text3),
    ]

    # --- свип-карта: X — Set (величина оси X), Y — две Meas (две линии),
    # середина — delay на каждой точке; уровни: свип-карта 0, цикл-свип 1 ---
    LOG.clear()
    POINTS.clear()
    RESULTS.clear()
    sw = SweepCard(start='1', stop='3', step='1')
    sw.x_cards.append(Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '1', 'value': '9.9'}))
    sw.mid_cards.append(Card('delay', {'seconds': '0.05'}))
    sw.y_cards += [Card('meas', {'device': 'ps', 'kind': 'voltage', 'channel': '1'}),
                   Card('meas', {'device': 'mm', 'kind': 'voltage_dc'})]
    loop_set = Card('set', {'device': 'ps', 'kind': 'voltage', 'channel': '2', 'value': '9.9'})
    loop_meas = Card('meas', {'device': 'ps', 'kind': 'voltage', 'channel': '2'})
    sw_seq = [sw, ForLoop(mode='sweep', start='1', stop='2', step='1',
                          children=[loop_set, loop_meas])]
    units = sweep_units(sw_seq)
    ok4 = execute_program(sw_seq, settings, log, lambda: False,
                          constants, on_meas, on_result)
    text4 = '\n'.join(t for _k, t in LOG)
    card_pts = [p for p in POINTS if p[0] == 0]
    loop_pts = [p for p in POINTS if p[0] == 1]
    lbl_v = 'БП ch1: измерить напряжение'
    lbl_mm = 'ММ: измерить V DC'
    checks += [
        ('свип-карта: итоги ok', ok4),
        ('свип-карта: units — карта и цикл', [u[0] for u in units] == ['card', 'loop']),
        ('свип-карта: заголовок в логе', 'СВИП 1 → 3' in text4),
        ('свип-карта: 3 точки по X',
         [x for _l, _v, x, lb, _y in card_pts if lb == lbl_v] == [1.0, 2.0, 3.0]),
        ('свип-карта: ось X от Set-карты', all(v == 'V (свип), В'
                                               for _l, v, *_ in card_pts)),
        ('свип-карта: две линии Y', {lb for *_a, lb, _y in card_pts} == {lbl_v, lbl_mm}),
        ('свип-карта: точек 3×2', len(card_pts) == 6),
        ('свип-карта: Set X ведётся свипом', text4.count('ch1: задать напряжение = 3 В') >= 1),
        ('свип-карта: уровень цикла — 1', [x for _l, _v, x, *_ in loop_pts] == [1.0, 2.0]),
        ('отчёт: все Meas свип-карты (6+2)', len(RESULTS) == 8),
    ]

    # --- свип-карта без Set-карты в X пропускается и точек не даёт ---
    LOG.clear()
    POINTS.clear()
    RESULTS.clear()
    empty = SweepCard(start='1', stop='2', step='1')
    empty.y_cards.append(Card('meas', {'device': 'ps', 'kind': 'voltage'}))
    ok5 = execute_program([empty], settings, log, lambda: False,
                          constants, on_meas, on_result)
    text5 = '\n'.join(t for _k, t in LOG)
    checks += [
        ('свип без X: units пуст', sweep_units([empty]) == []),
        ('свип без X: пропущен с предупреждением',
         'в отсеке X нет Set-карты' in text5),
        ('свип без X: Meas не выполнялась', len(POINTS) == 0 and len(RESULTS) == 0),
        ('свип без X: программа завершена без ошибок', ok5),
    ]

    failed = [name for name, passed in checks if not passed]
    for name, passed in checks:
        print(('PASS  ' if passed else 'FAIL  ') + name)

    if failed:
        print('\nТЕСТ ПРОВАЛЕН:', ', '.join(failed))
        sys.exit(1)
    print('\nТЕСТ ПРОЙДЕН: шагов в логе —',
          sum(1 for k, _ in LOG if k in ('info', 'meas')))


if __name__ == '__main__':
    main()
