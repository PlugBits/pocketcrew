#!/usr/bin/env python3
"""互換シム(段階1: core/ への分割)。本体は core/webpush.py。
`import webpush` が core.webpush と同一のモジュールオブジェクトを返すようにする。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import webpush as _m

sys.modules[__name__] = _m
