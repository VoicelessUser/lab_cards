# -*- coding: utf-8 -*-
"""Модель «карт» программы проверки и каталог действий.

Тип карты = тип действия. В колоде внизу у стола — стопки по типу:
Set / Meas / ON-OFF / Delay. Прибор (БП или Мультиметр) выбирается в
настройках карты справа: у Meas есть переключатель прибора, Set и ON/OFF —
только БП. Карты одного типа — одного цвета; значок и подпись на карте —
по выбранному прибору.

Цикл ForLoop: «повторить N раз» или «свипирование» — автоматически ведёт
все Set-карты внутри себя (если Set-карт нет, свип недоступен).
"""
import uuid
from dataclasses import dataclass, field

# --- цвета: по типу действия (Meas у БП и ММ — один цвет) ---
C_SET = '#2f6fd6'     # Set — синий
C_MEAS = '#1e9e5a'    # Meas — зелёный
C_SW = '#7a4fd0'      # ON / OFF — фиолетовый
C_SYS = '#6b7280'     # Delay — серый
C_LOOP = '#b45309'    # линия вставки

DEVICE_LABELS = {'ps': 'БП', 'mm': 'Мультиметр', 'sys': 'Система'}

# options: [(значение, подпись)]; options=None — список зависит от прибора
CATALOG = {
    'set': dict(color=C_SET, title='Set', icon='ps',
        fields=[
            dict(key='kind', label='Что задаём', default='voltage',
                 options=[('voltage', 'Напряжение (В)'), ('current', 'Ток (А)')]),
            dict(key='channel', label='Канал', default='1'),
            dict(key='value', label='Значение', default='3.3'),
        ]),
    'meas': dict(color=C_MEAS, title='Meas', icon=None,   # значок по прибору
        fields=[
            dict(key='device', label='Прибор', default='ps',
                 options=[('ps', 'БП'), ('mm', 'Мультиметр')]),
            dict(key='channel', label='Канал', default='1'),
            dict(key='kind', label='Режим', default='voltage', options=None),
        ]),
    'on': dict(color=C_SW, title='ON', icon='ps',
        fields=[
            dict(key='mode', label='Режим включения', default='safe_on',
                 options=[('safe_on', 'safe_on'), ('on', 'on')]),
            dict(key='channel', label='Канал', default='1'),
        ]),
    'off': dict(color=C_SW, title='OFF', icon='ps',
        fields=[dict(key='channel', label='Канал', default='1')]),
    'delay': dict(color=C_SYS, title='Delay', icon='sys',
        fields=[dict(key='seconds', label='Задержка, с', default='1.0')]),
}

# Стопки колоды (внизу у стола): одна стопка на тип действия
DECK_STACKS = [
    ('set', 'Set'),
    ('meas', 'Meas'),
    ('on', 'ON/OFF'),
    ('delay', 'Delay'),
]

_MEAS_KINDS = {
    'ps': [('voltage', 'Напряжение (В)'), ('current', 'Ток (А)')],
    'mm': [('voltage_dc', 'V DC (В)'), ('voltage_ac', 'V AC (В)'),
           ('current_dc', 'I DC (А)'), ('current_ac', 'I AC (А)'),
           ('resistance', 'R (Ом)')],
}

_MEAS_KIND_SHORT = {
    'ps': {'voltage': 'V', 'current': 'I'},
    'mm': {'voltage_dc': 'V DC', 'voltage_ac': 'V AC',
           'current_dc': 'I DC', 'current_ac': 'I AC', 'resistance': 'R'},
}

# Карты, которыми управляет свипирование
SET_CARD_TYPES = ('set',)


@dataclass
class Card:
    """Одна карта-действие. params: имя поля -> строка."""
    type: str
    params: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class ForLoop:
    """Цикл вокруг соседних карт. mode: 'count' (N раз) | 'sweep' (свип Set-карт).

    target_id — id Set-карты внутри цикла, которую ведёт свип
    (выбирается в настройках цикла; если пусто и Set-карта одна — она).
    """
    mode: str = 'count'
    count: str = '3'
    start: str = '1'
    stop: str = '5'
    step: str = '1'
    target_id: str = ''
    children: list = field(default_factory=list)   # Card | ForLoop
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def substitute(value, vars_):
    """Подстановка констант: «Vcc» (точное совпадение) или шаблон «{Vcc}»."""
    s = str(value).strip()
    if not vars_:
        return s
    if s in vars_:
        return str(vars_[s])
    for name, val in vars_.items():
        s = s.replace('{' + name + '}', str(val))
    return s


def meas_kind_options(device):
    """Режимы Meas-карты для выбранного прибора."""
    return _MEAS_KINDS.get(device, _MEAS_KINDS['ps'])


def new_card(card_type):
    """Карта с параметрами по умолчанию из каталога."""
    return Card(card_type, {f['key']: f['default'] for f in CATALOG[card_type]['fields']})


def card_device_label(card):
    """Название прибора для подписи на карте (у Meas — по её настройке)."""
    if card.type == 'meas':
        return DEVICE_LABELS[card.params.get('device', 'ps')]
    if card.type == 'delay':
        return DEVICE_LABELS['sys']
    return DEVICE_LABELS['ps']            # set / on / off — только БП


def card_icon(card):
    """Какой значок рисовать на карте (у Meas — по её настройке)."""
    if card.type == 'meas':
        return card.params.get('device', 'ps')
    return CATALOG[card.type]['icon']


def card_color(card):
    """Цвет карты — по типу действия."""
    return CATALOG[card.type]['color']


def summarize(card):
    """Краткая подпись параметров на карте."""
    p = card.params
    t = card.type
    if t == 'set':
        k = _MEAS_KIND_SHORT['ps'].get(p.get('kind'), '?')
        return f'ch{p.get("channel", "1")} · {k} = {p.get("value", "")}'
    if t == 'meas':
        dev = p.get('device', 'ps')
        k = _MEAS_KIND_SHORT[dev].get(p.get('kind'), '?')
        if dev == 'ps':
            return f'БП ch{p.get("channel", "1")} · {k}'
        return f'ММ · {k}'
    if t == 'on':
        return f'ch{p.get("channel", "1")} · {p.get("mode", "safe_on")}'
    if t == 'off':
        return f'ch{p.get("channel", "1")}'
    if t == 'delay':
        return f'{p.get("seconds", "")} с'
    return ''


def stats_rows(card, vars_=None):
    """Строки «параметр — значение» для тёмной панели на карте (как статы)."""
    p = {k: substitute(v, vars_) for k, v in card.params.items()}
    t = card.type
    if t == 'set':
        k = _MEAS_KIND_SHORT['ps'].get(p.get('kind'), '?')
        unit = 'В' if p.get('kind') == 'voltage' else 'А'
        return [('РЕЖИМ', k), ('КАНАЛ', str(p.get('channel', '1'))),
                ('ЗНАЧЕНИЕ', f'{p.get("value", "")} {unit}')]
    if t == 'meas':
        if p.get('device', 'ps') == 'mm':
            return [('РЕЖИМ', _MEAS_KIND_SHORT['mm'].get(p.get('kind'), '?'))]
        return [('РЕЖИМ', _MEAS_KIND_SHORT['ps'].get(p.get('kind'), '?')),
                ('КАНАЛ', str(p.get('channel', '1')))]
    if t == 'on':
        return [('РЕЖИМ', str(p.get('mode', 'safe_on'))),
                ('КАНАЛ', str(p.get('channel', '1')))]
    if t == 'off':
        return [('КАНАЛ', str(p.get('channel', '1')))]
    if t == 'delay':
        return [('ВРЕМЯ', f'{p.get("seconds", "")} с')]
    return []


def describe(card, vars_=None):
    """Человеческое описание действия для статуса (с подстановкой констант)."""
    t = card.type
    p = {k: substitute(v, vars_) for k, v in card.params.items()}
    ch = p.get('channel', '?')
    if t == 'set':
        what = 'напряжение' if p.get('kind') == 'voltage' else 'ток'
        unit = 'В' if p.get('kind') == 'voltage' else 'А'
        return f'БП ch{ch}: задать {what} = {p.get("value", "?")} {unit}'
    if t == 'meas':
        if p.get('device', 'ps') == 'mm':
            k = _MEAS_KIND_SHORT['mm'].get(p.get('kind'), '?')
            return f'ММ: измерить {k}'
        what = 'напряжение' if p.get('kind') == 'voltage' else 'ток'
        return f'БП ch{ch}: измерить {what}'
    if t == 'on':
        return f'БП ch{ch}: включить ({p.get("mode", "safe_on")})'
    if t == 'off':
        return f'БП ch{ch}: выключить'
    if t == 'delay':
        return f'задержка {p.get("seconds", "?")} с'
    return t


def loop_label(loop):
    """Подпись на зоне цикла: «повтор × 3» / «свип 1 → 5, шаг 1»."""
    if loop.mode == 'sweep':
        return f'свип {loop.start} → {loop.stop}, шаг {loop.step}'
    return f'повтор × {loop.count}'


def find_container(seq, item_id):
    """(список, индекс) для элемента с данным id; рекурсивно внутри циклов."""
    for i, it in enumerate(seq):
        if it.id == item_id:
            return seq, i
        if isinstance(it, ForLoop):
            found = find_container(it.children, item_id)
            if found:
                return found
    return None


def remove_items(seq, ids):
    """Удаляет элементы с указанными id (рекурсивно), возвращает число удалённых."""
    n = 0
    keep = []
    for it in seq:
        if it.id in ids:
            n += 1
            continue
        if isinstance(it, ForLoop):
            n += remove_items(it.children, ids)
        keep.append(it)
    seq[:] = keep
    return n


def expand_on_off_pairs(seq, ids):
    """Пара ON/OFF удаляется вместе: к выделению добавляется соседняя карта пары.

    Партнёр — карта непосредственно рядом (справа для ON, слева для OFF):
    именно так их раскладывает колода. Если карты разведены по программе,
    они удаляются независимо.
    """
    result = set(ids)

    def walk(lst):
        for i, it in enumerate(lst):
            if isinstance(it, ForLoop):
                walk(it.children)
                continue
            if it.type in ('on', 'off') and it.id in result:
                j = i + 1 if it.type == 'on' else i - 1
                if 0 <= j < len(lst):
                    partner = lst[j]
                    if {it.type, partner.type} == {'on', 'off'}:
                        result.add(partner.id)

    walk(seq)
    return result


def used_groups(seq):
    """Какие приборы задействованы ('ps'/'mm') — с учётом прибора в Meas-картах."""
    g = set()
    for it in seq:
        if isinstance(it, ForLoop):
            g |= used_groups(it.children)
        elif it.type == 'meas':
            g.add(it.params.get('device', 'ps'))
        elif it.type in ('set', 'on', 'off'):
            g.add('ps')
    return g


def collect_set_cards(seq):
    """Все Set-карты внутри последовательности (включая вложенные циклы)."""
    out = []
    for it in seq:
        if isinstance(it, ForLoop):
            out += collect_set_cards(it.children)
        elif isinstance(it, Card) and it.type in SET_CARD_TYPES:
            out.append(it)
    return out
