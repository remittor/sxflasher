import sys
import errno
import logging
import array

from ctypes import *
import ctypes.util

from ctypes.wintypes import *
import winreg as wr

_internal_module = False
try:
    from .. import backend
    _internal_module = True   # this module placed into usb/backend/
except ImportError:
    import pyusb as usb

if _internal_module:
    from .. import util
    from .._debug import methodtrace
    from .. import _interop
    from .. import _objfinalizer
    from .. import libloader
    from ..core import USBError, USBTimeoutError
else:
    import pyusb.backend as backend
    import pyusb.util as util
    from pyusb._debug import methodtrace
    import pyusb._interop as _interop
    import pyusb._objfinalizer as _objfinalizer
    import pyusb.libloader as libloader
    from pyusb.core import USBError, USBTimeoutError


__author__ = 'remittor'

__all__ = [ 'get_backend', 'get_usb_driver_info' ]

_logger = logging.getLogger('usb.backend.ggsomc')

_lib = None
_ctx = None

# ==================================================================================

def is_32bit():
    return sizeof(c_void_p) == 4

TRUE  = 1
FALSE = 0
NULL  = 0

HDEVINFO  = HANDLE
INVALID_HANDLE_VALUE = HANDLE(-1).value

ULONG_PTR = c_ulonglong
if is_32bit():
    ULONG_PTR = c_ulong

DIGCF_PRESENT = 2
DIGCF_DEVICEINTERFACE = 16

SPDRP_HARDWAREID = 1
SPDRP_FRIENDLYNAME = 12
SPDRP_LOCATION_INFORMATION = 13

# Exception/Status codes from winuser.h and winnt.h
STATUS_WAIT_0 = 0
STATUS_ABANDONED_WAIT_0 = 128
STATUS_USER_APC = 192
STATUS_TIMEOUT = 258
STATUS_PENDING = 259

WAIT_FAILED = -1
WAIT_OBJECT_0 = STATUS_WAIT_0 + 0

WAIT_ABANDONED = STATUS_ABANDONED_WAIT_0 + 0
WAIT_ABANDONED_0 = STATUS_ABANDONED_WAIT_0 + 0

WAIT_TIMEOUT = STATUS_TIMEOUT
WAIT_IO_COMPLETION = STATUS_USER_APC
STILL_ACTIVE = STATUS_PENDING

ERROR_SUCCESS = 0
ERROR_HANDLE_EOF = 38
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259
ERROR_IO_INCOMPLETE = 996
ERROR_IO_PENDING = 997


class GUID(Structure):
    _fields_ = [
        ('Data1', c_uint32),
        ('Data2', c_ushort),
        ('Data3', c_ushort),
        ('Data4', c_ubyte*8),
    ]
    def __str__(self):
        return "{%08x-%04x-%04x-%s-%s}" % (
            self.Data1,
            self.Data2,
            self.Data3,
            ''.join(["%02x" % d for d in self.Data4[:2]]),
            ''.join(["%02x" % d for d in self.Data4[2:]]),
        )

GUID_DEVINTERFACE_USB_DEVICE = GUID(0xA5DCBF10, 0x6530, 0x11D2, (c_ubyte*8)(0x90, 0x1F, 0x00, 0xC0, 0x4F, 0xB9, 0x51, 0xED))
        
class SP_DEVINFO_DATA(Structure):
    _fields_ = [
        ('cbSize', DWORD),
        ('ClassGuid', GUID),
        ('DevInst', DWORD),
        ('Reserved', ULONG_PTR),
    ]
    def __str__(self):
        return "ClassGuid:%s DevInst:%s" % (self.ClassGuid, self.DevInst)

PSP_DEVINFO_DATA = POINTER(SP_DEVINFO_DATA)

class SP_DEVICE_INTERFACE_DATA(Structure):
    _fields_ = [
        ('cbSize', DWORD),
        ('InterfaceClassGuid', GUID),
        ('Flags', DWORD),
        ('Reserved', ULONG_PTR),
    ]
    def __str__(self):
        return "InterfaceClassGuid:%s Flags:%s" % (self.InterfaceClassGuid, self.Flags)

PSP_DEVICE_INTERFACE_DATA = POINTER(SP_DEVICE_INTERFACE_DATA)


MAX_DEVICE_PATH_LEN = 2000

class SP_DEVICE_INTERFACE_DETAIL_DATA_A(Structure):
    _fields_ = [
        ('cbSize', DWORD),
        ('DevicePath', CHAR * MAX_DEVICE_PATH_LEN),
    ]
    _pack_ = 1
    def __str__(self):
        return f'DevicePath: "{self.DevicePath.decode("latin-1")}"'

PSP_DEVICE_INTERFACE_DETAIL_DATA_A = POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_A)

class SECURITY_ATTRIBUTES(Structure):
    _fields_ = [
        ('nLength', DWORD),
        ('lpSecurityDescriptor', LPVOID),
        ('bInheritHandle', BOOL),
    ]

LPSECURITY_ATTRIBUTES = POINTER(SECURITY_ATTRIBUTES)


class _OFFSET(Structure):
    _fields_ = [
        ("Offset",     DWORD),
        ("OffsetHigh", DWORD)
    ]

class _OFFSET_UNION(Union):
    _anonymous_ = [ "_offset" ]
    _fields_ = [
        ("_offset", _OFFSET),
        ("Pointer", LPVOID)
    ]

class OVERLAPPED(ctypes.Structure):
    _anonymous_ = [ "_offset_union" ]
    _fields_ = [
        ("Internal",      ULONG_PTR),
        ("InternalHigh",  ULONG_PTR),
        ("_offset_union", _OFFSET_UNION),
        ("hEvent",        HANDLE),
    ]

LPOVERLAPPED = POINTER(OVERLAPPED)

# ==================================================================================

class _usb_endpoint_desc(Structure):
    _fields_ = [('bLength', c_uint8),
                ('bDescriptorType', c_uint8),
                ('bEndpointAddress', c_uint8),
                ('bmAttributes', c_uint8),
                ('wMaxPacketSize', c_uint16),
                ('bInterval', c_uint8),
                ('bRefresh', c_uint8),
                ('bSynchAddress', c_uint8)]

class _usb_interface_desc(Structure):
    _fields_ = [('bLength', c_uint8),
                ('bDescriptorType', c_uint8),
                ('bInterfaceNumber', c_uint8),
                ('bAlternateSetting', c_uint8),
                ('bNumEndpoints', c_uint8),
                ('bInterfaceClass', c_uint8),
                ('bInterfaceSubClass', c_uint8),
                ('bInterfaceProtocol', c_uint8),
                ('iInterface', c_uint8)]

class _usb_config_desc(Structure):
    _fields_ = [('bLength', c_uint8),
                ('bDescriptorType', c_uint8),
                ('wTotalLength', c_uint16),
                ('bNumInterfaces', c_uint8),
                ('bConfigurationValue', c_uint8),
                ('iConfiguration', c_uint8),
                ('bmAttributes', c_uint8),
                ('bMaxPower', c_uint8)]

class _usb_device_desc(Structure):
    _fields_ = [('bLength', c_uint8),
                ('bDescriptorType', c_uint8),
                ('bcdUSB', c_uint16),
                ('bDeviceClass', c_uint8),
                ('bDeviceSubClass', c_uint8),
                ('bDeviceProtocol', c_uint8),
                ('bMaxPacketSize0', c_uint8),
                ('idVendor', c_uint16),
                ('idProduct', c_uint16),
                ('bcdDevice', c_uint16),
                ('iManufacturer', c_uint8),
                ('iProduct', c_uint8),
                ('iSerialNumber', c_uint8),
                ('bNumConfigurations', c_uint8)]

# ==================================================================================

def _load_library(find_library = None):
    return WinDLL("SetupAPI.dll")

def _setup_prototypes(lib):
    lib.GetProcessHeap = windll.kernel32.GetProcessHeap
    lib.GetProcessHeap.argtypes = [ ]
    lib.GetProcessHeap.restype = HANDLE

    lib.HeapAlloc = windll.kernel32.HeapAlloc
    lib.HeapAlloc.argtypes = [
        HANDLE,      # hHeap
        DWORD,       # dwFlags
        c_size_t     # AllocSize
    ]
    lib.HeapAlloc.restype = LPVOID

    lib.HeapFree = windll.kernel32.HeapFree
    lib.HeapFree.argtypes = [
        HANDLE,      # hHeap
        DWORD,       # dwFlags
        LPVOID       # lpMem
    ]
    lib.HeapFree.restype = BOOL

    lib.HeapAlloc = windll.kernel32.HeapAlloc
    lib.HeapAlloc.argtypes = [
        HANDLE,
        DWORD,
        c_size_t
    ]
    lib.HeapAlloc.restype = LPVOID

    lib.SetupDiGetClassDevsW.argtypes = [
        POINTER(GUID),   # ClassGuid
        LPCWSTR,         # Enumerator
        HWND,            # hwndParent
        DWORD            # Flags
    ]
    lib.SetupDiGetClassDevsW.restype = HDEVINFO

    lib.SetupDiDestroyDeviceInfoList.argtypes = [
        HDEVINFO   # DeviceInfoSet
    ]
    lib.SetupDiDestroyDeviceInfoList.restype = BOOL

    lib.SetupDiEnumDeviceInterfaces.argtypes = [
        HDEVINFO,                     # hDev
        PSP_DEVINFO_DATA,             # DeviceInfo
        POINTER(GUID),                # ClassGuid
        DWORD,                        # MemberIndex
        PSP_DEVICE_INTERFACE_DATA     # DeviceInterfaceData
    ]
    lib.SetupDiEnumDeviceInterfaces.restype = BOOL

    lib.SetupDiGetDeviceInterfaceDetailA.argtypes = [
        HDEVINFO,                            # DeviceInfoSet
        PSP_DEVICE_INTERFACE_DATA,           # DeviceInterfaceData
        PSP_DEVICE_INTERFACE_DETAIL_DATA_A,  # DeviceInterfaceDetailData
        DWORD,                               # DeviceInterfaceDetailDataSize
        PDWORD,                              # RequiredSize
        PSP_DEVINFO_DATA                     # DeviceInfoData
    ]
    lib.SetupDiGetDeviceInterfaceDetailA.restype = BOOL
    
    lib.CreateFileA = windll.kernel32.CreateFileA
    lib.CreateFileA.argtypes = [
        LPCSTR,                # lpFileName,
        DWORD,                 # dwDesiredAccess,
        DWORD,                 # dwShareMode,
        LPSECURITY_ATTRIBUTES, # lpSecurityAttributes,
        DWORD,                 # dwCreationDisposition,
        DWORD,                 # dwFlagsAndAttributes,
        HANDLE                 # hTemplateFile
    ]
    lib.CreateFileA.restype = HANDLE

    lib.CloseHandle = windll.kernel32.CloseHandle
    lib.CloseHandle.argtypes = [ HANDLE ]
    lib.CloseHandle.restype = BOOL

    lib.CreateEventA = windll.kernel32.CreateEventA
    lib.CreateEventA.argtypes = [
        LPSECURITY_ATTRIBUTES, # lpEventAttributes,
        BOOL,                  # bManualReset,
        BOOL,                  # bInitialState,
        LPCSTR                 # lpName
    ]
    lib.CloseHandle.restype = BOOL 

    lib.SetEvent = windll.kernel32.SetEvent
    lib.SetEvent.argtypes = [ HANDLE ]   # hEvent
    lib.SetEvent.restype = BOOL

    lib.ResetEvent = windll.kernel32.ResetEvent
    lib.ResetEvent.argtypes = [ HANDLE ]   # hEvent
    lib.ResetEvent.restype = BOOL

    lib.CancelIo = windll.kernel32.CancelIo
    lib.CancelIo.argtypes = [ HANDLE ]   # hFile
    lib.CancelIo.restype = BOOL

    lib.WaitForSingleObject = windll.kernel32.WaitForSingleObject
    lib.WaitForSingleObject.argtypes = [
        HANDLE,  # hHandle,
        DWORD    # dwMilliseconds
    ]
    lib.WaitForSingleObject.restype = DWORD

    lib.GetOverlappedResult = windll.kernel32.GetOverlappedResult
    lib.GetOverlappedResult.argtypes = [
        HANDLE,       # hFile,
        LPOVERLAPPED, # lpOverlapped,
        LPDWORD,      # lpNumberOfBytesTransferred,
        BOOL,         # bWait
    ]    
    lib.GetOverlappedResult.restype = BOOL 

    lib.ReadFile = windll.kernel32.ReadFile
    lib.ReadFile.argtypes = [
        HANDLE,       # hFile,
        LPVOID,       # lpBuffer,
        DWORD,        # nNumberOfBytesToRead,
        LPDWORD,      # lpNumberOfBytesRead,
        LPOVERLAPPED  # lpOverlapped
    ]
    lib.ReadFile.restype = BOOL 

    lib.WriteFile = windll.kernel32.WriteFile
    lib.WriteFile.argtypes = [
        HANDLE,       # hFile,
        LPVOID,       # lpBuffer,
        DWORD,        # nNumberOfBytesToWrite,
        LPDWORD,      # lpNumberOfBytesWritten,
        LPOVERLAPPED  # lpOverlapped
    ]
    lib.WriteFile.restype = BOOL 


# wrap a device
class _Device(_objfinalizer.AutoFinalizedObject):
    def __init__(self, gg, hdevinf, did):
        self.gg = gg
        self.hdevinf = hdevinf
        self.did = did
        self.vid = 0
        self.pid = 0
        self.path = b''
        self.wMaxPacketSize = 0

    def _finalize_object(self):
        pass

class _DevIterator(_objfinalizer.AutoFinalizedObject):
    def __init__(self, gg):
        self.gg = gg
        self.hdevinf = None
        
        self.dev_iface_num = -1
        interfaceClassGuid = byref(GUID_DEVINTERFACE_USB_DEVICE)
        flags = DIGCF_DEVICEINTERFACE | DIGCF_PRESENT
        hdev = _lib.SetupDiGetClassDevsW(interfaceClassGuid, None, NULL, flags)
        if not hdev:
            raise RuntimeError(f'Cannot open USB enumerator! Error: {WinError()}')
            
        self.hdevinf = hdev        

    def __iter__(self):
        if self.hdevinf is None:
            raise
            
        while True:
            interfaceClassGuid = byref(GUID_DEVINTERFACE_USB_DEVICE)
            self.dev_iface_num += 1
            dwMemberIdx = DWORD(self.dev_iface_num)
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = sizeof(did)
            ret = _lib.SetupDiEnumDeviceInterfaces(self.hdevinf, None, interfaceClassGuid, dwMemberIdx, byref(did))
            if not ret:
                if GetLastError() == ERROR_NO_MORE_ITEMS:
                    return _Device(self.gg, None, None) # StopIteration
                raise RuntimeError(f'Cannot enum USB devices! Error: {WinError()}')
            yield _Device(self.gg, self.hdevinf, did)
    
    def _finalize_object(self):
        if self.hdevinf:
            _lib.SetupDiDestroyDeviceInfoList(self.hdevinf)
            self.hdevinf = None

class _DeviceHandle(object):
    def __init__(self, dev, hdev):
        self.dev = dev
        self.path = dev.path
        self.hdev = hdev
        self.oRead = OVERLAPPED()
        self.oRead.hEvent = _lib.CreateEventA(None, TRUE, FALSE, None)
        self.oWrite = OVERLAPPED()
        self.oWrite.hEvent = _lib.CreateEventA(None, TRUE, FALSE, None)

    def __del__(self):
        if self.hdev:
            _lib.CloseHandle(self.hdev)

        _lib.CloseHandle(self.oRead.hEvent)
        _lib.CloseHandle(self.oWrite.hEvent)

class _GordonGateUsb(backend.IBackend):
    @methodtrace(_logger)
    def __init__(self, lib, xdev):
        backend.IBackend.__init__(self)
        self.xdev = xdev
        self.lib = lib
        self.ctx = None

    @methodtrace(_logger)
    def _finalize_object(self):
        pass

    @methodtrace(_logger)
    def enumerate_devices(self):
        return _DevIterator(self)

    @methodtrace(_logger)
    def get_device_descriptor(self, dev):
        if dev.hdevinf is None or dev.did is None:
            return None

        idd = SP_DEVICE_INTERFACE_DETAIL_DATA_A()
        idd.cbSize = 6 if sizeof(c_void_p) == 4 else 8

        size = sizeof(idd)
        
        devinfo = SP_DEVINFO_DATA()
        devinfo.cbSize = sizeof(devinfo)
        
        rc = _lib.SetupDiGetDeviceInterfaceDetailA(dev.hdevinf, byref(dev.did), byref(idd), size, None, byref(devinfo))
        if not rc:
            raise RuntimeError(f'Cannot get USB device details! Error: {WinError()}')

        #print('idd: ', idd)
        dev.path = idd.DevicePath[:]  # copy bytes

        desc = _usb_device_desc()
        desc.bus = None
        desc.address = None
        desc.port_number = None
        desc.port_numbers = None
        desc.speed = None

        vid = 0
        pid = 0
        vm = b'usb#vid_'
        v = dev.path.find(vm)
        if v >= 0:
            v += len(vm)
            vid = int(dev.path[v:v+4].decode(), 16)
            pm = b'&pid_'
            p = dev.path.find(pm, v)
            if p > 0:
                p += len(pm)
                pid = int(dev.path[p:p+4].decode(), 16)

        if vid and pid:
            dev.vid = vid
            dev.pid = pid
            desc.idVendor = vid
            desc.idProduct = pid
            
        if vid == self.xdev.idVendor and pid == self.xdev.idProduct:    
            desc = self.xdev
            desc.bLength = self.xdev.bLength 
            desc.bDescriptorType = self.xdev.bDescriptorType 
            desc.bcdUSB = self.xdev.bcdUSB 
            desc.bcdDevice = self.xdev.bcdDevice 
            desc.bDeviceClass = self.xdev.bDeviceClass 
            desc.bDeviceSubClass = self.xdev.bDeviceSubClass 
            desc.bDeviceProtocol = self.xdev.bDeviceProtocol 
            desc.bMaxPacketSize0 = self.xdev.bMaxPacketSize0 
            desc.iManufacturer = self.xdev.iManufacturer
            desc.iProduct = self.xdev.iProduct
            desc.iSerialNumber = self.xdev.iSerialNumber
            
            desc.bNumConfigurations = self.xdev.bNumConfigurations
            
            desc.bus = self.xdev.bus
            desc.address = self.xdev.bus
            desc.port_number = self.xdev.port_number
            desc.port_numbers = self.xdev.port_numbers
            desc.speed = self.xdev.speed
            
        return desc

    @methodtrace(_logger)
    def get_configuration_descriptor(self, dev, config):
        desc = _usb_config_desc()
        desc.extra_descriptors = None
        
        if dev.vid == self.xdev.idVendor and dev.pid == self.xdev.idProduct:
            cfg = self.xdev[config]
            desc.bLength = cfg.bLength
            desc.bDescriptorType = cfg.bDescriptorType
            desc.wTotalLength = cfg.wTotalLength
            desc.bNumInterfaces = cfg.bNumInterfaces
            desc.bConfigurationValue = cfg.bConfigurationValue
            desc.iConfiguration = cfg.iConfiguration
            desc.bmAttributes = cfg.bmAttributes
            desc.bMaxPower = cfg.bMaxPower
        
        return desc

    @methodtrace(_logger)
    def get_interface_descriptor(self, dev, intf, alt, config):
        desc = _usb_interface_desc()
        desc.extra_descriptors = None
        
        if dev.vid == self.xdev.idVendor and dev.pid == self.xdev.idProduct:
            cfg = self.xdev[config]
            iface = cfg[ (intf, alt) ]
            desc.bLength = iface.bLength
            desc.bDescriptorType = iface.bDescriptorType
            desc.bInterfaceNumber = iface.bInterfaceNumber
            desc.bAlternateSetting = iface.bAlternateSetting
            desc.bNumEndpoints = iface.bNumEndpoints
            desc.bInterfaceClass = iface.bInterfaceClass
            desc.bInterfaceSubClass = iface.bInterfaceSubClass
            desc.bInterfaceProtocol = iface.bInterfaceProtocol
            desc.iInterface = iface.iInterface

        return desc

    @methodtrace(_logger)
    def get_endpoint_descriptor(self, dev, ep, intf, alt, config):
        desc = _usb_endpoint_desc()
        desc.extra_descriptors = None
        
        if dev.vid == self.xdev.idVendor and dev.pid == self.xdev.idProduct:
            cfg = self.xdev[config]
            iface = cfg[ (intf, alt) ]
            epnt = iface[ep]
            desc.bLength = epnt.bLength
            desc.bDescriptorType = epnt.bDescriptorType
            desc.bEndpointAddress = epnt.bEndpointAddress
            desc.bmAttributes = epnt.bmAttributes
            desc.wMaxPacketSize = epnt.wMaxPacketSize
            desc.bInterval = epnt.bInterval
            desc.bRefresh = epnt.bRefresh
            desc.bSynchAddress = epnt.bSynchAddress
            
            if dev.wMaxPacketSize == 0 or dev.wMaxPacketSize > desc.wMaxPacketSize:
                dev.wMaxPacketSize = desc.wMaxPacketSize
        
        return desc

    @methodtrace(_logger)
    def open_device(self, dev):
        #print(f'open_device: {dev.path}')
        
        lpFileName = dev.path
        
        GENERIC_WRITE    = 0x40000000
        GENERIC_READ     = 0x80000000
        dwAccess = GENERIC_WRITE | GENERIC_READ
        
        FILE_SHARE_READ  = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        dwShareMode = FILE_SHARE_READ | FILE_SHARE_WRITE
        
        lpSecAttr = None
        
        OPEN_EXISTING = 3
        dwDispos = OPEN_EXISTING
        
        FILE_FLAG_OVERLAPPED = 0x40000000
        dwFlags = FILE_FLAG_OVERLAPPED        
        
        dev_handle = _lib.CreateFileA(lpFileName, dwAccess, dwShareMode, lpSecAttr, dwDispos, dwFlags, None)
        if dev_handle == INVALID_HANDLE_VALUE:
            raise RuntimeError(f'Cannot open USB device {lpFileName}\r\nError: {WinError()}')
        
        return _DeviceHandle(dev, dev_handle)

    @methodtrace(_logger)
    def close_device(self, dev_handle):
        _lib.CloseHandle(dev_handle.hdev)

    @methodtrace(_logger)
    def set_configuration(self, dev_handle, config_value):
        # FIXME
        pass

    @methodtrace(_logger)
    def get_configuration(self, dev_handle):
        # FIXME
        return None

    @methodtrace(_logger)
    def set_interface_altsetting(self, dev_handle, intf, altsetting):
        # FIXME
        raise Exception('not implemented')

    @methodtrace(_logger)
    def claim_interface(self, dev_handle, intf):
        # FIXME
        pass

    @methodtrace(_logger)
    def release_interface(self, dev_handle, intf):
        # FIXME
        pass

    @methodtrace(_logger)
    def bulk_write(self, dev_handle, ep, intf, data, timeout):
        payload, bufsize = data.buffer_info()
        
        maxPacketSize = dev_handle.dev.wMaxPacketSize
        hdev = dev_handle.hdev
        if maxPacketSize < 128:
            raise RuntimeError(f'Value maxPacketSize = {maxPacketSize} is too small')
        
        pos = 0
        while True:
            evt = dev_handle.oWrite
            evt.Internal = 0
            evt.InternalHigh = 0
            evt.Offset = 0
            evt.OffsetHigh = 0
            _lib.ResetEvent(evt.hEvent)

            dwWait = DWORD(-1)
            numOfBytesWrite = DWORD(0)
            addr = payload + pos
            bsz = maxPacketSize if pos + maxPacketSize <= bufsize else bufsize - pos            

            # https://learn.microsoft.com/en-US/windows/win32/fileio/testing-for-the-end-of-a-file
            
            rc = _lib.WriteFile(hdev, LPVOID(addr), bsz, byref(numOfBytesWrite), byref(evt))
            if rc == FALSE:
                dwErr = GetLastError()
                if dwErr != ERROR_IO_PENDING:
                    if dwErr == ERROR_INSUFFICIENT_BUFFER:
                        raise RuntimeError(f"ERROR_INSUFFICIENT_BUFFER: {WinError()}")
                    if dwErr == ERROR_HANDLE_EOF:
                        raise RuntimeError(f"ERROR_HANDLE_EOF: {WinError()}")
                    if dwErr == ERROR_OPERATION_ABORTED:
                        raise RuntimeError(f"ERROR_OPERATION_ABORTED: {WinError()}")
                    raise RuntimeError(f"Error [{dwErr}]: {WinError()}")
                
                #if evt.InternalHigh == 0 and evt.Internal == 0xC000000D:
                #    raise RuntimeError(f'----- WriteFile return STATUS_INVALID_PARAMETER -----')

                dwWait = _lib.WaitForSingleObject(evt.hEvent, timeout)
                if dwWait != WAIT_OBJECT_0:
                    if dwWait == WAIT_TIMEOUT:
                        _lib.CancelIo(hdev)
                        raise USBTimeoutError(f'WAIT_TIMEOUT: {WinError()}', dwWait, dwWait)
                    raise USBError(f'{WinError()}', dwWait, dwWait)

                nBytesWrite = DWORD(0)            
                while True:
                    rc = _lib.GetOverlappedResult(hdev, byref(evt), byref(nBytesWrite), FALSE)
                    if rc != FALSE:
                        break
                    dwErr2 = GetLastError()
                    if dwErr2 == ERROR_HANDLE_EOF:
                        raise RuntimeError(f"ERROR_HANDLE_EOF: {WinError()}")
                    if dwErr2 == ERROR_IO_INCOMPLETE:
                        raise RuntimeError(f"ERROR_IO_INCOMPLETE: {WinError()}")
                    raise RuntimeError(f"Error <{dwErr2}>: {WinError()}")
                
                numOfBytesWrite = nBytesWrite

            if bufsize == 0:
                break
            
            if numOfBytesWrite.value == 0:
                raise USBTimeoutError(f'_timeout_: numOfBytesWrite = 0 , bsz = {bsz}', 9900077, 9900077)
                
            pos += numOfBytesWrite.value
            if pos >= bufsize:
                break

        if pos != bufsize:
            raise USBError(f'USB Write incomplete! pos = {pos}, expected: {bufsize}', 9900078, 9900078)
        
        return pos

    @methodtrace(_logger)
    def bulk_read(self, dev_handle, ep, intf, buff, timeout):
        payload, bufsize = buff.buffer_info()
        
        hdev = dev_handle.hdev
        
        evt = dev_handle.oRead
        evt.Internal = 0
        evt.InternalHigh = 0
        evt.Offset = 0
        evt.OffsetHigh = 0
        _lib.ResetEvent(evt.hEvent)

        dwWait = DWORD(-1)
        numOfBytesRead = DWORD(0)

        # https://learn.microsoft.com/en-US/windows/win32/fileio/testing-for-the-end-of-a-file
        
        rc = _lib.ReadFile(hdev, LPVOID(payload), bufsize, byref(numOfBytesRead), byref(evt))
        if rc == FALSE:
            dwErr = GetLastError()
            if dwErr != ERROR_IO_PENDING:
                if dwErr == ERROR_INSUFFICIENT_BUFFER:
                    raise RuntimeError(f"ERROR_INSUFFICIENT_BUFFER: {WinError()}")
                if dwErr == ERROR_HANDLE_EOF:
                    raise RuntimeError(f"ERROR_HANDLE_EOF: {WinError()}")
                if dwErr == ERROR_OPERATION_ABORTED:
                    raise RuntimeError(f"ERROR_OPERATION_ABORTED: {WinError()}")
                raise RuntimeError(f"Error [{dwErr}]: {WinError()}")
            
            dwWait = _lib.WaitForSingleObject(evt.hEvent, timeout)
            if dwWait != WAIT_OBJECT_0:
                if dwWait == WAIT_TIMEOUT:
                    _lib.CancelIo(hdev)
                    raise USBTimeoutError(f'WAIT_TIMEOUT: {WinError()}', dwWait, dwWait)
                raise USBError(f'{WinError()}', dwWait, dwWait)

            nBytesRead = DWORD(0)
            while True:
                rc = _lib.GetOverlappedResult(hdev, byref(evt), byref(nBytesRead), FALSE)
                if rc != FALSE:
                    break
                dwErr2 = GetLastError()
                if dwErr2 == ERROR_HANDLE_EOF:
                    raise RuntimeError(f"ERROR_HANDLE_EOF: {WinError()}")
                if dwErr2 == ERROR_IO_INCOMPLETE:
                    raise RuntimeError(f"ERROR_IO_INCOMPLETE: {WinError()}")
                raise RuntimeError(f"Error <{dwErr2}>: {WinError()}")
            
            numOfBytesRead = nBytesRead

        return numOfBytesRead.value

    @methodtrace(_logger)
    def intr_write(self, dev_handle, ep, intf, data, timeout):
        raise RuntimeError('Not implemented')

    @methodtrace(_logger)
    def intr_read(self, dev_handle, ep, intf, buff, timeout):
        raise RuntimeError('Not implemented')

    @methodtrace(_logger)
    def ctrl_transfer(self, dev_handle, bmRequestType, bRequest, wValue, wIndex, data, timeout):
        raise RuntimeError('Not implemented')

    @methodtrace(_logger)
    def reset_device(self, dev_handle):
        # FIXME
        pass

    @methodtrace(_logger)
    def clear_halt(self, dev_handle, ep):
        # FIXME
        pass

def init_lib():
    global _lib
    if _lib is None:
        _lib = _load_library()
        _setup_prototypes(_lib)

    return _lib

def get_backend(find_library = None, xdev = None):
    global _lib, _ctx
    _lib = init_lib()
    if _ctx is None:
        _ctx = _GordonGateUsb(_lib, xdev)
    
    return _ctx

# ==================================================================================

def get_sub_keys(key):
    klst = [ ]
    sk_num, v_num, time = wr.QueryInfoKey(key)
    for i in range(0, sk_num):
        klst.append(wr.EnumKey(key, i))
    return klst

def get_value(key, vname):
    try:
        data, type = wr.QueryValueEx(key, vname)
    except FileNotFoundError:
        return None
    return data

def get_usb_driver_info(dev):
    dev_path = f'SYSTEM\\CurrentControlSet\\Enum\\USB\\VID_{dev.idVendor:04X}&PID_{dev.idProduct:04X}'
    access = wr.KEY_READ | wr.KEY_QUERY_VALUE | wr.KEY_ENUMERATE_SUB_KEYS
    try:
        key = wr.OpenKeyEx(wr.HKEY_LOCAL_MACHINE, dev_path, access = access)
    except:
        return -1

    subkeys = get_sub_keys(key)
    if len(subkeys) == 0:
        return -10
        
    if dev.port_number is None:
        return -15
    
    drv_name = ''
    drv_info_path = ''
    drv_pnum = -1
    for sk_name in subkeys:
        drv_path = dev_path + '\\' + sk_name
        #print(drv_path)
        key1 = wr.OpenKeyEx(wr.HKEY_LOCAL_MACHINE, drv_path, access = access)
        info_path = get_value(key1, 'Driver')
        d_name = get_value(key1, 'Service')
        if info_path and d_name:
            drv_loc_info = get_value(key1, 'LocationInformation')    
            if drv_loc_info:
                pk = drv_loc_info.find('Port_#')
                if pk >= 0:
                    pk += 6
                    pnum = int(drv_loc_info[pk:pk+4], 16)
                    if pnum == dev.port_number:
                        if drv_pnum >= 0:
                            return -20  # second key founded
                        drv_name = d_name
                        drv_info_path = info_path
                        drv_pnum = pnum
        wr.CloseKey(key1)

    if drv_pnum < 0 or not drv_name:
        return -30

    #print(f'drv_name: {drv_name}')
    #print(f'drv_info_path: {drv_info_path}')
    #print(f'drv_pnum: {drv_pnum}')
        
    drv_info_path = 'SYSTEM\\CurrentControlSet\\Control\\Class\\' + drv_info_path
    key1 = wr.OpenKeyEx(wr.HKEY_LOCAL_MACHINE, drv_info_path, access = access)
    drv_desc = get_value(key1, 'DriverDesc')
    drv_ver = get_value(key1, 'DriverVersion')
    wr.CloseKey(key1)
    return ( drv_name, drv_ver )

