"""集成测试公共固件。

集成测试使用真实 src/GameBot/config/data/ 下的配置文件，
不 mock 文件系统，验证多模块协作和配置结构完整性。
"""
import pytest

pytestmark = [pytest.mark.integration]
