#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Нормальная точка входа: запуск приложения из корня workspace.

    python main.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from card_tester.main import main

if __name__ == '__main__':
    main()
