# -*- coding: utf-8 -*-
"""Модель «карт» программы проверки и каталог действий.

Тип карты = тип действия. В колоде внизу у стола — стопки по типу:
Set / Meas / ON-OFF / Delay. Прибор (БП или Мультиметр) выбирается в
настройках карты справа: у Meas есть переключатель прибора, Set и ON/OFF —
только БП. Карты одного типа — одного цвета; значок и подпись на карте —
по выбранному прибору.

Цикл ForLoop: «повторить N раз» или «свипирование» — ведёт СВОЮ Set-карту
(свипируемый параметр). Циклы вкладываются друг в друга — уровни свипирования;
Set-карты раздаются свипам автоматически: вложенный свип забирает свою карту
первым, внешний берёт первую свободную из своего поддерева (карту можно
выбрать и вручную в настройках цикла). Если карта, ведомаая внешним свипом,
лежит внутри вложенного — значение подставляет сам внешний свип, а вложенные
свипы эту карту не трогают. Число свипов определяют Set-карты: свип без
свободной Set-карты не работает и графика не даёт; Meas-карта попадает на
график ближайшего объемлющего свипа.

Свип-карта (SweepCard) — отдельная жёлтая карта-«прибор» с тремя отсеками:
слева X — ровно одна Set-карта (свипируемая величина, ось X), посередине —
любые карты (выполняются на каждой точке), справа Y — Meas-карты (ось Y,
каждая — своя линия на графике). Отсеки X/Y принимают только свои типы карт,
карта-свип внутрь свипа не кладётся. Диапазон точек (От/До/Шаг) — в настройках
самой свип-карты; Set-карта отсека X не участвует в раздаче карт циклам-свипам.
"""
import uuid
from dataclasses import dataclass, field

# --- цвета: по типу действия (Meas у БП и ММ — один цвет) ---
C_SET = '#2f6fd6'     # Set — синий
C_MEAS = '#1e9e5a'    # Meas — зелёный
C_SW = '#7a4fd0'      # ON / OFF — фиолетовый
C_SYS = '#6b7280'     # Delay — серый
C_SWEEP = '#F5B301'   # Свип — жёлтый
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
    'sweep': dict(color=C_SWEEP, title='Свип', icon='sweep', fields=[]),
}

# Стопки колоды (внизу у стола): одна стопка на тип действия
DECK_STACKS = [
    ('set', 'Set'),
    ('meas', 'Meas'),
    ('on', 'ON/OFF'),
    ('delay', 'Delay'),
    ('sweep', 'Свип'),
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

    target_id — id Set-карты (переменной свипа). Карту можно выбрать в
    настройках цикла из свободных карт поддерева (не занятых вложенными
    свипами); если выбор не сделан, свип берёт первую свободную.
    """
    mode: str = 'count'
    count: str = '3'
    start: str = '1'
    stop: str = '5'
    step: str = '1'
    target_id: str = ''
    children: list = field(default_factory=list)   # Card | ForLoop | SweepCard
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class SweepCard:
    """Карта-свипирование с тремя отсеками.

    x_cards — ровно одна Set-карта: свипируемая величина (ось X);
    mid_cards — любые карты, выполняются на каждой точке;
    y_cards — Meas-карты: измерения (ось Y, каждая — своя линия графика).
    Диапазон точек — start → stop с шагом step (как у цикла-свипа).
    """
    start: str = '1'
    stop: str = '5'
    step: str = '1'
    x_cards: list = field(default_factory=list)    # [Card('set')] — не больше одной
    mid_cards: list = field(default_factory=list)  # Card | ForLoop | SweepCard
    y_cards: list = field(default_factory=list)    # [Card('meas'), ...]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def sweep_bays(sweep):
    """Отсеки свип-карты: [(роль, список), ...] в порядке слева направо."""
    return (('x', sweep.x_cards), ('mid', sweep.mid_cards), ('y', sweep.y_cards))


def x_set_card(sweep):
    """Set-карта отсека X (первая карта, если это Set); None — отсек пуст."""
    for c in sweep.x_cards:
        if isinstance(c, Card) and c.type == 'set':
            return c
    return None


def sweep_label(sweep):
    """Подпись свип-карты: «свип 1 → 5, шаг 1»."""
    return f'свип {sweep.start} → {sweep.stop}, шаг {sweep.step}'


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


def new_card(card_type, device=None):
    """Карта с параметрами по умолчанию из каталога.

    device — прибор стопки колоды: у Meas-карты он фиксируется при создании
    (Meas из «Мультиметра» всегда мультиметр) и в GUI не меняется.
    """
    card = Card(card_type, {f['key']: f['default'] for f in CATALOG[card_type]['fields']})
    if card_type == 'meas' and device and device != card.params.get('device'):
        card.params['device'] = device
        valid = [v for v, _ in meas_kind_options(device)]
        if card.params.get('kind') not in valid:
            card.params['kind'] = valid[0]
    return card


def card_device_label(card):
    """Название прибора для подписи на карте (у Meas — по её настройке)."""
    if card.type == 'meas':
        return DEVICE_LABELS[card.params.get('device', 'ps')]
    if card.type in ('delay', 'sweep'):
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
    if isinstance(card, SweepCard):
        xs, ys = len(card.x_cards), len(card.y_cards)
        return (f'свипирование: {sweep_label(card)} · X: {xs}, Y: {ys}')
    t = card.type
    if t == 'sweep':
        return 'свипирование: X — Set-карта (ось X), Y — Meas-карты (ось Y)'
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
    """(список, индекс) для элемента с данным id; рекурсивно внутри циклов
    и отсеков свип-карт."""
    for i, it in enumerate(seq):
        if it.id == item_id:
            return seq, i
        if isinstance(it, ForLoop):
            found = find_container(it.children, item_id)
            if found:
                return found
        elif isinstance(it, SweepCard):
            for _role, lst in sweep_bays(it):
                found = find_container(lst, item_id)
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
        elif isinstance(it, SweepCard):
            for _role, lst in sweep_bays(it):
                n += remove_items(lst, ids)
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
            if isinstance(it, SweepCard):
                for _role, sub in sweep_bays(it):
                    walk(sub)
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
        elif isinstance(it, SweepCard):
            for _role, lst in sweep_bays(it):
                g |= used_groups(lst)
        elif it.type == 'meas':
            g.add(it.params.get('device', 'ps'))
        elif it.type in ('set', 'on', 'off'):
            g.add('ps')
    return g


def collect_set_cards(seq):
    """Все Set-карты внутри последовательности (включая вложенные циклы).

    Внутрь свип-карт не заходим: её Set-карта ведётся самой свип-картой,
    циклам-свипам недоступна.
    """
    out = []
    for it in seq:
        if isinstance(it, ForLoop):
            out += collect_set_cards(it.children)
        elif isinstance(it, Card) and it.type in SET_CARD_TYPES:
            out.append(it)
    return out


def own_level_set_cards(seq):
    """Set-карты уровня: вне вложенных свипов (циклы «повтор» просматриваются).

    Такие карты свип применяет обычным порядком внутри своего прохода;
    карты глубже (внутри вложенных свипов и свип-карт) свип применяет сам
    до прохода.
    """
    out = []
    for it in seq:
        if isinstance(it, ForLoop):
            if it.mode != 'sweep':
                out += own_level_set_cards(it.children)
        elif isinstance(it, Card) and it.type in SET_CARD_TYPES:
            out.append(it)
    return out


def _pick_sweep_target(loop, claimed_ids):
    """Set-карта свипа loop: явный target_id, если карта свободна,
    иначе первая свободная в его поддереве; None — свободных нет."""
    cand = [c for c in collect_set_cards(loop.children) if c.id not in claimed_ids]
    target = next((c for c in cand if c.id == loop.target_id), None)
    return target if target is not None else (cand[0] if cand else None)


def sweep_candidates(loop):
    """Set-карты, из которых свип loop выбирает переменную: его поддерево
    минус карты, занятые вложенными свипами (их цели)."""
    inner = {c.id for c in resolve_sweeps(loop.children).values() if c is not None}
    return [c for c in collect_set_cards(loop.children) if c.id not in inner]


def resolve_sweeps(seq):
    """Раздача Set-карт свипам: каждому свипу — своя переменная.

    Свип забирает карту из своего поддерева (явный target_id имеет приоритет),
    при этом карты, уже занятые вложенными свипами, ему недоступны: вложенный
    свип «забирает» свою карту первым, внешний берёт первую свободную. Так три
    Set-карты внутри самого внутреннего из трёх вложенных свипов дают три
    уровня свипирования. Внутрь свип-карт заходим только ради циклов в её
    середине — Set-карта отсека X ведётся самой свип-картой. Возвращает
    {loop.id: Set-карта | None} — None у свипа, которому свободных карт
    не досталось (он пропускается).
    """
    owners = {}

    def walk(seq):
        claimed = set()
        for it in seq:
            if isinstance(it, ForLoop):
                deeper = walk(it.children)
                claimed |= deeper
                if it.mode == 'sweep':
                    target = _pick_sweep_target(it, deeper)
                    owners[it.id] = target
                    if target is not None:
                        claimed.add(target.id)
            elif isinstance(it, SweepCard):
                walk(it.mid_cards)      # циклы в середине раздают себе карты сами
        return claimed

    walk(seq)
    return owners


def sweep_units(seq):
    """Работающие свипы в порядке следования (нумерация графиков):
    [('card'|'loop', id), ...]. Свип-карта работает, если в отсеке X лежит
    Set-карта; цикл-свип — если у него есть своя Set-карта."""
    owners = resolve_sweeps(seq)
    units = []

    def walk(lst):
        for it in lst:
            if isinstance(it, SweepCard):
                if x_set_card(it) is not None:
                    units.append(('card', it.id))
                walk(it.mid_cards)
            elif isinstance(it, ForLoop):
                if it.mode == 'sweep' and owners.get(it.id) is not None:
                    units.append(('loop', it.id))
                walk(it.children)

    walk(seq)
    return units


def count_sweeps(seq):
    """Число уровней свипирования — свипы со своей Set-картой.

    Число свипов определяют Set-карты (свипируемые параметры), а не Meas:
    свип без свободной Set-карты — не свип (и графика не даёт).
    """
    return sum(1 for c in resolve_sweeps(seq).values() if c is not None)


def subtree_has_container(item, container):
    """Список container лежит внутри item (тело цикла или отсек свип-карты)?

    Нужно, чтобы цикл/свип нельзя было выложить внутрь самого себя.
    """
    if isinstance(item, ForLoop):
        if container is item.children:
            return True
        return any(subtree_has_container(c, container)
                   for c in item.children if isinstance(c, (ForLoop, SweepCard)))
    if isinstance(item, SweepCard):
        for _role, lst in sweep_bays(item):
            if container is lst:
                return True
        return any(subtree_has_container(c, container)
                   for c in item.mid_cards if isinstance(c, (ForLoop, SweepCard)))
    return False
