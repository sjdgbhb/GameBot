"""手动测试公共钩子。

在主环境 3.12 中执行（大漠经 dm_bridge 子进程调用），依赖大漠插件 COM。
"""

import pytest

pytestmark = [
    pytest.mark.manual,
    pytest.mark.dm,
]
