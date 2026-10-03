#!/bin/sh
# 验红专用：先清字节码缓存，再不写字节码地跑测试。原因见计划的 Global Constraints。
find src tests -name __pycache__ -prune -exec rm -rf {} +
exec .venv/bin/python -B -m pytest "$@" -q
