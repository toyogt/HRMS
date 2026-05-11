from __future__ import annotations

import ctypes
import os
from base64 import b64encode
from datetime import datetime
from pathlib import Path
from typing import Any


class MachineSdkError(RuntimeError):
    pass


class SBXPCClient:
    def __init__(self, dll_path: str | Path) -> None:
        if os.name != "nt":
            raise MachineSdkError("SBXPC SDK sync is supported only on Windows.")

        self.dll_path = Path(dll_path)
        if not self.dll_path.exists():
            raise MachineSdkError(f"SDK DLL not found: {self.dll_path}")

        self._bstr_t = ctypes.c_void_p
        self._long_t = ctypes.c_long
        # Vendor C# samples bind many SDK BOOL-like returns/flags as byte.
        # Using c_ubyte here aligns ctypes signatures with the SDK samples.
        self._bool_t = ctypes.c_ubyte

        self._dll = ctypes.WinDLL(str(self.dll_path))
        self._ole = ctypes.windll.oleaut32
        self._configure_ole()
        self._configure_dll()

    def _configure_ole(self) -> None:
        self._ole.SysAllocString.argtypes = [ctypes.c_wchar_p]
        self._ole.SysAllocString.restype = self._bstr_t
        self._ole.SysFreeString.argtypes = [self._bstr_t]
        self._ole.SysFreeString.restype = None

    def _configure_dll(self) -> None:
        self._dll._DotNET.argtypes = []
        self._dll._DotNET.restype = None

        self._dll._ConnectTcpip.argtypes = [
            self._long_t,
            ctypes.POINTER(self._bstr_t),
            self._long_t,
            self._long_t,
        ]
        self._dll._ConnectTcpip.restype = self._bool_t

        self._dll._Disconnect.argtypes = [self._long_t]
        self._dll._Disconnect.restype = None

        self._dll._EnableDevice.argtypes = [self._long_t, self._bool_t]
        self._dll._EnableDevice.restype = self._bool_t

        self._dll._EnableUser.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            self._long_t,
            self._bool_t,
        ]
        self._dll._EnableUser.restype = self._bool_t

        self._dll._SetEnrollData1.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            self._long_t,
            ctypes.POINTER(ctypes.c_void_p),
            self._long_t,
        ]
        self._dll._SetEnrollData1.restype = self._bool_t

        self._dll._SetUserName1.argtypes = [
            self._long_t,
            self._long_t,
            ctypes.POINTER(self._bstr_t),
        ]
        self._dll._SetUserName1.restype = self._bool_t

        self._dll._GetUserName1.argtypes = [
            self._long_t,
            self._long_t,
            ctypes.POINTER(self._bstr_t),
        ]
        self._dll._GetUserName1.restype = self._bool_t

        self._dll._ReadAllUserID.argtypes = [self._long_t]
        self._dll._ReadAllUserID.restype = self._bool_t

        self._dll._GetAllUserID.argtypes = [
            self._long_t,
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
        ]
        self._dll._GetAllUserID.restype = self._bool_t

        self._dll._DeleteEnrollData.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            self._long_t,
        ]
        self._dll._DeleteEnrollData.restype = self._bool_t

        self._dll._GetDeviceTime.argtypes = [
            self._long_t,
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
        ]
        self._dll._GetDeviceTime.restype = self._bool_t

        self._dll._GeneralOperationXML.argtypes = [self._long_t, ctypes.POINTER(self._bstr_t)]
        self._dll._GeneralOperationXML.restype = self._bool_t

        self._dll._XML_AddString.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        self._dll._XML_AddString.restype = self._bool_t

        self._dll._XML_AddInt.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        self._dll._XML_AddInt.restype = self._bool_t

        self._dll._XML_AddLong.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            self._long_t,
        ]
        self._dll._XML_AddLong.restype = self._bool_t

        self._dll._XML_AddBoolean.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            self._bool_t,
        ]
        self._dll._XML_AddBoolean.restype = self._bool_t

        self._dll._XML_AddBinaryByte.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_void_p),
            self._long_t,
        ]
        self._dll._XML_AddBinaryByte.restype = self._bool_t

        self._dll._XML_ParseString.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.POINTER(self._bstr_t),
        ]
        self._dll._XML_ParseString.restype = self._bool_t

        self._dll._XML_ParseInt.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
        ]
        self._dll._XML_ParseInt.restype = self._long_t

        self._dll._XML_ParseLong.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
        ]
        self._dll._XML_ParseLong.restype = self._long_t

        self._dll._XML_ParseBoolean.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
        ]
        self._dll._XML_ParseBoolean.restype = self._bool_t

        self._dll._XML_ParseBinaryByte.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ubyte),
            self._long_t,
        ]
        self._dll._XML_ParseBinaryByte.restype = self._bool_t

        self._dll._GetLastError.argtypes = [self._long_t, ctypes.POINTER(self._long_t)]
        self._dll._GetLastError.restype = self._bool_t

        # Optional functions that may differ across firmware/SDK builds.
        self._fn_set_device_time1 = self._bind_optional(
            "_SetDeviceTime1",
            [
                self._long_t,
                self._long_t,
                self._long_t,
                self._long_t,
                self._long_t,
                self._long_t,
                self._long_t,
            ],
            self._bool_t,
        )
        self._fn_get_serial_number = self._bind_optional(
            "_GetSerialNumber",
            [self._long_t, ctypes.POINTER(self._bstr_t)],
            self._bool_t,
        )
        self._fn_get_device_model = self._bind_optional(
            "_GetDeviceModel",
            [
                self._long_t,
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
            ],
            self._bool_t,
        )
        self._fn_read_all_glog_data = self._bind_optional(
            "_ReadAllGLogData",
            [self._long_t],
            self._bool_t,
        )
        self._fn_get_all_glog_data = self._bind_optional(
            "_GetAllGLogData",
            [
                self._long_t,
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
                ctypes.POINTER(self._long_t),
            ],
            self._bool_t,
        )
        self._fn_get_backup_number = self._bind_optional(
            "_GetBackupNumber",
            [self._long_t],
            self._long_t,
        )
        self._fn_get_internal_fw_ver = self._bind_optional(
            "_GetInternalFwVer",
            [self._long_t],
            self._long_t,
        )

    def _bind_optional(self, name: str, argtypes: list[Any], restype: Any) -> Any | None:
        try:
            fn = getattr(self._dll, name)
        except AttributeError:
            return None
        fn.argtypes = argtypes
        fn.restype = restype
        return fn

    def dotnet(self) -> None:
        self._dll._DotNET()

    def last_error(self, machine_number: int) -> int | None:
        error_code = self._long_t(0)
        ok = bool(self._dll._GetLastError(machine_number, ctypes.byref(error_code)))
        if not ok:
            return None
        return int(error_code.value)

    def connect_tcpip(self, machine_number: int, ip_address: str, port: int, password: int) -> None:
        ip_ptr = self._alloc_bstr(ip_address)
        try:
            ok = bool(
                self._dll._ConnectTcpip(
                    machine_number,
                    ctypes.byref(ip_ptr),
                    port,
                    password,
                )
            )
        finally:
            self._free_bstr(ip_ptr)

        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "ConnectTcpip failed"))

    def disconnect(self, machine_number: int) -> None:
        self._dll._Disconnect(machine_number)

    def enable_device(self, machine_number: int, enabled: bool) -> None:
        flag = 1 if enabled else 0
        ok = bool(self._dll._EnableDevice(machine_number, flag))
        if not ok:
            state = "enable" if enabled else "disable"
            raise MachineSdkError(self._format_last_error(machine_number, f"EnableDevice({state}) failed"))

    def enable_user(
        self,
        machine_number: int,
        user_id: int,
        *,
        e_machine_number: int = 1,
        backup_number: int = 0,
        enabled: bool = True,
    ) -> None:
        flag = 1 if enabled else 0
        ok = bool(
            self._dll._EnableUser(
                machine_number,
                user_id,
                e_machine_number,
                backup_number,
                flag,
            )
        )
        if not ok:
            state = "enable" if enabled else "disable"
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"EnableUser({state}) failed for user_id={user_id}",
                )
            )

    def set_enroll_data1(
        self,
        machine_number: int,
        user_id: int,
        *,
        backup_number: int = 0,
        machine_privilege: int = 0,
        credential_value: int = 0,
        template_words: list[int] | None = None,
    ) -> None:
        # Vendor samples allocate (1404 + 12) / 4 signed 32-bit words for the enroll data buffer.
        words = template_words if template_words is not None else [0] * 354
        if not words:
            words = [0] * 354
        buffer_type = self._long_t * len(words)
        buffer = buffer_type(*[int(value) for value in words])
        data_ptr = ctypes.cast(buffer, ctypes.c_void_p)
        ok = bool(
            self._dll._SetEnrollData1(
                machine_number,
                user_id,
                backup_number,
                machine_privilege,
                ctypes.byref(data_ptr),
                credential_value,
            )
        )
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"SetEnrollData1 failed for user_id={user_id}, backup_number={backup_number}",
                )
            )

    def get_user_name(self, machine_number: int, user_id: int) -> str:
        name_ptr = self._bstr_t()
        try:
            ok = bool(self._dll._GetUserName1(machine_number, user_id, ctypes.byref(name_ptr)))
            value = self._bstr_to_string(name_ptr)
        finally:
            self._free_bstr(name_ptr)

        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"GetUserName1 failed for user_id={user_id}",
                )
            )
        return value

    def list_all_user_ids(self, machine_number: int) -> list[dict[str, int | bool]]:
        ok = bool(self._dll._ReadAllUserID(machine_number))
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "ReadAllUserID failed"))

        rows: list[dict[str, int | bool]] = []
        while True:
            user_id = self._long_t(0)
            e_machine_number = self._long_t(0)
            backup_number = self._long_t(0)
            machine_privilege = self._long_t(0)
            enabled = self._long_t(0)

            has_row = bool(
                self._dll._GetAllUserID(
                    machine_number,
                    ctypes.byref(user_id),
                    ctypes.byref(e_machine_number),
                    ctypes.byref(backup_number),
                    ctypes.byref(machine_privilege),
                    ctypes.byref(enabled),
                )
            )
            if not has_row:
                break

            rows.append(
                {
                    "user_id": int(user_id.value),
                    "e_machine_number": int(e_machine_number.value),
                    "backup_number": int(backup_number.value),
                    "machine_privilege": int(machine_privilege.value),
                    "enabled": int(enabled.value) != 0,
                }
            )
        return rows

    def delete_enroll_data(
        self,
        machine_number: int,
        user_id: int,
        *,
        e_machine_number: int = 1,
        backup_number: int = 0,
    ) -> None:
        ok = bool(
            self._dll._DeleteEnrollData(
                machine_number,
                user_id,
                e_machine_number,
                backup_number,
            )
        )
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"DeleteEnrollData failed for user_id={user_id}",
                )
            )

    def get_device_time(self, machine_number: int) -> datetime:
        year = self._long_t(0)
        month = self._long_t(0)
        day = self._long_t(0)
        hour = self._long_t(0)
        minute = self._long_t(0)
        second = self._long_t(0)
        _day_of_week = self._long_t(0)

        ok = bool(
            self._dll._GetDeviceTime(
                machine_number,
                ctypes.byref(year),
                ctypes.byref(month),
                ctypes.byref(day),
                ctypes.byref(hour),
                ctypes.byref(minute),
                ctypes.byref(second),
                ctypes.byref(_day_of_week),
            )
        )
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GetDeviceTime failed"))

        return datetime(
            int(year.value),
            int(month.value),
            int(day.value),
            int(hour.value),
            int(minute.value),
            int(second.value),
        )

    def set_device_time(self, machine_number: int, device_time: datetime) -> None:
        if self._fn_set_device_time1 is None:
            raise MachineSdkError("SetDeviceTime1 is not available in this SDK DLL.")
        ok = bool(
            self._fn_set_device_time1(
                machine_number,
                int(device_time.year),
                int(device_time.month),
                int(device_time.day),
                int(device_time.hour),
                int(device_time.minute),
                int(device_time.second),
            )
        )
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "SetDeviceTime1 failed"))

    def get_serial_number(self, machine_number: int) -> str:
        if self._fn_get_serial_number is None:
            raise MachineSdkError("GetSerialNumber is not available in this SDK DLL.")
        serial_ptr = self._bstr_t()
        try:
            ok = bool(self._fn_get_serial_number(machine_number, ctypes.byref(serial_ptr)))
            value = self._bstr_to_string(serial_ptr)
        finally:
            self._free_bstr(serial_ptr)
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GetSerialNumber failed"))
        return value

    def get_device_model(self, machine_number: int) -> dict[str, int]:
        if self._fn_get_device_model is None:
            raise MachineSdkError("GetDeviceModel is not available in this SDK DLL.")
        is_big_user_id = self._long_t(0)
        company_type = self._long_t(0)
        machine_type = self._long_t(0)
        machine_version = self._long_t(0)
        ok = bool(
            self._fn_get_device_model(
                machine_number,
                ctypes.byref(is_big_user_id),
                ctypes.byref(company_type),
                ctypes.byref(machine_type),
                ctypes.byref(machine_version),
            )
        )
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GetDeviceModel failed"))
        return {
            "is_big_user_id": int(is_big_user_id.value),
            "company_type": int(company_type.value),
            "machine_type": int(machine_type.value),
            "machine_version": int(machine_version.value),
        }

    def get_backup_number(self, machine_number: int) -> int:
        if self._fn_get_backup_number is None:
            raise MachineSdkError("GetBackupNumber is not available in this SDK DLL.")
        return int(self._fn_get_backup_number(machine_number))

    def get_internal_fw_version(self, machine_number: int) -> int:
        if self._fn_get_internal_fw_ver is None:
            raise MachineSdkError("GetInternalFwVer is not available in this SDK DLL.")
        return int(self._fn_get_internal_fw_ver(machine_number))

    def list_general_logs(self, machine_number: int, *, limit: int | None = None) -> list[dict[str, int | str]]:
        if self._fn_read_all_glog_data is None or self._fn_get_all_glog_data is None:
            raise MachineSdkError("ReadAllGLogData/GetAllGLogData is not available in this SDK DLL.")
        ok = bool(self._fn_read_all_glog_data(machine_number))
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "ReadAllGLogData failed"))

        rows: list[dict[str, int | str]] = []
        max_rows = int(limit) if limit is not None else None
        while True:
            t_machine_number = self._long_t(0)
            enroll_number = self._long_t(0)
            e_machine_number = self._long_t(0)
            verify_mode = self._long_t(0)
            year = self._long_t(0)
            month = self._long_t(0)
            day = self._long_t(0)
            hour = self._long_t(0)
            minute = self._long_t(0)
            second = self._long_t(0)
            has_row = bool(
                self._fn_get_all_glog_data(
                    machine_number,
                    ctypes.byref(t_machine_number),
                    ctypes.byref(enroll_number),
                    ctypes.byref(e_machine_number),
                    ctypes.byref(verify_mode),
                    ctypes.byref(year),
                    ctypes.byref(month),
                    ctypes.byref(day),
                    ctypes.byref(hour),
                    ctypes.byref(minute),
                    ctypes.byref(second),
                )
            )
            if not has_row:
                break

            y = int(year.value)
            m = int(month.value)
            d = int(day.value)
            hh = int(hour.value)
            mm = int(minute.value)
            ss = int(second.value)
            rows.append(
                {
                    "t_machine_number": int(t_machine_number.value),
                    "enroll_number": int(enroll_number.value),
                    "e_machine_number": int(e_machine_number.value),
                    "verify_mode": int(verify_mode.value),
                    "year": y,
                    "month": m,
                    "day": d,
                    "hour": hh,
                    "minute": mm,
                    "second": ss,
                    "log_datetime": f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}",
                }
            )
            if max_rows is not None and len(rows) >= max_rows:
                break
        return rows

    def get_bound_capabilities(self) -> dict[str, bool]:
        return {
            "SetDeviceTime1": self._fn_set_device_time1 is not None,
            "GetSerialNumber": self._fn_get_serial_number is not None,
            "GetDeviceModel": self._fn_get_device_model is not None,
            "ReadAllGLogData": self._fn_read_all_glog_data is not None,
            "GetAllGLogData": self._fn_get_all_glog_data is not None,
            "GetBackupNumber": self._fn_get_backup_number is not None,
            "GetInternalFwVer": self._fn_get_internal_fw_ver is not None,
        }

    def set_user_name(self, machine_number: int, user_id: int, user_name: str) -> None:
        name_ptr = self._alloc_bstr(user_name)
        try:
            ok = bool(self._dll._SetUserName1(machine_number, user_id, ctypes.byref(name_ptr)))
        finally:
            self._free_bstr(name_ptr)
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"SetUserName1 failed for user_id={user_id}",
                )
            )

    def set_user_info(
        self,
        machine_number: int,
        user_id: int,
        timezone1: int,
        timezone2: int,
        group_no: int,
        card_no: int,
    ) -> str:
        xml = ""
        xml = self.xml_add_string(xml, "REQUEST", "SetUserInfo")
        xml = self.xml_add_string(xml, "MSGTYPE", "request")
        xml = self.xml_add_int(xml, "MachineID", machine_number)
        xml = self.xml_add_int(xml, "UserID", user_id)
        xml = self.xml_add_int(xml, "Timezone1", timezone1)
        xml = self.xml_add_int(xml, "Timezone2", timezone2)
        xml = self.xml_add_int(xml, "GroupNo", group_no)

        low = card_no & 0xFFFFFFFF
        high = (card_no >> 32) & 0xFFFFFFFF
        xml = self.xml_add_string(xml, "CardNo_Low", str(low))
        xml = self.xml_add_string(xml, "CardNo_High", str(high))

        return self.general_operation_xml(machine_number, xml)

    def general_operation_xml(self, machine_number: int, request_xml: str) -> str:
        xml_ptr = self._alloc_bstr(request_xml)
        try:
            ok = bool(self._dll._GeneralOperationXML(machine_number, ctypes.byref(xml_ptr)))
            response_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)

        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GeneralOperationXML failed"))
        return response_xml

    def xml_add_string(self, xml: str, tag: str, value: str) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddString(ctypes.byref(xml_ptr), tag, value))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)

        if not ok:
            raise MachineSdkError(f"XML_AddString failed for tag={tag}")
        return out_xml

    def xml_add_int(self, xml: str, tag: str, value: int) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddInt(ctypes.byref(xml_ptr), tag, value))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)

        if not ok:
            raise MachineSdkError(f"XML_AddInt failed for tag={tag}")
        return out_xml

    def xml_add_long(self, xml: str, tag: str, value: int) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddLong(ctypes.byref(xml_ptr), tag, int(value)))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_AddLong failed for tag={tag}")
        return out_xml

    def xml_add_boolean(self, xml: str, tag: str, value: bool) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddBoolean(ctypes.byref(xml_ptr), tag, 1 if value else 0))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_AddBoolean failed for tag={tag}")
        return out_xml

    def xml_add_binary_byte(self, xml: str, tag: str, data: bytes) -> str:
        payload = bytes(data or b"")
        raw_buffer = (ctypes.c_ubyte * len(payload))(*payload) if payload else None
        data_ptr = ctypes.cast(raw_buffer, ctypes.c_void_p) if raw_buffer is not None else ctypes.c_void_p()
        xml_ptr = self._alloc_bstr(xml)
        try:
            try:
                ok = bool(
                    self._dll._XML_AddBinaryByte(
                        ctypes.byref(xml_ptr),
                        tag,
                        ctypes.byref(data_ptr),
                        len(payload),
                    )
                )
            except OSError as exc:
                raise MachineSdkError(f"XML_AddBinaryByte failed for tag={tag}: {exc}") from exc
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_AddBinaryByte failed for tag={tag}")
        return out_xml

    def xml_parse_string(self, xml: str, tag: str) -> str:
        xml_ptr = self._alloc_bstr(xml)
        value_ptr = self._bstr_t()
        try:
            ok = bool(self._dll._XML_ParseString(ctypes.byref(xml_ptr), tag, ctypes.byref(value_ptr)))
            value = self._bstr_to_string(value_ptr)
        finally:
            self._free_bstr(xml_ptr)
            self._free_bstr(value_ptr)
        if not ok:
            raise MachineSdkError(f"XML_ParseString failed for tag={tag}")
        return value

    def xml_parse_int(self, xml: str, tag: str) -> int:
        xml_ptr = self._alloc_bstr(xml)
        try:
            value = int(self._dll._XML_ParseInt(ctypes.byref(xml_ptr), tag))
        finally:
            self._free_bstr(xml_ptr)
        return value

    def xml_parse_long(self, xml: str, tag: str) -> int:
        xml_ptr = self._alloc_bstr(xml)
        try:
            value = int(self._dll._XML_ParseLong(ctypes.byref(xml_ptr), tag))
        finally:
            self._free_bstr(xml_ptr)
        return value

    def xml_parse_boolean(self, xml: str, tag: str) -> bool:
        xml_ptr = self._alloc_bstr(xml)
        try:
            value = bool(self._dll._XML_ParseBoolean(ctypes.byref(xml_ptr), tag))
        finally:
            self._free_bstr(xml_ptr)
        return value

    def xml_parse_binary_byte_base64(self, xml: str, tag: str, length: int) -> str:
        safe_len = max(1, int(length))
        buffer = (ctypes.c_ubyte * safe_len)()
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_ParseBinaryByte(ctypes.byref(xml_ptr), tag, buffer, safe_len))
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_ParseBinaryByte failed for tag={tag}")
        return b64encode(bytes(buffer)).decode("ascii")

    # Backward-compatible private aliases used by existing code.
    def _xml_add_string(self, xml: str, tag: str, value: str) -> str:
        return self.xml_add_string(xml, tag, value)

    def _xml_add_int(self, xml: str, tag: str, value: int) -> str:
        return self.xml_add_int(xml, tag, value)

    def _alloc_bstr(self, value: str) -> ctypes.c_void_p:
        # SysAllocString may come back as a plain integer pointer value.
        # Wrap it as c_void_p so ctypes.byref(...) works reliably.
        raw_ptr = self._ole.SysAllocString(value or "")
        ptr = self._bstr_t(raw_ptr)
        if not ptr and value:
            raise MachineSdkError("SysAllocString failed.")
        return ptr

    def _free_bstr(self, value: ctypes.c_void_p) -> None:
        if value:
            self._ole.SysFreeString(value)

    @staticmethod
    def _bstr_to_string(value: ctypes.c_void_p) -> str:
        if not value:
            return ""
        return ctypes.wstring_at(value)

    def _format_last_error(self, machine_number: int, message: str) -> str:
        code = self.last_error(machine_number)
        if code is None:
            return message
        return f"{message} (code={code})"
