#!/usr/bin/env python3
"""互換シム(段階1: core/ への分割)。systemd の ExecStart はこのファイルを指したままにする。
本体は core/server.py。リポジトリ直下を sys.path に足してから core.server.main() を呼ぶだけ。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.server import main

if __name__ == "__main__":
    main()
