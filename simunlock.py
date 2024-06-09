import os
import sys
from os import path as osp

import logging
from logcfg import log

import somcusb
import somcta as ta


class SimUnlock():
    def __init__(self, sud = None, loglevel = logging.CRITICAL):
        self.test = 0
        self.loglevel = loglevel
        self.sud = sud
        if not self.sud:
            self.sud = somcusb.SomcUsbDevice(loglevel = loglevel)

    def connect(self):
        sud = self.sud
        sud.connect()
        self.max_download_size = int(sud.getvar('max-download-size'))
        
    def init_vars(self):
        sud = self.sud
        self.root_key_hash = sud.command('Get-root-key-hash')   # PLF_ROOT_HASH
        self.loader_ver = sud.getvar('Loader-version')
        self.phone_id = sud.getvar('Phone-id')
        self.device_id = sud.getvar('Device-id')
        self.rooting_status = sud.getvar('Rooting-status')  # Reading 325 bytes from RPMB, OK + Reading 325 bytes from RPMB, OK
        self.sector_size = sud.getvar('Sector-size', 'int')
        self.ufs_info = sud.getvar('Ufs-info')
        self.emmc_info = sud.getvar('Emmc-info')
        self.def_security = sud.getvar('Default-security')
        self.platform_id = sud.getvar('Platform-id')
        self.keystore_counter = sud.getvar('Keystore-counter', 'int')  # Reading 325 bytes from RPMB, OK
        self.security_state = sud.getvar('Security-state')             # Reading 325 bytes from RPMB, OK
        self.s1_root = sud.getvar('S1-root')
        self.sake_root = sud.getvar('Sake-root')    # Reading 325 bytes from RPMB, OK
        self.battery_level = sud.getvar('Battery', 'int')
        sud.getvar('Frp-partition')
        sud.getvar('Stored-security-state')   # Reading 325 bytes from RPMB, OK
        sud.getvar('Keystore-xcs')            # Reading 325 bytes from RPMB, OK
        sud.getvar('X-conf')
        sud.getvar('Soc-unique-id')
        self.blver = sud.getvar('version-bootloader')
        self.serialno = sud.getvar('serialno')

    def magic_func_001(self, u2129, sens_data, S1_LDR):
        # FIXME
        return None

    def unlock(self):
        sud = self.sud
        self.init_vars()
        
        u2129 = sud.read_ta( [2, 2129] )

        sens_data = sud.read_ta( [2, 2010] ) # SENS_DATA
        
        S1_LDR = sud.read_ta( [2, 2003] )    # S1_LDR

        # author: the_lazer
        new_sens_data = self.magic_func_001(u2129, sens_data, S1_LDR)

        if not self.test:
            ret = sud.write_ta( [2, 2010], new_sens_data )  # 0x278 bytes
            if ret is None:
                raise RuntimeError(f'Cannot write to SENS_DATA')
        
            ret = sud.write_ta( [2, 2128], bytes.fromhex('?? ?? ?? ??') )  # 4 bytes
            if ret is None:
                raise RuntimeError(f'Cannot write to [2:2128]')

            ret = sud.write_ta( [2, 2129], bytes.fromhex('?? ' * 0x3CA) )  # 0x3CA bytes
            if ret is None:
                raise RuntimeError(f'Cannot write to [2:2129]')
        
        sud.powerdown()
        
        txt = sud.dump_xbl_log(save_to_file = False)  # LAST_BOOT_LOG
        txt = sud.dump_xbl_log(save_to_file = False)  # LAST_BOOT_LOG
        
        max_download_size = int(sud.getvar('max-download-size'))
        product = sud.getvar('product')
        version = sud.getvar('version')
        blver = sud.getvar('version-bootloader')
        bbver = sud.getvar('version-baseband')
        serialno = sud.getvar('serialno')
        secure = sud.getvar('secure')
        sector_size = sud.getvar('Sector-size', 'int')
        loader_ver = sud.getvar('Loader-version')
        phone_id = sud.getvar('Phone-id')
        device_id = sud.getvar('Device-id')
        platform_id = sud.getvar('Platform-id')
        rooting_status = sud.getvar('Rooting-status')  # Reading 325 bytes from RPMB, OK + Reading 325 bytes from RPMB, OK
        ufs_info = sud.getvar('Ufs-info')
        emmc_info = sud.getvar('Emmc-info')
        def_security = sud.getvar('Default-security')
        keystore_counter = sud.getvar('Keystore-counter', 'int')  # Reading 325 bytes from RPMB, OK
        security_state = sud.getvar('Security-state')        # Reading 325 bytes from RPMB, OK
        s1_root = sud.getvar('S1-root')
        sake_root = sud.getvar('Sake-root')    # Reading 325 bytes from RPMB, OK
        root_key_hash = sud.command('Get-root-key-hash')   # PLF_ROOT_HASH
        
        slot_count = sud.getvar('slot-count', 'int')
        current_slot = sud.getvar('current-slot')
        battery_level = sud.getvar('Battery', 'int')
        
        if not self.test:
            ret = sud.write_ta('FLASH_MODE', b'\x01')  # [2:10100]
            if ret is None:
                raise RuntimeError(f'Flash mode cannot activate!')

            """
            author: the_lazer ; link: https://xdaforums.com/t/3777538/post-76291096
            
            In order to enable locking/unlocking of the bootloader through
              FG4, the xfl has support for oem lock/unlock commands. When executing
              those commands, the xfl writes data in miscTA, which is then verified by
              the boot on the next boot up, and if valid, the bootloader is locked or
              unlocked respectively.

            1. If MiscTA Unit 2226 (TA_RCK) is not empty, the boot SHALL check whether 
              unlocking of the bootloader is allowed.

              If unlocking of the bootloader is allowed and the RCK is valid, the bootloader SHALL be unlocked.
              Before unlocking the bootloader, the userdata and cache partitions, as well
              as MiscTA Unit 66667 (TA_DEVICE_KEY) MUST be erased.
              After unlocking the bootloader, MiscTA Unit 2550 (TA_MASTER_RESET) SHALL
              be set to 0x2.
              MiscTA Unit 2226 MUST be erased after the check.

            2. If MiscTA Unit 2237 (TA_RESET_LOCK_STATUS) is not empty, 
               the boot SHALL validate whether the content of the unit is a valid CMS signed message.

              If the message is verified, the bootloader SHALL be locked.
              Before locking the bootloader, the userdata and cache partitions, as well as
              MiscTA Unit 66667 (TA_DEVICE_KEY) MUST be erased.
              After locking the bootloader, MiscTA Unit 2550 (TA_MASTER_RESET) SHALL
              be set to 0x2.
              MiscTA Unit 2237 MUST be erased after the check.
            """

            RCK = bytes.fromhex('?? ' * 0x10)
            ret = sud.write_ta('BL_UNLOCKCODE', RCK)  # [2:2226]  16 bytes
            if ret is None:
                raise RuntimeError(f'Cannot write to [2:2226]')
        
        txt = sud.read_ta('FLASH_LOG')   # [2:2475]
        if txt is None:
            log.error(f'Cannot get FW history log: {sud.lastresp}')
        else:
            #log.debug('Firmware history log: \n' + txt.decode('latin-1'))
            pass
        
        if not self.test:
            sud.set_current_slot('a')
            
            ret = sud.write_ta('FLASH_MODE', b'\x00')  # [2:10100]
            if ret is None:
                raise RuntimeError(f'Flash mode cannot deactivate!')
            
        log.info(f'Sent command: "Sync" ...')
        if self.test:
            log.info(f'  Skip "Sync" command! Reason: test = {self.test}')
        else:
            rt = sud.read_timeout
            wt = sud.write_timeout
            sud.read_timeout = 5*1000   # 5 seconds
            sud.write_timeout = 5*1000  # 5 seconds

            ret = sud.command('Sync')
            if ret is None:
                raise RuntimeError(f'Command "Sync" fail: {sud.lastresp}')
            
            sud.read_timeout = rt
            sud.write_timeout = wt
            log.info(f'Command "Sync" completed!')

        if not self.test:
            sud.command('reboot-bootloader')
            log.info(f'Rebooting the device into bootloader mode')
        
        log.info(f'======= SIM Unlock completed ======= test: {self.test}')


if __name__ == '__main__':
    import optparse
    parser = optparse.OptionParser("usage: %prog [options]", add_help_option = False)
    parser.add_option("-t", "--test", dest = "test", default = 1, type = "int")
    parser.add_option("-T", "--timeout", dest = "timeout", default = None, type = "int")
    parser.add_option("", "--rt", dest = "read_timeout", default = 500, type = "int")
    parser.add_option("", "--wt", dest = "write_timeout", default = 1000, type = "int")
    parser.add_option("-v", "--verbose", dest = "verbose", default = 1, type = "int")
    (opt, args) = parser.parse_args() 
    
    try:
        loglevel = logging.DEBUG if opt.verbose else logging.INFO
        xx = SimUnlock(loglevel = loglevel)
        xx.test = opt.test
        
        if opt.timeout:
            rt = opt.timeout
            wt = opt.timeout
        else: 
            rt = opt.read_timeout
            wt = opt.write_timeout
            
        log.info(f'Set read  timeout = {rt} ms')
        xx.sud.read_timeout = rt
        log.info(f'Set write timeout = {wt} ms')
        xx.sud.write_timeout = wt
        
        xx.connect()
        xx.unlock()
    
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








