#!/usr/bin/env python3
"""互換シム(段階1: core/ への分割)。本体は core/update.py。
`import update` が core.update と同一のモジュールオブジェクトを返すようにする。
CLI で直接叩く場合(python3 update.py state 等)は core/update.py を直接呼ぶこと
(このシムは import 専用で、__main__ 側の分岐は core 側では実行されない)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import update as _m

sys.modules[__name__] = _m
