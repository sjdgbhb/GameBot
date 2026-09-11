"""输入操作 Mixin — 键盘/鼠标/字符串输入（基于 _com_call 原语组合）。"""


class InputMixin:
    """键鼠输入相关操作：按键、点击、移动、字符串发送。

    依赖子类提供 `_com_call(name, *args)` 原语。
    send_string/send_string2 另依赖 `get_foreground_window`（WindowMixin 提供）。
    """

    def set_keypad_delay(self, key_type: str = "normal", delay: float = 0.03):
        """设置按键弹起延迟（秒）"""
        self._com_call("SetKeypadDelay", key_type, delay)

    def key_press_char(self, char: str):
        self._com_call("KeyPressChar", char)

    def key_down_char(self, char: str):
        self._com_call("KeyDownChar", char)

    def key_up_char(self, char: str):
        self._com_call("KeyUpChar", char)

    def move_to(self, x: int, y: int):
        self._com_call("MoveTo", x, y)

    def left_click(self):
        self._com_call("LeftClick")

    def left_double_click(self):
        self._com_call("LeftDoubleClick")

    def left_down(self):
        return self._com_call("LeftDown")

    def left_up(self):
        return self._com_call("LeftUp")

    def right_click(self):
        self._com_call("RightClick")

    def send_string(self, text: str, hwnd: int = 0):
        """使用 DmPlugin SendString 向指定窗口发送文本。

        hwnd 缺省时优先取当前绑定窗口（后台模式下目标窗口未必在前台），
        无绑定再回退到前台窗口。
        """
        target_hwnd = hwnd or getattr(self, "_current_bind_hwnd", 0) or self.get_foreground_window()
        return self._com_call("SendString", target_hwnd, text)

    def send_string2(self, text: str, hwnd: int = 0):
        """使用旧版 DmPlugin SendString2 向指定窗口发送文本。"""
        target_hwnd = hwnd or getattr(self, "_current_bind_hwnd", 0) or self.get_foreground_window()
        return self._com_call("SendString2", target_hwnd, text)

    def send_string_ime(self, text: str):
        """使用 DmPlugin SendStringIme 向绑定窗口发送字符串（支持中文等输入法字符）。

        作用于当前绑定窗口，无需传 hwnd；如需启用 IME 注入，绑定参数
        public 需含 dx.public.input.ime（大漠收费功能）。
        实测注意：dm 3.1233 对 war3 聊天框前/后台均无效（返回 1 但无输入）。
        """
        return self._com_call("SendStringIme", text)
