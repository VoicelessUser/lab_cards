# -*- coding: utf-8 -*-
"""Прогон программы проверки на виртуальных приборах, без GUI и железа.

Запуск:  python tests/test_runner.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from card_tester.cards import Card, ForLoop
from card_tester.runner import execute_program

LOG = []
POINTS = []
RESULTS = []


def log(text, kind='info'):
    LOG.append((kind, text))
    print(f'[{kind:5s}] {text}')


def on_meas(var, x, label, y):
    POINTS.append((var, x, label, y))


def on_result(label, text, stamp):
    RESULTS.append((label, text, stamp))


def main():
    # Свип: одна Set-карта внутри — свип ведёт её даже без явного выбора
    sweep_loop = ForLoop(mode='sweep', start='1', stop='3', step='1', children=[
        Card('set', {'kind': 'voltage', 'channel': '1', 'value': '9.9'}),
        Card('delay', {'seconds': '0.2'}),
        Card('meas', {'device': 'ps', 'kind': 'voltage', 'channel': '1'}),
    ])
    # Свип с выбором Set-карты: ведётся только целевая (V), ток не трогается
    target_card = Card('set', {'kind': 'voltage', 'channel': '1', 'value': '9.9'})
    other_card = Card('set', {'kind': 'current', 'channel': '2', 'value': '0.25'})
    pick_loop = ForLoop(mode='sweep', start='1', stop='2', step='1',
                        target_id=target_card.id, children=[target_card, other_card])
    count_loop = ForLoop(mode='count', count='2', children=[
        Card('meas', {'device': 'mm', 'kind': 'voltage_dc'}),
        Card('delay', {'seconds': '0.1'}),
    ])
    sequence = [sweep_loop, pick_loop, count_loop,
                Card('set', {'kind': 'current', 'channel': '1', 'value': '0.5'}),
                Card('set', {'kind': 'voltage', 'channel': '3', 'value': 'Vcc'})]

    settings = {
        'ps': {'model': 'DP832A', 'port': 'test_float'},
        'mm': {'model': 'DM3068', 'port': 'test_float'},
    }
    constants = {'Vcc': '3.3'}

    ok = execute_program(sequence, settings, log, lambda: False,
                         constants, on_meas, on_result)

    text = '\n'.join(t for _k, t in LOG)
    labels = [lbl for _v, _x, lbl, _y in POINTS]
    checks = [
        ('итоги ok', ok),
        ('СВИП 1 → 3', 'СВИП 1 → 3' in text),
        ('точки свипа', '— точка 3/3: 3' in text),
        ('график: 3 точки', len(POINTS) == 3),
        ('график: ось X', all(v == 'V (свип), В' for v, *_ in POINTS)),
        ('график: x = 1..3', [x for _v, x, _l, _y in POINTS] == [1.0, 2.0, 3.0]),
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
