"""手动测试公共钩子。

仅在 .venv-dm 32 位 Python 3.8 环境中执行，依赖大漠插件 COM。
"""
import pytest

pytestmark = [
    pytest.mark.manual,
    pytest.mark.dm,
]
