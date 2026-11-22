# -*- coding: utf-8 -*-
"""Сохранение/загрузка программы проверки в JSON.

Карты + коробки-приборы + константы (v3). Карты ссылаются на прибор через
id коробки в params['device']. Старые файлы (v2, «подключение» с одним БП
и одним ММ) мигрируются: настройки превращаются в две коробки, а карты
привязываются к ним при загрузке (см. MainWindow._migrate_device_ids).
"""
import json

from .cards import (Card, ForLoop, SweepCard, CATALOG, DeviceBox,
                    DEFAULT_PS, DEFAULT_MM)

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


def save_program(path, sequence, devices, constants=None):
    """Сохраняет программу: карты, коробки-приборы, константы."""
    data = {
        'version': 3,
        'devices': [{'kind': b.kind, 'model': b.model, 'port': b.port, 'id': b.id}
                    for b in (devices or [])],
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
    if isinstance(it, SweepCard):
        return {
            'sweep_card': True,
            'start': it.start, 'stop': it.stop, 'step': it.step,
            'x': [_dump(c) for c in it.x_cards],
            'mid': [_dump(c) for c in it.mid_cards],
            'y': [_dump(c) for c in it.y_cards],
        }
    # id карты сохраняем: на него ссылается target_id свипа
    return {'card': it.type, 'params': dict(it.params), 'id': it.id}


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
    if 'sweep_card' in it:
        return SweepCard(
            start=it.get('start', '1'), stop=it.get('stop', '5'),
            step=it.get('step', '1'),
            x_cards=[_load(c) for c in it.get('x', [])],
            mid_cards=[_load(c) for c in it.get('mid', [])],
            y_cards=[_load(c) for c in it.get('y', [])],
        )
    t = it.get('card')
    params = dict(it.get('params', {}))
    if t in _LEGACY:                 # карта старой версии
        t, params = _LEGACY[t](params)
    if t not in CATALOG:
        raise ValueError(f'Неизвестный тип карты: {t}')
    card = Card(t, params)
    if it.get('id'):                 # id из файла (в старых файлах его нет)
        card.id = str(it['id'])
    return card


def _devices_from_legacy(connection):
    """Старый файл (v2): настройки подключения → две коробки (БП и ММ)."""
    conn = connection if isinstance(connection, dict) else {}
    ps = conn.get('ps', {}) or {}
    mm = conn.get('mm', {}) or {}
    return [
        DeviceBox(kind='ps',
                  model=str(ps.get('model') or DEFAULT_PS['model']),
                  port=str(ps.get('port') or DEFAULT_PS['port'])),
        DeviceBox(kind='mm',
                  model=str(mm.get('model') or DEFAULT_MM['model']),
                  port=str(mm.get('port') or DEFAULT_MM['port'])),
    ]


def load_program(path):
    """Возвращает (последовательность, коробки-приборы, константы)."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    sequence = [_load(it) for it in data.get('sequence', [])]
    constants = [{'name': str(c.get('name', '')), 'value': str(c.get('value', ''))}
                 for c in data.get('constants', [])]
    devices = []
    for d in data.get('devices', []):
        b = DeviceBox(kind=str(d.get('kind', 'ps')),
                      model=str(d.get('model', '')),
                      port=str(d.get('port', '')))
        if d.get('id'):
            b.id = str(d['id'])
        devices.append(b)
    if not devices:                      # старый файл (v2): подключение → коробки
        devices = _devices_from_legacy(data.get('connection', {}))
    return sequence, devices, constants
