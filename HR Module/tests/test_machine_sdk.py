from __future__ import annotations

import ctypes

from attendance_relay.machine_sdk import SBXPCClient


class _FakeOle:
    def __init__(self) -> None:
        self.freed: list[object] = []

    def SysAllocString(self, _value: str) -> int:
        # Mimic Windows ctypes behavior for c_void_p restype: returns raw int pointer.
        return 123456

    def SysFreeString(self, value: object) -> None:
        self.freed.append(value)


def test_alloc_bstr_wraps_raw_pointer_into_ctypes_instance() -> None:
    client = SBXPCClient.__new__(SBXPCClient)
    client._bstr_t = ctypes.c_void_p
    client._ole = _FakeOle()

    ptr = client._alloc_bstr("abc")
    assert isinstance(ptr, ctypes.c_void_p)
    assert ptr.value == 123456

    client._free_bstr(ptr)
    assert len(client._ole.freed) == 1
    assert isinstance(client._ole.freed[0], ctypes.c_void_p)
