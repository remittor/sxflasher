import os
import sys
import enum
import queue
import array
import ctypes
from datetime import datetime
from datetime import timedelta
import binascii
import platform
import atexit

_use_local_pyusb = False
try:
    import pyusb as usb
    _use_local_pyusb = True
except:
    import usb

if _use_local_pyusb: 
    import pyusb.core
    usb.core = pyusb.core
    import pyusb.backend
    usb.backend = pyusb.backend
    import pyusb.backend.libusb1
    usb.backend.libusb1 = pyusb.backend.libusb1
    import pyusb.util
    usb.util = pyusb.util
    from pyusb.util import build_request_type, CTRL_OUT, CTRL_IN, CTRL_TYPE_VENDOR, CTRL_RECIPIENT_DEVICE
    from pyusb.util import endpoint_direction, ENDPOINT_OUT, ENDPOINT_IN
else:
    import usb.core
    import usb.backend
    import usb.backend.libusb1
    import usb.util
    from usb.util import build_request_type, CTRL_OUT, CTRL_IN, CTRL_TYPE_VENDOR, CTRL_RECIPIENT_DEVICE
    from usb.util import endpoint_direction, ENDPOINT_OUT, ENDPOINT_IN

import somcta as ta

import logging
from logcfg import log


class SXError(IOError):
    def __init__(self, msg, errno = 0):
        IOError.__init__(self, errno, msg)

class SomcUsbResponse():
    def __init__(self, data, retcode = 0, errtext = ''):
        self.data = data
        self.retcode = retcode
        self.errtext = errtext
        
    def __str__(self):
        if self.data is None:
            return f'<None,{self.retcode},"{self.errtext}">'
        else:
            return f'<{len(self.data)},{self.retcode},"{self.errtext}">'

class SomcUsbDevice():
    def __init__(self, loglevel = logging.CRITICAL):
        self.dev = None
        self.epout = None
        self.epin = None
        self.rbuf = b''
        atexit.register(self.cleanup)
        self.lastresp = None
        self.upbuf = b''
        log.set_level(loglevel)
        self.read_timeout = 500    # 500 ms
        self.write_timeout = 2000  # 2 seconds
        self.max_download_size = 0

    def __del__(self):
        if self.dev:
            print("Closing USB connection")
            try:
                #self.dev.reset()
                pass
            except Exception as e:
                #print(e)
                pass
            usb.util.dispose_resources(self.dev)

    def cleanup(self):
        #log.debug("Closing USB connection!!!!!!")
        pass

    def set_timeouts(self, timeout):
        if isinstance(timeout, int):
            timeout = ( timeout, timeout )
        
        self.read_timeout  = timeout[0]
        self.write_timeout = timeout[1]

    def get_timeouts(self):
        return ( self.read_timeout, self.write_timeout)

    def get_usb_devlist(self, vid, pid):
        dlst = [ ]
        dname = os.path.dirname(os.path.abspath(__file__))
        find_library = None
        if sys.platform == 'win32':
            if ctypes.sizeof(ctypes.c_void_p) == 4:
                libpath = dname + os.path.sep + "libusb1_32.dll"
            else:
                libpath = dname + os.path.sep + "libusb1_64.dll"
            find_library = lambda x: libpath
        
        usb_backend = usb.backend.libusb1.get_backend(find_library = find_library)

        devlist = usb.core.find(find_all = True, backend = usb_backend)
        if not devlist:
            raise RuntimeError("USB device not connected")

        for dev in devlist:
            #log.debug(f"VID: 0x{dev.idVendor:04X}  PID: 0x{dev.idProduct:04X}  DeviceClass: 0x{dev.bDeviceClass:02X}")
            if dev.idVendor == vid and dev.idProduct == pid:
                dlst.append(dev)
        
        return dlst

    def print_dev_struct(self, dev = None):
        dev = self.dev if dev is None else dev
        #log.debug(f"VID: 0x{dev.idVendor:04X}  PID: 0x{dev.idProduct:04X}  DeviceClass: 0x{dev.bDeviceClass:02X}")
        for cfg in dev:
            log.debug(f'CONF: {cfg.bConfigurationValue}')
            for intf in cfg:
                log.debug(f'  IFaceNum: {intf.bInterfaceNumber}  AltSettings: {intf.bAlternateSetting}')
                for ep in intf:
                    log.debug(f'    EpAddr: 0x{ep.bEndpointAddress:X}')

    def connect(self, timeout = None, write_timeout = None):
        devlist = self.get_usb_devlist(0x0FCE, 0xB00B)  # SOMC 2017 XFL
        if not devlist:
            raise RuntimeError("SOMC usb device not found!")

        if len(devlist) > 1:
            raise RuntimeError(f"Founded {len(devlist)} SOMC usb devices!")

        dev = devlist[0]
        del devlist
        self.dev = dev
        
        self.print_dev_struct()        

        # access the first configuration
        usbcfg = dev[0]
        # access the first interface
        usbintf = usbcfg[(0,0)]
        # first endpoint
        usbep = usbintf[0]

        #cfg: usb.core.Configuration = dev.get_active_configuration()
        cfg = dev[0]
        intf = cfg[(0, 0)]
        in_ep  = intf[0].bEndpointAddress
        out_ep = intf[1].bEndpointAddress
        #print(f'out_ep: 0x{out_ep:X} , in_ep: 0x{in_ep:X}')
        #print('dev:', dev)
        ret = self.check_usb_driver()
        if ret != 0:
            raise RuntimeError('Incorrect USB driver!')
            
        dev = self.dev

        dev.reset()
        dev.set_configuration()
        #dev.set_interface_altsetting(interface = 0, alternate_setting = 0)

        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        
        custom_match = lambda e: endpoint_direction(e.bEndpointAddress) == ENDPOINT_OUT
        self.epout = usb.util.find_descriptor(intf, custom_match = custom_match)
        if not self.epout:
            raise RuntimeError('Cannot find ENDPOINT_OUT for USB device!')
        
        log.debug(str(self.epout).strip().replace('\n    ', '\n        '))

        custom_match = lambda e: endpoint_direction(e.bEndpointAddress) == ENDPOINT_IN
        self.epin  = usb.util.find_descriptor(intf, custom_match = custom_match)
        if not self.epout:
            raise RuntimeError('Cannot find ENDPOINT_IN for USB device!')

        log.debug(str(self.epin ).strip().replace('\n    ', '\n        '))

        if timeout:
            self.read_timeout = timeout
        
        if write_timeout:
            self.write_timeout = write_timeout

        dev.default_timeout = self.read_timeout
        self.init_streams()
        self.max_download_size = int(self.getvar('max-download-size'))

    def check_usb_driver(self, force = 'ggsomc'):
        dev = self.dev
        if sys.platform != 'win32':
            return 0

        import ggsomc
        
        dev_addr = f'{dev.idVendor:04X}:{dev.idProduct:04X}'
        ret = ggsomc.get_usb_driver_info(dev)
        if isinstance(ret, int):
            raise RuntimeError(f'USB driver for device {dev_addr} not found! rc = {ret}')

        drv_name = ret[0]
        drv_ver = ret[1]        
        log.info(f'Device: {dev_addr}  DriverName: "{drv_name}"  DriverVersion: {drv_ver}')
        
        dn = drv_name.lower()
        if dn.startswith('libusbk'):
            log.info(f'USB Device {dev_addr} using driver "{drv_name}" ver:{drv_ver}')
            return 0
            
        if dn.startswith('ggsomc'):
            log.info(f'USB Device {dev_addr} using driver "{drv_name}" ver:{drv_ver}')
            ver = drv_ver.split('.')
            if force == 'ggsomc':
                if int(ver[0]) < 3 or (int(ver[0]) == 3 and int(ver[1]) < 2):
                    raise RuntimeError(f'USB Device {dev_addr} using older GordonGate driver! Please install latest version!')
                return self.switch_to_ggsomc(dev)
            return 0

        log.error(f'USB Device {dev_addr} using unsupported driver "{drv_name}" ver:{drv_ver}')
        log.error(f'Please install SOMC GordonGate driver or install libusbK.sys driver via Zadig utility!')
        return -1

    def switch_to_ggsomc(self, xdev):
        import ggsomc

        usb_backend = ggsomc.get_backend(xdev = xdev)
        if not usb_backend:
            raise RuntimeError(f'Cannot switch to ggsomc backend')

        dev = usb.core.find(idVendor = self.dev.idVendor, idProduct = self.dev.idProduct, backend = usb_backend)
        if not dev:
            raise RuntimeError("USB device not connected (ggsomc)")
        
        log.debug(f'ggdev: {type(dev)}')
        self.dev = dev
        log.info(f'switch_to_ggsomc: OK')
        return 0


    def read_all_packets(self, ep, timeout = 1000):
        if not isinstance(ep, int):
            ep = ep.bEndpointAddress
        try:
            k = timeout // 10
            for i in range(0, k):
                self.dev.read(ep, 0x1000, 10)
        except Exception:
            pass

    def init_streams(self):
        self.read_all_packets(self.epin)
        dt = self.dev.default_timeout
        self.dev.default_timeout = 500
        max_download_size = None
        try:
            max_download_size = self.getvar('max-download-size')
        #except usb.core.USBTimeoutError:
        #    raise
        except Exception:
            pass
        self.dev.default_timeout = dt
        
        if max_download_size is None:
            log.debug('USB streams cleaning...')
            try:
                self.raw_write(b'getvar:max-download-size', 500)
            #except usb.core.USBTimeoutError:
            #    raise
            except Exception:
                pass
            data = None
            try:
                data = self.raw_read(0, 10)
            except Exception:
                pass
                
            if data:
                ht = data[:4]
                if ht != b'DATA' and ht != b'OKAY' and ht != b'FAIL':
                    raise RuntimeError(f'Cannot init USB streams! Data: {data}')

            data = None
            while True:
                size = self.epout.wMaxPacketSize - 16
                try:
                    self.raw_write(b'\x00' * size, 100)  # <======
                except usb.core.USBTimeoutError:
                    raise # pass
                try:
                    data = self.raw_read(0, 2)
                except Exception:
                    pass
                if data:
                    break
                
            ht = data[:4]
            if ht != b'DATA' and ht != b'OKAY' and ht != b'FAIL':
                raise RuntimeError(f'Cannot init USB Streams! Data: {data}')

        log.info('USB streams inited!')        
        self.read_all_packets(self.epin)
        return True

    def raw_write(self, data, timeout = None):
        if timeout is None:
            timeout = self.write_timeout
            
        ep = self.epout
        epaddr = ep.bEndpointAddress
        #pktsize = ep.wMaxPacketSize        
        size = 0
        while size < len(data):
            size += self.dev.write(epaddr, data if size == 0 else data[size:], timeout = timeout)
        
        if size != len(data):
            raise RuntimeError(f'USB write error: size = {size}, expected: {len(data)}')

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()

        self.raw_write(data)

    def raw_read(self, size = 0, timeout = None):
        ep = self.epin
        epaddr = ep.bEndpointAddress
        pktsize = ep.wMaxPacketSize
        data = array.array('B', [ ])
        while True:
            if size > 0 and pktsize > size - len(data):
                pktsize = size - len(data)
            plen = len(data)
            try:                
                data += self.dev.read(epaddr, pktsize, timeout)
            except usb.core.USBTimeoutError:
                break
            if len(data) == plen:
                break  # readed 0 bytes ==> EOF
            if size == 0:
                break
            if size > 0 and len(data) >= size:
                break
        
        if size > 0 and size != len(data):
            raise RuntimeError(f'Error on read stream from USB device! Read size = {len(data)} , expected: {size}')

        return data.tobytes()

    def read(self, onepkt = False, timeout = None):        
        self.lastresp = SomcUsbResponse(None, -1000)
        data = self.raw_read(0, timeout)
        ht = data[:4]
        if ht != b'DATA' and ht != b'OKAY' and ht != b'FAIL':
            raise RuntimeError(f'Recv unknown header type = {ht}')

        if ht == b'OKAY':
            self.lastresp = SomcUsbResponse(data[4:])
            return self.lastresp

        if ht == b'FAIL':
            self.lastresp = SomcUsbResponse(None, -1, data[4:].decode('latin-1'))
            return self.lastresp

        header = data
        data = b''
        footer = b''
        while True:
            if ht != b'DATA':
                raise RuntimeError(f'Recv unknown DATA header type = {ht}')

            if len(header) == 13 and header[12] == b'\0':
                # xperia 10 mark 3 XQ-BT41 send 13 bytes where last byte is null termination, fixing it to 12
                header = header[:12]

            if len(header) != 12:
                raise RuntimeError(f'Errornous DATA response! Header len = {len(header)}, expected: 12')

            if onepkt:
                self.lastresp = SomcUsbResponse(header[4:], 0, 'DATA_SIZE')
                return self.lastresp

            size = int(header[4:].decode('latin-1'), 16)
            if size > 0:
                data += self.raw_read(size, timeout)
            
            header = self.raw_read(0, timeout)
            if len(header) < 4:
                raise RuntimeError(f'Errornous DATA response! Header len = {len(header)}, expected >= 4')
                
            ht = header[:4]
            if ht == b'OKAY' or ht == b'FAIL':
                footer = header[4:]
                break  
            
        if ht == b'FAIL':
            self.lastresp = SomcUsbResponse(data, -2, footer.decode('latin-1'))
            return self.lastresp
            
        self.lastresp = SomcUsbResponse(data)
        return self.lastresp
        
    def command(self, msg, dt = 'bytes'):
        self.write(msg)
        un = ''
        if isinstance(msg, str):
            if msg.startswith('Read-TA:') or msg.startswith('Write-TA:'):
                try:
                    upc = msg.split(':')
                    part = int(upc[1])
                    code = int(upc[2])
                    unit = ta.punit[part][code]
                    if not unit.name.startswith('_'):
                        un = f'<{unit.name}>'
                except Exception as e:
                    pass

        resp = self.read()
        if resp.retcode < 0 or resp.data is None:
            log.error(f'CMD: {msg}{un}: [rc:{resp.retcode}] "{resp.errtext}"')
            return None
        
        x = msg.startswith('Write-TA:') if isinstance(msg, str) else False
        data = resp.data if not x else self.upbuf
        if dt == 'str' or dt == 'int':
            log.debug(f'CMD: {msg}{un} = {data.decode("latin-1")}')
        else:
            if len(resp.data) > 256:
                log.debug(f'CMD: {msg}{un} = <size:{len(data)}>')
            else:
                log.debug(f'CMD: {msg}{un} = {binascii.hexlify(data, " ")}')
        
        if dt == 'str':
            return resp.data.decode('latin-1')
            
        if dt == 'int':
            if len(resp.data) < 1:
                raise RuntimeError(f'CMD: {msg}{un}: response len = {len(resp.data)}, expected >= 1')
            return int(resp.data.decode('latin-1'))

        if dt == 'int8':
            if len(resp.data) < 1:
                raise RuntimeError(f'CMD: {msg}{un}: response size = {len(resp.data)}, expected >= 1')
            return int.from_bytes(resp.data[:1])

        if dt.startswith('int32'):
            if len(resp.data) < 4:
                raise RuntimeError(f'CMD: {msg}{un}: response size = {len(resp.data)}, expected >= 4')
            byteorder = 'little' if dt == 'int32le' else 'big'    
            return int.from_bytes(resp.data[:4], byteorder = byteorder)

        return resp.data

    def check_signature_cmd(self):        
        self.cmd_sign_with_data_allow = False
        log.debug('check_signature_cmd...')
        self.write('signature:00000000')
        resp = self.read(onepkt = True)
        log.debug(f'resp: {resp}')
        
        if resp.retcode == 0 and resp.errtext == 'DATA_SIZE':
            resp2 = self.read(onepkt = True)
            log.info(f'Command "signature:<size>" is supported!')
            self.cmd_sign_with_data_allow = True
            return True
        
        log.info(f'Command "signature:<size>" NOT supported!')
        return False

    def getvar(self, name, dt = 'str'):
        return self.command('getvar:' + name, dt)
        
    def ta_unit_addr(self, addr):
        if isinstance(addr, ta.TAUnit):
            unit = addr
            return (unit.part, unit.code)
    
        if isinstance(addr, str):
            unit = ta.unit[addr]
            return (unit.part, unit.code)
        
        if isinstance(addr, int):
            return (2, addr)

        if isinstance(addr, list):
            return (addr[0], addr[1])

        raise RuntimeError(f'Incorrect type of TA unit addr: {type(addr)}')
    
    def read_ta(self, addr):
        part, unit = self.ta_unit_addr(addr)
        return self.command(f'Read-TA:{part}:{unit}')
        
    def set_current_slot(self, slot):
        if slot != 'a' and slot != 'b':
            raise RuntimeError(f'Incorrect slot name!')
            
        msg = f'set_active:{slot}'
        ret = self.command(msg)
        if ret is None:
            return None

        return slot

    def dump_all_ta(self):
        product = self.getvar('product')
        serialno = self.getvar('serialno')
        stime = datetime.now().strftime('%Y%m%d-%H%M%S')
        dname = os.path.dirname(os.path.abspath(__file__))
        dname += os.path.sep + f'TA_{product}_{serialno}_' + stime
        os.makedirs(dname, exist_ok = True)
        for part in range(1, 3):
            msg = f'Read-all-TA:{part}'
            data = self.command(msg)
            if data is None or len(data) == 0:
                log.error(f'Cannot get dump TA for partion {part}')
                continue
            subdir = dname + os.path.sep + f'part_{part}'
            os.makedirs(subdir, exist_ok = True)
            fname = dname + os.path.sep + f'ta_{product}_{serialno}_{part}.img'
            with open(fname, 'wb') as file:
                file.write(data)
            log.info(f'File "{fname}" saved!')
            pos = 0
            while True:
                if len(data) - pos == 0:
                    break
                if len(data) - pos < 8:
                    log.error(f'Incorrect dump struct (001)')
                    break
                unit = int.from_bytes(data[pos:pos+4], byteorder = 'big')
                pos += 4
                size = int.from_bytes(data[pos:pos+4], byteorder = 'big')
                pos += 4
                fname = subdir + os.path.sep + f'ta_{product}_{serialno}_{part}_{unit}.dat'
                with open(fname, 'wb') as file:
                    file.write(data[pos:pos+size])
                pos += size

    def dump_err_log(self, save_to_file = True):
        txt = self.command('Getlog')
        if txt is None:
            log.error(f'Cannot get s1boot logs: {self.lastresp}')
        
        if save_to_file:
            stime = datetime.now().strftime('%Y-%m-%d__%H-%M-%S')
            dname = os.path.dirname(os.path.abspath(__file__))
            os.makedirs(f'{dname}/logs', exist_ok = True)
            fname = f'{dname}/logs/sxf__{stime}__error.log'
            with open(fname, 'wb') as file:
                file.write(txt) if txt else file.write('')
        return txt

    def dump_xbl_log(self, save_to_file = True):
        txt = self.read_ta( [2, 2050] )   # LAST_BOOT_LOG
        if txt is None:
            log.error(f'Cannot get s1boot logs: {self.lastresp}')
        
        if save_to_file:
            stime = datetime.now().strftime('%Y-%m-%d__%H-%M-%S')
            dname = os.path.dirname(os.path.abspath(__file__))
            os.makedirs(f'{dname}/logs', exist_ok = True)
            fname = f'{dname}/logs/sxf__{stime}__bl.log'
            with open(fname, 'wb') as file:
                file.write(txt) if txt else file.write('')
        return txt
        
    def upload(self, data, sign = False, timeout = None):
        self.upbuf = b''
        if isinstance(data, str):
            data = data.encode()
    
        dsize = len(data)
        if dsize >= self.max_download_size:
            raise RuntimeError(f'Error on UPLOAD command: Too large data size = {dsize}, max = {self.max_download_size}')

        dsizehex = f'{dsize:08X}'
        cmdname = 'download' if not sign else 'signature'
        msg = f'{cmdname}:{dsizehex}'
        self.write(msg)
        
        resp = self.read(onepkt = True, timeout = timeout)
        
        if resp.retcode != 0 or resp.errtext != 'DATA_SIZE':
            raise RuntimeError(f'Error on {cmdname} command: {str(self.lastresp)}')

        if resp.data != dsizehex.encode():
            raise RuntimeError(f' Error: {cmdname} DATA reply size: {resp.data}, expected: "{dsizehex}"')

        if dsize > 0:
            self.write(data)

        resp = self.read(onepkt = True, timeout = timeout)
        if resp.retcode != 0 or resp.errtext != '':
            if sign:
                print('resp.errtext:', resp.errtext)
                return False
            raise RuntimeError(f'ERROR on {cmdname} command: {str(self.lastresp)}')

        self.upbuf = data[:]   # copy bytearray
        log.debug(f'{cmdname} command comleted! Size = {dsize}')
        return True

    def write_ta(self, addr, data):
        part, unit = self.ta_unit_addr(addr)
        self.upload(data)
        return self.command(f'Write-TA:{part}:{unit}')
    
    def check_sign_upload(self):
        ret = self.upload(b'\x00\x00\x00\x03', sign = True)
        if not ret:
            log.error(f'CMD: signature: {self.lastresp}')   # <None,-1,"Failed to verify cms">

    def powerdown(self):
        self.raw_write(b'powerdown')
        self.raw_read(0, 50)


def activate_usb_backend_logger(level = logging.DEBUG):
    logger = logging.getLogger('usb')
    logger.setLevel(level)
    usb._debug.enable_tracing(True)
    handler = logging.StreamHandler()    
    fmt = logging.Formatter('%(levelname)s:%(name)s:%(message)s') 
    handler.setFormatter(fmt)
    logger.addHandler(handler)

def somc_usb_test(sud):
    #activate_usb_backend_logger(level = logging.DEBUG)
    max_download_size = sud.getvar('max-download-size')
    sector_size = sud.getvar('Sector-size')
    product = sud.getvar('product')
    version = sud.getvar('version')
    blver = sud.getvar('version-bootloader')
    bbver = sud.getvar('version-baseband')
    serialno = sud.getvar('serialno')
    secure = sud.getvar('secure')
    loader_ver = sud.getvar('Loader-version')
    phone_id = sud.getvar('Phone-id')
    device_id = sud.getvar('Device-id')
    platform_id = sud.getvar('Platform-id')
    rooting_status = sud.getvar('Rooting-status')
    ufs_info = sud.getvar('Ufs-info')
    emmc_info = sud.getvar('Emmc-info')
    def_security = sud.getvar('Default-security')
    keystore_counter = sud.getvar('Keystore-counter')
    security_state = sud.getvar('Security-state')

    sud.getvar('Stored-security-state')
    sud.getvar('Keystore-xcs')

    s1_root = sud.getvar('S1-root')
    sake_root = sud.getvar('Sake-root')
    root_key_hash = sud.command('Get-root-key-hash')   # PLF_ROOT_HASH
    slot_count = sud.getvar('slot-count')
    current_slot = sud.getvar('current-slot')
    battery_level = sud.getvar('Battery')
    sud.getvar('Frp-partition')
    sud.getvar('X-conf')
    sud.getvar('Soc-unique-id')

    #sud.command('Get-gpt-info:0')
    #sud.command('Get-gpt-info:1')
    #sud.command('Get-gpt-info:2')

    #sud.command('Get-ufs-info')
    #sud.command('Get-emmc-info')

    #log = sud.command('Getlog')
    #print(log.decode('latin-1'))

    #sud.dump_all_ta()

    simlock = sud.read_ta(0x7DA)
    #print(simlock)
    ddd = sud.read_ta(0x1046B)
    ddd = sud.read_ta(0x1046C)

    ddd = sud.read_ta(2128)
    ddd = sud.read_ta(2129)
    ddd = sud.read_ta(2010)
    ddd = sud.read_ta(2003)

    ddd = sud.read_ta(2050)

    sud.upload("hello world")
    sud.upload(b'\x55' * 4000000)
    ##sud.upload(b'\x55' * 150*1000*1000)
    
    ##sud.upload(b'\x00\x00\x00\x02')

    sud.upload(b'')
    #sud.write_ta(2486, b'\x00\x00\x00\x01')    # ENABLE_NONSECURE_USB_DEBUG
    ddd = sud.read_ta(2486)

    #sud.check_sign_upload()

    sud.dump_err_log()
    sud.dump_xbl_log()


if __name__ == '__main__':
    import optparse
    parser = optparse.OptionParser("usage: %prog [options]", add_help_option = False)
    parser.add_option("-a", "--action", dest = "action", default = '', type = "string")
    parser.add_option("-t", "--test", dest = "test", default = 1, type = "int")
    parser.add_option("-T", "--timeout", dest = "timeout", default = None, type = "int")
    parser.add_option("", "--rt", dest = "read_timeout", default = 500, type = "int")
    parser.add_option("", "--wt", dest = "write_timeout", default = 1000, type = "int")
    parser.add_option("-v", "--verbose", dest = "verbose", default = 1, type = "int")
    (opt, args) = parser.parse_args() 
    
    try:
        loglevel = logging.DEBUG if opt.verbose else logging.INFO
        sud = SomcUsbDevice(loglevel = loglevel)
        sud.test = opt.test
        
        if opt.timeout:
            rt = opt.timeout
            wt = opt.timeout
        else: 
            rt = opt.read_timeout
            wt = opt.write_timeout
            
        log.info(f'Set read  timeout = {rt} ms')
        sud.read_timeout = rt
        log.info(f'Set write timeout = {wt} ms')
        sud.write_timeout = wt

        sud.connect()

        if opt.action == '':
            somc_usb_test(sud)

        if opt.action == 'dumpta':
            sud.dump_all_ta()
        
        if opt.action == 'pwdn' or opt.action == 'powerdown':
            sud.powerdown()
    
    except Exception:
        log.error('CRITICAL ERROR')
        log.set_level(100)
        log.exception('CRITICAL ERROR')
        raise
    
    except KeyboardInterrupt:
        log.error('---- KeyboardInterrupt ----')
        log.set_level(100)
        log.exception('---- KeyboardInterrupt ----')
        raise
 
    log.info('==== Finish ====')
