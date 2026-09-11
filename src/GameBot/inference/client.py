"""推理客户端单例工厂。

提供 get_inference_client() 全局单例，返回 LocalInferenceClient 实例。
模型在首次调用时懒加载。
"""

import threading

_client = None
_init_lock = threading.Lock()


def get_inference_client(load_chest: bool = True, load_combat: bool = True):
    """获取全局共享的推理客户端单例（首次调用加载模型）。

    Args:
        load_chest: 是否预加载宝箱检测模型（仅首次创建时生效）
        load_combat: 是否预加载战斗状态检测模型（仅首次创建时生效）
    """
    global _client
    if _client is None:
        with _init_lock:
            if _client is None:
                from GameBot.inference.local import LocalInferenceClient

                client = LocalInferenceClient()
                client.load_chest = load_chest
                client.load_combat = load_combat
                client.start()
                _client = client
    return _client
