# -*- coding: utf-8 -*-
"""Движок выполнения программы проверки.

execute_program() — чистая логика (тестируется без GUI): подключает приборы
lib_visa, идёт по программе слева направо, разворачивает циклы. Свипирование
(цикл mode='sweep') автоматически управляет всеми Set-картами внутри себя:
на каждой точке подставляет значение в их поле value и передаёт точку
в on_meas для графика.

RunThread / IdnThread — обёртки в QThread для GUI.
"""
import time
from datetime import datetime

from .qt import QtCore, Signal
from .cards import (Card, ForLoop, substitute, describe, loop_label,
                    used_groups, collect_set_cards, CATALOG)

PS_MODELS = ['DP832A', 'NGE100', 'AKIP1143', 'TH6400']
MM_MODELS = ['DM3068', 'AKIP2101', 'SDM3045X']

# режим ММ -> (атрибут mm.meas, единица)
_MM_KIND_ATTR = {
    'voltage_dc': ('voltage_dc', 'В'),
    'voltage_ac': ('voltage_ac', 'В'),
    'current_dc': ('current_dc', 'А'),
    'current_ac': ('current_ac', 'А'),
    'resistance': ('resistance', 'Ом'),
}


class StopRun(Exception):
    """Останов программы пользователем."""


def to_float(s, what):
    try:
        return float(str(s).strip().replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError(f'{what}: «{s}» — не число') from None


def make_device(group, model, port, log):
    """Создаёт прибор lib_visa. Тестовые порты ('test*') — виртуальные приборы."""
    port_s = str(port).strip()
    model_s = str(model).strip()
    if port_s.lower().startswith('test'):
        from lib_visa import PowerSupplyTest, MultimeterTest
        if group == 'ps':
            log(f'БП: виртуальный прибор (модель {model_s or "—"}), порт {port_s}', 'warn')
            return PowerSupplyTest(port_s)
        log(f'ММ: виртуальный прибор (модель {model_s or "—"}), порт {port_s}', 'warn')
        return MultimeterTest(port_s)
    from lib_visa import get_device
    return get_device(model_s, port_s)


def _ps_channel(ctx, params):
    dev = ctx.devices.get('ps')
    if dev is None:
        raise RuntimeError('Источник питания не подключён')
    n = int(to_float(substitute(params.get('channel', '1'), ctx.vars), 'Канал'))
    if not 1 <= n <= 3:
        raise ValueError(f'Канал {n}: допустимы 1–3')
    return getattr(dev, f'channel_{n}')


def do_action(card, ctx):
    """Выполняет действие карты.

    Возвращает (текст результата, число): число не None только для карт Meas
    (используется для графика в реальном времени).
    """
    p = {k: substitute(v, ctx.vars) for k, v in card.params.items()}
    t = card.type

    if t == 'delay':
        sec = to_float(p.get('seconds', '1'), 'Delay')
        deadline = time.monotonic() + max(0.0, sec)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, None
            if ctx.should_stop():
                raise StopRun()
            time.sleep(min(0.1, remaining))

    if t == 'set':
        ch = _ps_channel(ctx, p)
        kind = p.get('kind', 'voltage')
        val = to_float(p.get('value'), 'Значение')
        if kind == 'voltage':
            ch.set.voltage = val
        elif kind == 'current':
            ch.set.current_limit = val
        else:
            raise ValueError(f'Режим «{kind}»: допустимы voltage / current')
        return None, None

    if t == 'meas':
        if p.get('device', 'ps') == 'mm':
            dev = ctx.devices.get('mm')
            if dev is None:
                raise RuntimeError('Мультиметр не подключён')
            kind = p.get('kind', 'voltage_dc')
            if kind not in _MM_KIND_ATTR:
                raise ValueError(f'Неизвестный режим ММ: {kind}')
            attr, unit = _MM_KIND_ATTR[kind]
            val = getattr(dev.meas, attr)
            return f'{val:.6g} {unit}', val
        ch = _ps_channel(ctx, p)
        kind = p.get('kind', 'voltage')
        if kind == 'voltage':
            v = ch.meas.voltage
            return f'{v:.6g} В', v
        if kind == 'current':
            i_ = ch.meas.current
            return f'{i_:.6g} А', i_
        raise ValueError(f'Режим «{kind}»: допустимы voltage / current')

    if t == 'on':
        ch = _ps_channel(ctx, p)
        mode = str(p.get('mode', 'safe_on')).strip().lower()
        if mode == 'safe_on':
            ch.safe_on()
        elif mode == 'on':
            ch.on()
        else:
            raise ValueError(f'Режим «{mode}»: допустимы safe_on / on')
        return None, None

    if t == 'off':
        _ps_channel(ctx, p).off()
        return None, None

    raise ValueError(f'Неизвестная карта: {t}')


def exec_card(card, ctx, depth):
    ind = '  ' * depth
    ctx.steps += 1
    line = f'{ind}Шаг {ctx.steps}: {describe(card, ctx.vars)}'
    try:
        result, value = do_action(card, ctx)
    except StopRun:
        raise
    except Exception as e:
        ctx.log(f'{line} — ✗ {e}', 'error')
        raise
    if result:
        ctx.log(f'{line} → {result}', 'meas')
        stamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        # каждая Meas-карта попадает в отчёт (время замера + значение)
        if ctx.on_result:
            ctx.on_result(describe(card, ctx.vars), result, stamp)
        # точка для графика: если идёт свипирование
        if value is not None and ctx.sweep_stack and ctx.on_meas:
            var, x = ctx.sweep_stack[-1]
            ctx.on_meas(var, x, describe(card, ctx.vars), value)
    else:
        ctx.log(line, 'info')


def loop_values(loop):
    """Список значений для свипа (start → stop с шагом)."""
    start = to_float(loop.start, 'Свип: начало')
    stop = to_float(loop.stop, 'Свип: конец')
    step = to_float(loop.step, 'Свип: шаг')
    if step == 0:
        raise ValueError('Свип: шаг не может быть 0')
    vals = []
    x = start
    eps = abs(step) / 1e9
    if step > 0:
        while x <= stop + eps:
            vals.append(round(x, 10))
            x += step
    else:
        while x >= stop - eps:
            vals.append(round(x, 10))
            x += step
    return vals


def _sweep_x_label(set_cards):
    kinds = {sc.params.get('kind', 'voltage') for sc in set_cards}
    if kinds == {'voltage'}:
        return 'V (свип), В'
    if kinds == {'current'}:
        return 'I (свип), А'
    return 'свип'


def run_loop(loop, ctx, depth):
    ind = '  ' * depth
    if not loop.children:
        ctx.log(f'{ind}⟳ Цикл пуст — пропущен', 'warn')
        return

    if loop.mode == 'sweep':
        set_cards = collect_set_cards(loop.children)
        if not set_cards:
            ctx.log(f'{ind}⟳ Свип недоступен: внутри нет Set-карт — пропущен', 'warn')
            return
        # свип ведёт выбранную в настройках цикла Set-карту;
        # если выбор не сделан, а Set-карта одна — берём её
        target = next((c for c in set_cards if c.id == loop.target_id), None)
        if target is None:
            if len(set_cards) == 1:
                target = set_cards[0]
            else:
                ctx.log(f'{ind}⟳ Свип: выберите Set-карту в настройках цикла '
                        f'(Set-карт: {len(set_cards)}) — пропущен', 'warn')
                return
        vals = loop_values(loop)
        x_name = _sweep_x_label([target])
        ctx.log(f'{ind}⟳ СВИП {loop.start} → {loop.stop}, шаг {loop.step} — '
                f'{len(vals)} точек · {describe(target)}', 'loop')
        ctx.sweep_stack.append((x_name, vals[0] if vals else 0.0))
        try:
            for i, val in enumerate(vals, 1):
                if ctx.should_stop():
                    raise StopRun()
                ctx.sweep_stack[-1] = (x_name, val)
                target.params['value'] = f'{val:g}'
                ctx.log(f'{ind}— точка {i}/{len(vals)}: {val:g}', 'loop')
                run_items(loop.children, ctx, depth + 1)
        finally:
            if ctx.sweep_stack:
                ctx.sweep_stack.pop()
        return

    # повтор N раз
    n = int(to_float(substitute(loop.count, ctx.vars), 'Цикл: повторов'))
    n = max(0, n)
    ctx.log(f'{ind}⟳ повтор × {loop.count} — {n} итер.', 'loop')
    for i in range(1, n + 1):
        if ctx.should_stop():
            raise StopRun()
        ctx.log(f'{ind}— итерация {i}/{n}', 'loop')
        run_items(loop.children, ctx, depth + 1)


def run_items(items, ctx, depth=0):
    for it in items:
        if ctx.should_stop():
            raise StopRun()
        if isinstance(it, ForLoop):
            run_loop(it, ctx, depth)
        elif isinstance(it, Card):
            exec_card(it, ctx, depth)


class RunContext:
    def __init__(self, devices, log, should_stop, vars=None, on_meas=None,
                 on_result=None):
        self.devices = devices
        self.log = log
        self.should_stop = should_stop
        self.vars = dict(vars or {})   # константы (для подстановки в поля)
        self.steps = 0
        self.sweep_stack = []          # [(подпись оси X, значение)]
        self.on_meas = on_meas         # callback(имя_оси, x, подпись, y) — свип
        self.on_result = on_result     # callback(описание, текст, время) — все Meas


def execute_program(sequence, settings, log, should_stop, constants=None,
                    on_meas=None, on_result=None):
    """Подключает нужные приборы, выполняет программу, гарантированно отключает.

    constants — словарь общих констант {имя: значение}, доступны в полях карт.
    on_meas — callback(имя_оси, x, подпись_измерения, y): вызывается для каждой
    Meas-карты внутри цикла-диапазона (данные для графика).
    on_result — callback(описание, значение_текстом, время): вызывается для
    КАЖДОЙ Meas-карты (данные для отчёта).
    Возвращает True при полном прохождении без ошибок.
    """
    devices = {}
    ctx = RunContext(devices, log, should_stop, vars=constants,
                     on_meas=on_meas, on_result=on_result)
    ok = False
    try:
        groups = used_groups(sequence)
        if not groups:
            log('Программа пуста', 'warn')
            return False
        for g, title in (('ps', 'БП'), ('mm', 'ММ')):
            if g in groups:
                cfg = settings.get(g, {})
                dev = make_device(g, cfg.get('model', ''), cfg.get('port', ''), log)
                dev.connect()
                devices[g] = dev
                log(f'{title}: подключён ({cfg.get("model", "?")} → {cfg.get("port", "?")})', 'ok')

        run_items(sequence, ctx)
        log(f'✓ Программа завершена: шагов {ctx.steps}, ошибок нет', 'ok')
        ok = True
    except StopRun:
        log('⏹ Остановлено пользователем', 'warn')
    except Exception as e:
        log(f'✗ Ошибка: {e}', 'error')
    finally:
        ps = devices.get('ps')
        if ps is not None:
            try:
                ps.all_channels_off()
            except Exception:
                pass
        for dev in devices.values():
            try:
                dev.disconnect()
            except Exception:
                pass
        if devices:
            log('── Все каналы выключены, приборы отключены', 'hw')
    return ok


class RunThread(QtCore.QThread):
    """Выполнение программы в отдельном потоке (UI не блокируется)."""
    sig_log = Signal(str, str)                  # текст, вид (в статусную строку)
    sig_done = Signal(bool, str)                # ok, сообщение
    sig_point = Signal(str, str, float, float)  # имя оси X, подпись, x, y
    sig_meas = Signal(str, str, str)            # описание, значение, время

    def __init__(self, sequence, settings, constants=None, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.settings = settings
        self.constants = constants or {}
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        log = lambda text, kind='info': self.sig_log.emit(text, kind)
        on_meas = lambda var, x, label, y: self.sig_point.emit(var, label, x, y)
        on_result = lambda label, text, stamp: self.sig_meas.emit(label, text, stamp)
        try:
            ok = execute_program(self.sequence, self.settings, log,
                                 lambda: self._stop, self.constants,
                                 on_meas, on_result)
        except Exception as e:  # на случай сбоя вне execute_program
            self.sig_log.emit(f'✗ Внутренняя ошибка: {e}', 'error')
            ok = False
        self.sig_done.emit(ok, 'готово' if ok else 'остановлено/ошибка')


class IdnThread(QtCore.QThread):
    """Проверка подключения: connect → *IDN? → disconnect."""
    sig_log = Signal(str, str)
    sig_done = Signal(str, str)      # группа ('ps'/'mm'), 'ok' | 'busy'

    def __init__(self, group, model, port, parent=None):
        super().__init__(parent)
        self.group = group
        self.model = model
        self.port = port

    def run(self):
        title = {'ps': 'БП', 'mm': 'ММ'}[self.group]
        dev = None
        try:
            dev = make_device(self.group, self.model, self.port,
                              lambda t, k='info': self.sig_log.emit(t, k))
            dev.connect()
            idn = dev.identify_yourself()
            self.sig_log.emit(f'{title}: {idn}', 'ok')
            self.sig_done.emit(self.group, 'ok')
        except Exception as e:
            self.sig_log.emit(f'{title}: проверка не удалась — {e}', 'error')
            self.sig_done.emit(self.group, 'ok')
        finally:
            if dev is not None:
                try:
                    dev.disconnect()
                except Exception:
                    pass
