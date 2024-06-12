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
_tau[2][2003]  = 'HW_CONF'        # 0x7D3  # "S1_LDR" "S1_HWConf" "x_conf_hwconfig"
_tau[2][2010]  = 'SIMLOCK'        # 0x7DA  # simlock, bootloader unlock allowed, etc.
_tau[2][2021]  = 'DRM_KEY_STATUS' # 0x7E5

_tau[2][2022]  = 'BLOB_0'         # 0x7E6  # marlin
_tau[2][2023]  = 'BLOB_1'         # 0x7E7  # ckb
_tau[2][2024]  = 'BLOB_2'         # 0x7E8  # widevine
_tau[2][2025]  = 'BLOB_3'         # 0x7E9  # HDCP

_tau[2][2036]  = 'BLOB_E'         # 0x7F4

_tau[2][2040]  = 'DRM_DYN_DATA'   # 0x7F8
_tau[2][2050]  = 'LAST_BOOT_LOG'  # 0x802
_tau[2][2053]  = 'BOOT_COUNTER'   # 0x805
_tau[2][2099]  = 'DRM_CUST'       # 0x833

_tau[2][2128]  = '__2128'            # 0x850  uint32_t
_tau[2][2129]  = 'SIMLOCK_SIGNATURE' # 0x851  "S1_SL"

_tau[2][2160]  = 'S1_GCodes'      # 0x870

_tau[2][2141]  = 'MACHINE_ID'     # 0x85D

_tau[2][2202]  = 'SW_VER'         # 0x89A
_tau[2][2205]  = 'CUST_VER'       # 0x89D
_tau[2][2206]  = 'FS_VER'         # 0x89E
_tau[2][2207]  = 'S1_BOOT_VER'    # 0x89F
_tau[2][2208]  = '__2208'         # 0x8A0
_tau[2][2209]  = 'BUILD_TYPE'     # 0x8A1
_tau[2][2210]  = 'PHONE_NAME'     # 0x8A2
_tau[2][2212]  = 'AC_VER'         # 0x8A4    # cust-reset.ta zeroes this (1 byte)

_tau[2][2226]  = 'RCK'                     # 0x8B2  # BL_UNLOCKCODE
_tau[2][2227]  = 'STARTUP_SHUTDOWNRESULT'  # 0x8B3
_tau[2][2228]  = 'CHECKPOINTS_ENABLED'     # 0x8B4
_tau[2][2229]  = 'CHECKPOINTS_REACHED'     # 0x8B5
_tau[2][2237]  = 'RESET_LOCK_STATUS'       # 0x8BD

_tau[2][2301]  = 'STARTUP_REASON'          # 0x8FD   # boot config override unit
_tau[2][2311]  = 'DISABLE_CHARGE_ONLY'     # 0x907
_tau[2][2312]  = 'DISABLE_USB_CHARGING'    # 0x908
_tau[2][2316]  = 'DISABLE_CHARGE_ONLY_ENTERPRISE' # 0x90C  # auto-boot.ta zeroes this (1 byte)
_tau[2][2330]  = 'OSV_RESTRICTION'         # 0x91A   # 1 byte

_tau[2][2401]  = 'FOTA_STATUS'             # 0x961
_tau[2][2402]  = 'FOTA_REPART'             # 0x962
_tau[2][2404]  = 'FOTA_INTERNAL'           # 0x964   # MODEM_CUST_CFG ?? cfg located in system/etc/customization/modem/ -> fota-reset.ta zeroes this

_tau[2][2460]  = 'VIRTUAL_UIM'             # 0x99C
_tau[2][2470]  = 'ENABLE_USB_ENG_PID'      # 0x9A6
_tau[2][2471]  = 'ENABLE_USB_DEBUGGING'    # 0x9A7
_tau[2][2473]  = 'ENABLE_SERIAL_CONSOLE'   # 0x9A9  # value 1 for enable serial console or value 0 (default) to disable (https://forum.xda-developers.com/showpost.php?p=80212371&postcount=1125)

_tau[2][2473]  = 'KERNEL_CMD_DEBUG_MASK'   # 0x9A9   # 1 byte
_tau[2][2475]  = 'FLASH_LOG'               # 0x9AB   # firmwares history log
_tau[2][2486]  = 'ENABLE_NONSECURE_USB_DEBUG'  # 0x9B6
_tau[2][2490]  = 'BATTERY_CAPACITY'        # 0x9BA

_tau[2][2495]  = 'DCMLAC_TRANSMISSION_CONFIG'  # 0x9BF 
_tau[2][2496]  = 'DCMLAC_SEND_TIME'            # 0x9C0 
_tau[2][2497]  = 'DCMLAC_UPLOAD_LOG_LATEST'    # 0x9C1 
_tau[2][2498]  = 'DCMLAC_IDDCONFIG_SW_VERSION' # 0x9C2 

_tau[2][2500]  = 'CREDMGR_KEYTABLE_PRESET' # 0x9C4
_tau[2][2501]  = 'SECURITY_GA_DATA'        # 0x9C5
_tau[2][2550]  = 'MASTER_RESET'            # 0x9F6  #
_tau[2][2551]  = 'BASEBAND_CFG'            # 0x9F7  # cfg located in the modem
_tau[2][2553]  = 'WIPE_REASON'             # 0x9F9

_tau[2][2560]  = 'WLAN_ADDR_0'             # 0xA00  WIFI_MAC
_tau[2][2561]  = 'WLAN_ADDR_1'             # 0xA01
_tau[2][2562]  = 'WLAN_ADDR_2'             # 0xA02
_tau[2][2563]  = 'WLAN_ADDR_3'             # 0xA03

_tau[2][2564]  = 'WLAN_TXPOWER_2_4G'       # 0xA04
_tau[2][2565]  = 'WLAN_TXPOWER_5G_LOW'     # 0xA05
_tau[2][2566]  = 'WLAN_TXPOWER_5G_MID'     # 0xA06
_tau[2][2567]  = 'WLAN_TXPOWER_5G_HIGH'    # 0xA07
_tau[2][2568]  = 'BD_ADDR'                 # 0xA08  BLUETOOTH_MAC

_tau[2][2570]  = 'MMS_USER_AGENT'          # 0xA0A
_tau[2][2571]  = 'MMSC_URL'                # 0xA0B

_tau[2][2585]  = 'LCD_NVM_1'               # 0xA19
_tau[2][2586]  = 'LCD_NVM_2'               # 0xA1A
_tau[2][2587]  = 'LCD_NVM_WRITE_COUNT'     # 0xA1B
_tau[2][2587]  = 'LCD_NVM_HWID'            # 0xA1C

_tau[2][2590]  = 'RETAIL_DEMO_ACTIVE_STATUS'  # 0xA1E
_tau[2][2595]  = 'PHONE_USAGE_FLAG'           # 0xA23
_tau[2][2601]  = 'NV_PREF_MODE_I'             # 0xA29
_tau[2][2602]  = 'NV_LIFE_TIMER_G_I'          # 0xA2A
_tau[2][2603]  = 'NV_SERVICE_DOMAIN_PREF_I'   # 0xA2B
_tau[2][4899]  = 'SONY_SERVICE_ID'            # 0x1323
_tau[2][4900]  = 'SERIAL_NO'               # 0x1324
_tau[2][4901]  = 'PBA_ID'                  # 0x1325
_tau[2][4902]  = 'PBA_ID_REV'              # 0x1326
_tau[2][4908]  = 'PP_SEMC_ITP_PRODUCT_NO'  # 0x132C
_tau[2][4909]  = 'PP_SEMC_ITP_REV'         # 0x132D

_tau[2][4952]  = 'NFC_CHIP_FW'                # 0x1358
_tau[2][4953]  = 'NFC_CHIP_VERSION'           # 0x1359
_tau[2][4960]  = 'GYRO_CALIBRATED'            # 0x1360
_tau[2][4961]  = 'MPU3050_CALIBRATION_DATA'   # 0x1361
_tau[2][4962]  = 'MPU6050_CALIBRATION_DATA'   # 0x1362
_tau[2][4963]  = 'ACCEL_CALIBRATION_DATA'     # 0x1363
_tau[2][4964]  = 'GYRO_CALIBRATION_DATA'      # 0x1364
_tau[2][4970]  = 'PROXIMITY_CALIBRATION_DATA' # 0x136A

_tau[2][10022]  = 'THERMAL_SHUTDOWN_COUNT'   # 0x2726
_tau[2][10023]  = 'THERMAL_LAST_SHUTDOWN_1'  # 0x2727
_tau[2][10024]  = 'THERMAL_LAST_SHUTDOWN_2'  # 0x2728
_tau[2][10025]  = 'THERMAL_LAST_SHUTDOWN_3'  # 0x2729

_tau[2][10100] = 'FLASH_MODE'              # 0x2774

_tau[2][10200] = 'FLIP_SLIDE_COUNTER'      # 0x27D8

_tau[2][66667] = 'DEVICE_KEY'              # 0x1046B  # DEVICE_KEY and DRM keys
_tau[2][66668] = 'REMOTE_LOCK'             # 0x1046C  # a sin file
_tau[2][66671] = 'GOOGLE_LOCK'             # 0x1046F  # google lock ( allow bootloader unlock in dev settings )
_tau[2][66673] = 'DEVICE_ID_HMAC_KEY'      # 0x10471  # dev_id HMAC key. Depend on existance of unit, = 0x874 (https://forum.xda-developers.com/showpost.php?p=82983507&postcount=1628)


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
    
