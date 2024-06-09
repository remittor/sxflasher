import os
import sys
import array

class TAUnit():
    def __init__(self, part, code, name = '', doc = ''):
        self.part = part
        self.code = code
        self.name = name.upper()
        self.doc = doc
        self.value = None
        

_tau = [ { }, { }, { } ]

_tau[1][1877]  = 'RF_BC_CFG'      # 0x755
_tau[1][6828]  = 'LTE_BC_CFG'     # 0x1AAC

_tau[2][2002]  = 'FLA_FLA'        # 0x7D2  # what is flafla?
_tau[2][2003]  = 'S1_LDR'         # 0x7D3  # hw conf
_tau[2][2010]  = 'SENS_DATA'      # 0x7DA  # simlock, bootloader unlock allowed, etc.
_tau[2][2021]  = 'DRM_KEY_STATUS' # 0x7E5

_tau[2][2022]  = 'BLOB_0'         # 0x7E6  # marlin
_tau[2][2023]  = 'BLOB_1'         # 0x7E7  # ckb
_tau[2][2024]  = 'BLOB_2'         # 0x7E8  # widevine
_tau[2][2025]  = 'BLOB_3'         # 0x7E9

_tau[2][2036]  = 'BLOB_E'         # 0x7F4

_tau[2][2024]  = 'SRM'            # 0x7F8

_tau[2][2050]  = 'LAST_BOOT_LOG'  # 0x802

_tau[2][2128]  = '__2128'         # 0x850
_tau[2][2129]  = '__2129'         # 0x851

_tau[2][2141]  = 'MACHINE_ID'     # 0x85D

_tau[2][2202]  = 'SW_VER'         # 0x89A
_tau[2][2205]  = 'CUST_VER'       # 0x89D
_tau[2][2206]  = 'FS_VER'         # 0x89E
_tau[2][2207]  = 'S1_BOOT_VER'    # 0x89F
_tau[2][2208]  = '__2208'         # 0x8A0
_tau[2][2209]  = 'BUILD_TYPE'     # 0x8A1
_tau[2][2210]  = 'PHONE_NAME'     # 0x8A2
_tau[2][2212]  = 'AC_VER'         # 0x8A4    # cust-reset.ta zeroes this (1 byte)

_tau[2][2226]  = 'BL_UNLOCKCODE'           # 0x8B2  # RCK
_tau[2][2227]  = 'STARTUP_SHUTDOWNRESULT'  # 0x8B3
_tau[2][2237]  = 'RESET_LOCK_STATUS'       # 0x8BD

_tau[2][2301]  = 'STARTUP_REASON'          # 0x8FD   # "override unit"
_tau[2][2311]  = 'DISABLE_CHARGE_ONLY'     # 0x907
_tau[2][2316]  = 'DISABLE_CHARGE_ONLY_ENTERPRISE' # 0x90C  # auto-boot.ta zeroes this (1 byte)
_tau[2][2330]  = 'OSV_RESTRICTION'         # 0x91A   # 1 byte
_tau[2][2404]  = 'FOTA_INTERNAL'           # 0x964   # MODEM_CUST_CFG ?? cfg located in system/etc/customization/modem/ -> fota-reset.ta zeroes this
_tau[2][2473]  = 'KERNEL_CMD_DEBUG_MASK'   # 0x9A9   # 1 byte
_tau[2][2475]  = 'FLASH_LOG'               # 0x9AB   # firmwares history log
_tau[2][2486]  = 'ENABLE_NONSECURE_USB_DEBUG'  # 0x9B6
_tau[2][2500]  = 'CREDMGR_KEYTABLE_PRESET' # 0x9C4
_tau[2][2550]  = 'MASTER_RESET'            # 0x9F6  #
_tau[2][2551]  = 'BASEBAND_CFG'            # 0x9F7  # cfg located in the modem
_tau[2][2553]  = 'WIPE_REASON'             # 0x9F9
_tau[2][2560]  = 'WIFI_MAC'                # 0xA00
_tau[2][2568]  = 'BLUETOOTH_MAC'           # 0xA08

_tau[2][4900]  = 'SERIAL_NO'               # 0x1324
_tau[2][4901]  = 'PBA_ID'                  # 0x1325
_tau[2][4902]  = 'PBA_ID_REV'              # 0x1326
_tau[2][4908]  = 'PP_SEMC_ITP_PRODUCT_NO'  # 0x132C
_tau[2][4909]  = 'PP_SEMC_ITP_REV'         # 0x132D

_tau[2][10100] = 'FLASH_MODE'              # 0x2774

_tau[2][66667] = 'DEVICE_KEY'              # 0x1046B  # DEVICE_KEY and DRM keys
_tau[2][66668] = 'REMOTE_LOCK'             # 0x1046C  # a sin file


# =============================================================================================

unit = { }    # dict by name

punit = [ { }, { }, { } ]   # list of 3 partitions: dicts by unit_no

for part, pv in enumerate(_tau):
    for code, info in pv.items():
        if isinstance(info, str):
            name = info
        elif isinstance(info, list):
            name = info[0]
        else:
            raise RuntimeError(f'Incorrect TA unit table struct! {type(info)}')
        
        if name in unit:
            raise RuntimeError(f'Unit "{name}" already exists!')
        
        unit[name] = TAUnit(part, code, name)
        
        if code in punit[part]:
            raise RuntimeError(f'Unit {part}:{code} already exists!')
        
        punit[part][code] = TAUnit(part, code, name)
        
        if isinstance(info, list):
            if len(info) > 1 and len(info[1]) >= 1:
                unit[name].doc = info[1]
                punit[part][code].doc = info[1]

 
def load_from_file(fn):
    global punit
    with open(fn, 'r', encoding = 'latin-1') as file:
        lines = file.readlines()
    
    tau = TAUnit(None, None)
    tau._size = -1
    tau._ulist = [ ]
    
    def add_unit(tau):
        global punit
        if tau._size >= 0:
            if tau.part is None or tau.code is None:
                raise ValueError(f'Incorrect ta-file "{fn}". Part = {tau.part}, Code = {tau.code}')

            if tau._pos < 0:
                raise ValueError(f'Incorrect ta-file "{fn}". Pos = {tau._pos}')

            if tau._pos != tau._size:
                raise ValueError(f'Incorrect ta-file "{fn}". Pos = {tau._pos}, Size = {tau._size}')

            unit = TAUnit(tau.part, tau.code)
            if tau._size > 0:
                unit.value = bytes(tau._data)
            else:
                unit.value = b''
                
            if tau.code in punit[tau.part]:
                unit.name = punit[tau.part][tau.code].name
                
            tau._ulist.append(unit)

        tau.code = None
        tau._size = -1
        tau._data = None
        tau._pos = -1

    add_unit(tau)
    
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith('//'):
            continue

        if line.strip() == '':
            continue

        if line == '01' or line == '02':
            add_unit(tau)
            tau.part = int(line, 16)
            continue

        if tau.part is None:
            raise ValueError(f'Incorrect ta-file "{fn}". PartNum: "{line}"')
        
        line = line.replace('\t', ' ')
        
        if not line.startswith(' '):
            add_unit(tau)
        
        if tau.code is None:
            if line.startswith(' '):
                raise ValueError(f'Incorrect ta-file "{fn}". Unit: "{line}"')
            
            line = line.strip()
            line = line.replace('   ', ' ')
            line = line.replace('  ', ' ')
            
            vlst = line.split(' ')
            if len(vlst) < 2:
                raise ValueError(f'Incorrect ta-file "{fn}". UnitNum: "{line}"')
                
            ucode = vlst[0]
            if len(ucode) != 4 and len(ucode) != 8:
                raise ValueError(f'Incorrect ta-file "{fn}". UnitNum: "{line}"')

            tau.code = int(ucode, 16)

            usize = vlst[1]
            if len(usize) != 4 and len(usize) != 8:
                raise ValueError(f'Incorrect ta-file "{fn}". UnitNum: "{line}"')

            tau._size = int(usize, 16)
            
            if tau._size == 0:
                tau._pos = 0
                add_unit(tau)
                continue

            tau._data = array.array('B', b'\x00' * tau._size)
            line = '  ' + ' '.join( vlst[2:] )
            tau._pos = 0

        if tau._size < 0:
            raise ValueError(f'Incorrect ta-file "{fn}". Negative tau_size')

        if not line.startswith(' '):
            raise ValueError(f'Incorrect ta-file "{fn}". Data: "{line}"')

        line = line.strip()
        if len(line) < 2:
            raise ValueError(f'Incorrect ta-file "{fn}". Data: "{line}"')
            
        vlst = line.split(' ')
        for v in vlst:
            if len(v) != 2:
                raise ValueError(f'Incorrect ta-file "{fn}". Data: "{line}"')
            
            if tau._pos >= tau._size:
                raise ValueError(f'Incorrect ta-file "{fn}". Pos = {tau._pos} , Size = {tau._size}')
            
            tau._data[tau._pos] = int(v, 16)
            tau._pos += 1
        pass
                
    add_unit(tau)
    return tau._ulist
    
