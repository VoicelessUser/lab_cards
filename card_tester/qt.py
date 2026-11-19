# -*- coding: utf-8 -*-
"""Совместимость Qt-биндингов: PySide6 → PyQt6 → PyQt5.

Все остальные модули импортируют Qt отсюда, чтобы приложение работало
с любым установленным биндингом.
"""

QT_LIB = None
try:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    QT_LIB = 'PySide6'
except ImportError:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
        QT_LIB = 'PyQt6'
    except ImportError:
        from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
        QT_LIB = 'PyQt5'

if QT_LIB == 'PySide6':
    Signal = QtCore.Signal
    Slot = QtCore.Slot
else:  # PyQt6 / PyQt5
    Signal = QtCore.pyqtSignal
    Slot = QtCore.pyqtSlot

# В Qt6 QAction/QShortcut переехали из QtWidgets в QtGui; в PyQt5 они в QtWidgets.
try:
    QAction = QtGui.QAction
    QShortcut = QtGui.QShortcut
except AttributeError:
    QAction = QtWidgets.QAction
    QShortcut = QtWidgets.QShortcut


def drag_exec(drag, actions):
    """QDrag.exec (Qt6) / exec_ (PyQt5)."""
    if hasattr(drag, 'exec'):
        return drag.exec(actions)
    return drag.exec_(actions)


def mouse_pos(event):
    """Локальная позиция QMouseEvent как QPoint (разные биндинги)."""
    if hasattr(event, 'position'):
        return event.position().toPoint()
    return event.pos()


def drop_pos(event):
    """Позиция QDropEvent как QPoint."""
    if hasattr(event, 'position'):
        return event.position().toPoint()
    return event.pos()
