#!/usr/bin/env python3
"""互換シム(段階1: core/ への分割)。本体は core/collect.py。
`import collect` が core.collect と同一のモジュールオブジェクトを返すようにする
(状態を共有するため、コピーではなく sys.modules の差し替え)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import collect as _m

sys.modules[__name__] = _m
