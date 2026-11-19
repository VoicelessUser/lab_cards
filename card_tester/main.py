# -*- coding: utf-8 -*-
"""Точка входа: python -m card_tester.main  (или python card_tester/main.py)."""
import os
import sys

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from card_tester.main_window import MainWindow
else:
    from .main_window import MainWindow


def main():
    from .qt import QtWidgets, QtCore
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    win = MainWindow()
    win.show()
    sys.exit(app.exec() if hasattr(app, 'exec') else app.exec_())


if __name__ == '__main__':
    main()
