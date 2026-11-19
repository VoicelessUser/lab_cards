# -*- coding: utf-8 -*-
"""Сохранение/загрузка программы проверки в JSON.

Карты + настройки подключения + константы. Старые типы карт (до объединения
Set/Meas в одну карту с выбором режима) мигрируются при загрузке.
"""
import json

from .cards import Card, ForLoop, CATALOG

# миграция карт старых версий -> (новый тип, параметры)
_LEGACY = {
    # v1: отдельные карты на каждый режим
    'ps_set_voltage': lambda p: ('set', {'kind': 'voltage', 'value': p.get('voltage', '3.3'),
                                         'channel': p.get('channel', '1')}),
    'ps_set_current': lambda p: ('set', {'kind': 'current', 'value': p.get('current', '0.1'),
                                         'channel': p.get('channel', '1')}),
    'ps_meas_v': lambda p: ('meas', {'device': 'ps', 'kind': 'voltage',
                                     'channel': p.get('channel', '1')}),
    'ps_meas_i': lambda p: ('meas', {'device': 'ps', 'kind': 'current',
                                     'channel': p.get('channel', '1')}),
    'mm_meas_vdc': lambda p: ('meas', {'device': 'mm', 'kind': 'voltage_dc'}),
    'mm_meas_vac': lambda p: ('meas', {'device': 'mm', 'kind': 'voltage_ac'}),
    'mm_meas_idc': lambda p: ('meas', {'device': 'mm', 'kind': 'current_dc'}),
    'mm_meas_iac': lambda p: ('meas', {'device': 'mm', 'kind': 'current_ac'}),
    'mm_meas_res': lambda p: ('meas', {'device': 'mm', 'kind': 'resistance'}),
    # v2: карты ps_set/ps_meas/mm_meas (прибор был зашит в типе)
    'ps_set': lambda p: ('set', p),
    'ps_meas': lambda p: ('meas', dict(p, device='ps')),
    'mm_meas': lambda p: ('meas', dict(p, device='mm')),
    'ps_on': lambda p: ('on', p),
    'ps_off': lambda p: ('off', p),
}


def save_program(path, sequence, settings, constants=None):
    data = {
        'version': 2,
        'connection': settings,
        'constants': [dict(c) for c in (constants or [])],
        'sequence': [_dump(it) for it in sequence],
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _dump(it):
    if isinstance(it, ForLoop):
        return {
            'loop': True, 'mode': it.mode, 'count': it.count,
            'start': it.start, 'stop': it.stop, 'step': it.step,
            'target_id': it.target_id,
            'children': [_dump(c) for c in it.children],
        }
    return {'card': it.type, 'params': dict(it.params)}


def _load(it):
    if 'loop' in it:
        mode = it.get('mode', 'count')
        if mode == 'range':          # старое имя режима свипа
            mode = 'sweep'
        return ForLoop(
            mode=mode, count=it.get('count', '3'),
            start=it.get('start', '1'), stop=it.get('stop', '5'),
            step=it.get('step', '1'), target_id=it.get('target_id', ''),
            children=[_load(c) for c in it.get('children', [])],
        )
    t = it.get('card')
    params = dict(it.get('params', {}))
    if t in _LEGACY:                 # карта старой версии
        t, params = _LEGACY[t](params)
    if t not in CATALOG:
        raise ValueError(f'Неизвестный тип карты: {t}')
    return Card(t, params)


def load_program(path):
    """Возвращает (последовательность, настройки подключения, константы)."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    sequence = [_load(it) for it in data.get('sequence', [])]
    constants = [{'name': str(c.get('name', '')), 'value': str(c.get('value', ''))}
                 for c in data.get('constants', [])]
    return sequence, data.get('connection', {}), constants
