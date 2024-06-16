import os
import sys
from os import path as osp

import json
import gzip
import zlib
import tarfile
import xml.etree.ElementTree as ET

import logging
from logcfg import log

import somcusb
import somcta as ta


class SXFlasher():
    def __init__(self, sud = None, loglevel = logging.CRITICAL):
        self.test = 0
        self.loglevel = loglevel
        self.wdir = None
        self.sud = sud
        if not self.sud:
            self.sud = somcusb.SomcUsbDevice(loglevel = loglevel)
        self.erase_user_data = False
        self.flashmode = False
        self.sync_timeout = 30  # 30 seconds

    def connect(self):
        if self.test < 100:
            self.sud.connect()
            
        self.init_vars()
        
        if self.test >= 100:
            self.sud.cmd_sign_with_data_allow = False
        else:
            self.sud.check_signature_cmd()
        
    def init_vars(self):
        sud = self.sud
        if self.test >= 100:
            self.ufs_info = '__UFS__'
            self.max_download_size = 400*1000*1000
            self.sector_size = 0x1000
            self.slot_count = 2
            self.current_slot = 'a'
            self.flash_booth_slots = True
            self.battery_level = None
            self.def_security = 'OFF'
            return

        self.max_download_size = int(sud.getvar('max-download-size'))
        self.sector_size = sud.getvar('Sector-size', 'int')
        self.product = sud.getvar('product')
        self.version = sud.getvar('version')
        self.blver = sud.getvar('version-bootloader')
        self.bbver = sud.getvar('version-baseband')
        self.serialno = sud.getvar('serialno')
        self.secure = sud.getvar('secure')
        self.loader_ver = sud.getvar('Loader-version')
        self.phone_id = sud.getvar('Phone-id')
        self.device_id = sud.getvar('Device-id')
        self.platform_id = sud.getvar('Platform-id')
        self.rooting_status = sud.getvar('Rooting-status')
        self.ufs_info = sud.getvar('Ufs-info')
        self.emmc_info = sud.getvar('Emmc-info')
        self.def_security = sud.getvar('Default-security')
        self.keystore_counter = sud.getvar('Keystore-counter', 'int')
        self.security_state = sud.getvar('Security-state')

        sud.getvar('Stored-security-state')
        sud.getvar('Keystore-xcs')

        self.s1_root = sud.getvar('S1-root')
        self.sake_root = sud.getvar('Sake-root')
        self.root_key_hash = sud.command('Get-root-key-hash')   # PLF_ROOT_HASH
        self.slot_count = sud.getvar('slot-count', 'int')
        self.current_slot = sud.getvar('current-slot')
        self.battery_level = sud.getvar('Battery', 'int')
        sud.getvar('Frp-partition')
        sud.getvar('X-conf')
        sud.getvar('Soc-unique-id')
        
        self.flash_booth_slots = False
        if self.slot_count is not None:
            if self.slot_count == 2:
                # flash bootloader,bluetooth,dsp,modem,rdimage to booth a,b slots
                self.flash_booth_slots = True
    
    def check_battery(self):
        if self.battery_level is not None:
            low = False
            if self.battery_level > 1150:
                units = ' mV'
                if self.battery_level < 3750:
                    low = True
            else:
                units = '%'
                if self.battery_level < 17:
                    low = True
            if low:
                log.warn(f'Your battery level is {self.battery_level}{units} and you have risk ' +
                    'for hard brick in case your battery get fully discharged durring flash session!')

    def change_flashmode(self, active):
        if active:
            log.info('Flash mode activation...')
        else:    
            log.info('Flash mode deactivation...')
        if self.test:
            log.info('  Skip! reasone: TEST MODE')
            return
        
        data = b'\x01' if active else b'\x00'
        ret = self.sud.write_ta('FLASH_MODE', data)
        if ret is None:
            raise RuntimeError(f'Flash mode cannot set to {data}')
        
        self.flashmode = True if active else False

    def activate_flashmode(self):
        return self.change_flashmode(True)

    def deactivate_flashmode(self, fin = False):
        if fin and self.flashmode:
            try:
                self.sud.set_timeouts(200)
                self.change_flashmode(False)
            except Exception:
                pass
            return
            
        return self.change_flashmode(False)
        
    def get_partition_list(self, source = 'xml'):
        pdir = self.wdir + os.path.sep + 'partition'
        if not os.path.exists(pdir):
            raise RuntimeError(f'Directory "{pdir}" not found!')
        
        if source != 'xml':
            images = [ ]
            for fn in os.listdir(pdir): 
                fn = pdir + osp.sep + fn
                if os.path.isfile(fn):
                    if fn.endswith('.sin'):
                        images.append(fn)
            return images
        
        deliv = pdir + os.path.sep + 'partition_delivery.xml'
        if not os.path.exists(deliv):
            #raise RuntimeError(f'File "{deliv}" not found!')
            log.warn(f'File "{deliv}" not found!')
            return [ ]

        tree = ET.parse(deliv)
        root = tree.getroot()
        if root.tag != 'PARTITION_DELIVERY':
            raise RuntimeError(f'Incorrect XML root name "{root.tag}", expected "PARTITION_DELIVERY"')

        fmt = root.attrib['FORMAT']
        if fmt != '1':
            raise RuntimeError(f'Incorrect XML format = "{fmt}", expected "1"')

        images = [ ]
        for child in root:
            if child.tag == 'PARTITION_IMAGES':
                for file in child:
                    if file.tag == 'FILE':
                        file_path = file.attrib['PATH']
                        if len(file_path) > 1:
                            fname = pdir + os.path.sep + file_path
                            if not os.path.exists(fname):
                                raise RuntimeError(f'File "{fname}" not found!')
                            images.append( fname )
        
        return images
    
    def get_boot_delivery(self):
        bootdir = self.wdir + os.path.sep + 'boot'
        if not os.path.exists(bootdir):
            raise RuntimeError(f'Directory "{bootdir}" not found!')
        
        deliv = bootdir + os.path.sep + 'boot_delivery.xml'
        if not os.path.exists(deliv):
            raise RuntimeError(f'File "{deliv}" not found!')

        tree = ET.parse(deliv)
        root = tree.getroot()
        if root.tag != 'BOOT_DELIVERY':
            raise RuntimeError(f'Incorrect XML root name "{root.tag}", expected "BOOT_DELIVERY"')

        bd = { }
        bd['format'] = int(root.attrib['FORMAT'])
        bd['product'] = root.attrib['PRODUCT']
        bd['space_id'] = root.attrib['SPACE_ID']
        bd['version'] = root.attrib['VERSION']
        configs = bd['configs'] = { }
        for _conf in root:            
            if _conf.tag == 'CONFIGURATION':
                confname = _conf.attrib['NAME']
                conf = configs[confname] = { }
                conf['name'] = confname
                conf['boot_config'] = [ ]
                conf['boot_images'] = [ ]
                conf['attrs'] = { }
                conf['hwconf'] = { }
                conf['keystore'] = { }
                conf['sec_prop'] = { }
                conf['sec_state'] = None
                for _cfgitem in _conf:
                    if _cfgitem.tag == 'BOOT_CONFIG':
                        for _tafile in _cfgitem:
                            if _tafile.tag == 'FILE':
                                conf['boot_config'].append(_tafile.attrib['PATH'])
                    
                    if _cfgitem.tag == 'BOOT_IMAGES':
                        for _sinfile in _cfgitem:
                            if _sinfile.tag == 'FILE':
                                conf['boot_images'].append(_sinfile.attrib['PATH'])
                    
                    if _cfgitem.tag == 'ATTRIBUTES':
                        _attrs = _cfgitem.attrib['VALUE']
                        alst = _attrs.split(';')
                        for av in alst:
                            name = av.split('=')[0]
                            value = av.split('=')[1]
                            if value[:1] == '"' and value[-1:-2] == '"':
                                conf['attrs'][name] = value
                            else:
                                conf['attrs'][name] = value[1:-1]
                            
                    if _cfgitem.tag == 'HWCONFIG':
                        conf['hwconf']['cert'] = _cfgitem.attrib['CERTIFICATE']
                        conf['hwconf']['rev'] = _cfgitem.attrib['REVISION']
                        conf['hwconf']['ver'] = _cfgitem.attrib['VERSION']

                    if _cfgitem.tag == 'KEYSTORE':
                        conf['keystore']['cert'] = _cfgitem.attrib['CERTIFICATE']
                        conf['keystore']['rev'] = _cfgitem.attrib['REVISION']

                    if _cfgitem.tag == 'SECURITY_PROPERTIES':
                        conf['sec_prop']['rev'] = _cfgitem.attrib['REVISION']

                    if _cfgitem.tag == 'SECURITY_STATE':
                        conf['sec_state'] = _cfgitem.attrib['VALUE']
            
        return bd
    
    def check_in_updatexml(self, fname):
        xmlfn = self.wdir + os.path.sep + 'update.xml'
        if not osp.exists(xmlfn):
            raise RuntimeError(f'File "{xmlfn}" not found!')
        
        tree = ET.parse(xmlfn)
        root = tree.getroot()
        if root.tag != 'UPDATE':
            raise RuntimeError(f'Incorrect XML root name "{root.tag}", expected "UPDATE"')
        
        for child in root:
            if child.text == fname:
                return child.tag
                
        return None
    
    def process_partition(self, plst):
        sud = self.sud
        log.info("Repartitioning...")

        if self.ufs_info:
            stor_name = 'LUN0'
            cmd = 'Get-ufs-info'
        else:    
            stor_name = "EMMC_part_0"
            cmd = 'Get-emmc-info'
        
        log.info(f'Determining {stor_name} size...')
        if self.test >= 100:
            lun0_sz = 0x10
        else:
            stor_info = sud.command(cmd)
            if not stor_info or len(stor_info) < 0x20:
                raise RuntimeError(f'Error receiving {stor_name} header')
            
            if self.ufs_info:
                ufs_desc_sz = int.from_bytes(stor_info[0:1], byteorder = 'big')
                pos = ufs_desc_sz + 0x1C
                if len(stor_info) < pos + 4:
                    raise RuntimeError(f'Error receiving {stor_name} size')
                lun0_sz = int.from_bytes(stor_info[pos:pos+4], byteorder = 'big')
            else:
                pos = 0xD4
                if len(stor_info) < pos + 4:
                    raise RuntimeError(f'Error receiving {stor_name} size')
                lun0_sz = int.from_bytes(stor_info[pos:pos+4], byteorder = 'little')

            if not self.sector_size:
                raise RuntimeError(f'Cannot determine sector size!')
            
            if lun0_sz > 0:
                lun0_sz *= self.sector_size
                lun0_sz //= 1024

        log.info(f'{stor_name} size = 0x{lun0_sz:X} ({lun0_sz})')
        
        if lun0_sz > 0:
            for fn in plst:
                log.info(f'Processing part: "{osp.basename(fn)}"')
                if not(f'LUN0' in fn or 'LUN1' in fn or 'LUN2' in fn or 'LUN3' in fn):
                    log.warn(f'  Skipping partition "{osp.basename(fn)}" (Incorrect name)')
                    continue
                
                if 'LUN0' in fn and f'LUN0_{lun0_sz}_' not in fn and 'LUN0_X-FLASH-ALL' not in fn:
                    log.warn(f'  Skipping partition "{osp.basename(fn)}" (Incorrect Name)')
                    continue

                self.process_sin(fn, aux_cmd = "Repartition")
        pass
    
    def _xboot_crash(self):
        sud = self.sud
        imgname = 'partition-image-LUN0_62455808_X-FLASH-ALL-906F.sin'
        ret = sud.getvar(f'has-slot:{imgname}', 'str')
        if ret is None:
            log.warn(f'Cannot get slot for image "{imgname}"')
            return False
        return True
    
    def get_imgname_by_sin(self, fn):
        fsz = osp.getsize(fn)
        if fsz < 64:
            return None       
        
        bufsz = 512 if fsz > 512 else fsz
        with open(fn, 'rb') as file:
            data = file.read(bufsz)

        if data[0:2] == b'\x1F\x8B':
            file = open(fn, 'rb')
            try:
                gz = gzip.GzipFile(fileobj = file)
                buff = gz.read(512)
            finally:
                file.close()
            
            if len(buff) < 512:
                return None
                
            data = buff
                
        if len(data) < 512:
            return None
        
        if data[0x101:0x107] != b'ustar\x00':
            return None
        
        first_filename = data[0:100].decode('latin-1')
        if len(first_filename) == 0:
            return None
            
        if first_filename.startswith('.'):
            return None
        
        return osp.splitext(first_filename)[0]
    
    def process_sin(self, filename, aux_cmd = 'flash'):
        sud = self.sud
        has_slot = False
        if osp.sep not in filename:
            filename = self.wdir + osp.sep + filename
        
        sinfn = osp.basename(filename)
        sinsize = osp.getsize(filename)
        
        ret = self.check_in_updatexml(sinfn)
        log.debug(f'check_in_updatexml("{sinfn}") => "{ret}"')
        if ret and ret == 'NOERASE':
            if not self.erase_user_data:
                log.debug(f'  Skip SIN-file "{sinfn}". Reason: update.xml = "{ret}" and erase_user_data is False')
                return

        if sinsize < 512:
            raise RuntimeError(f'Incorrect SIN-file size: {sinsize} bytes')

        with tarfile.open(filename) as tar: 
            log.debug(f'Unpacking file "{sinfn}" ... ')
            imgname = None
            num = -2    
            for member in tar:
                if member.type != tarfile.REGTYPE:
                    continue  # process only regular files
                
                fn = member.name
                stream = tar.extractfile(member)
                if stream is None:  # process only regular files
                    continue
                
                cname = f'{sinfn}/{fn}'
                if sinsize > 50*1000*1000:
                    log.debug(f'process sin chunk: "{cname}" ...')
                
                data = stream.read()
                if len(data) >= self.max_download_size:
                    raise RuntimeError(f'Chunk "{cname}" very large! Size = {len(data)}, max = {self.max_download_size}')

                if len(data) == 0:
                    raise RuntimeError(f'Chunk "{cname}" is empty! Size = {len(data)}')

                if self.test >= 100:
                    log.info(f'  Skip sin chunk "{cname}", size: {len(data)} ! Reason: test = {self.test}')
                    continue

                num += 1
                if num == -1:  # CMS
                    imgname = osp.splitext(fn)[0]
                    if not fn.endswith('.cms'):
                        raise RuntimeError(f'File "{cname}" contain incorrect CMS (ext)')
                    
                    if data[0:2] != b'\x30\x82':
                        raise RuntimeError(f'File "{cname}" contain incorrect CMS (magic)')
                    
                    log.info(f'Uploading signature "{cname}" (size:{len(data)})')
                    ret = sud.upload(data, sign = sud.cmd_sign_with_data_allow)
                    if not ret:
                        raise RuntimeError(f'CMD: "signature:{len(data):08X}" ==> {sud.lastresp}')
                    
                    if not sud.cmd_sign_with_data_allow:
                        ret = sud.command('signature')
                        if ret is None:
                            raise RuntimeError(f'CMD: signature ==> {sud.lastresp}')
                    
                    log.info('  Signature: OKAY')
                    continue  # CMS file processed
                
                if osp.splitext(fn)[0] != imgname:
                    raise RuntimeError(f'File "{sinfn}" contain incorrect filename: "{fn}", expected: "{imgname}"')
                
                log.info(f'Uploading chunk "{cname}" (size:{len(data)})')
                ret = sud.upload(data)

                #if self.test:
                #    sud.upload(b'')  # erase xboot download buffer

                erase_cmd = ''
                if num == 0 and aux_cmd == 'flash':
                    erase_cmd = f'erase:{imgname}'
                    if self.current_slot and (self.current_slot == 'a' or self.current_slot == 'b'):
                        ret = sud.getvar(f'has-slot:{imgname}', 'str')
                        if ret is None:
                            raise RuntimeError(f'Cannot get slot for image "{imgname}"')
                        
                        if ret == 'yes':
                            has_slot = True
                            log.info(f'Partition "{imgname}" have slot "{self.current_slot}"');
                            if '_other' in sinfn:
                                if self.current_slot == 'a':
                                    erase_cmd = f'erase:{imgname}_b'
                                else:
                                    erase_cmd = f'erase:{imgname}_a'
                            else:        
                                if self.current_slot == 'a':
                                    erase_cmd = f'erase:{imgname}_a'
                                else:
                                    erase_cmd = f'erase:{imgname}_b'
                if erase_cmd:    
                    log.info(f'CMD: {erase_cmd}')
                    if self.test:
                        log.info(f'  Skip erase! Reason: test = {self.test}')
                    else:
                        ret = sud.command(erase_cmd)
                        if ret is None:
                            raise RuntimeError(f'Cannot erase image: "{imgname}"')
                        
                if aux_cmd:
                    cmd = f'{aux_cmd}:{imgname}'
                    if aux_cmd == 'Repartition' and imgname.startswith('partitionimage_'):
                        # Oreo changed partition image name, so this is a quick fix
                        cnum = imgname.replace('partitionimage_', '')
                        cmd = f'Repartition:{cnum}'
                    elif has_slot:
                        if '_other' in sinfn:
                            if self.current_slot == 'a':
                                cmd = f'{aux_cmd}:{imgname}_b'
                            else:
                                cmd = f'{aux_cmd}:{imgname}_a'
                        else:        
                            if self.current_slot == 'a':
                                cmd = f'{aux_cmd}:{imgname}_a'
                            else:
                                cmd = f'{aux_cmd}:{imgname}_b'
                    
                    log.info(f'CMD: {cmd}')
                    if self.test:
                        log.info(f'  Skip {cmd.split(":")[0]}! Reason: test = {self.test}')
                    else:
                        ret = sud.command(cmd)
                        if ret is None:
                            raise RuntimeError(f'Cannot {aux_cmd} image: "{imgname}". Error: {sud.lastresp}')

    def process_ta(self, filename, max_units = None):
        sud = self.sud
        tafn = osp.basename(filename)
        tasize = osp.getsize(filename)
        log.info(f'Process TA-file "{tafn}" ...')
        taulist = ta.load_from_file(filename)
        if not taulist:
            raise RuntimeError(f'Incorrect ta-file "{tafn}"')
            
        if max_units:
            if len(taulist) > max_units:
                raise RuntimeError(f'Incorrect ta-file "{tafn}"! Too many units. Expected <= {max_units}')
            
        for tau in taulist:
            if tau.part == 2:
                if tau.code in [ 2003,    # hw config
                                 2010,    # simlock
                                 2129,    # simlock signature
                                 2210,    # PHONE_NAME
                                 4900,    # SERIAL_NO 
                                 66667,   # DEVICE_KEY
                    ]:
                    log.debug(f'  Skip TA unit from "{tafn}". Reason: unit [2:{tau.code}] are special!')
                    continue
            cmd = f'Write-TA:{tau.part}:{tau.code}'
            log.info(f'CMD: {cmd}   <size = {len(tau.value)}>')
            if self.test:
                log.info(f'  Skip "{tafn}"! Reason: test = {self.test}')
            else:
                ret = sud.write_ta( [tau.part, tau.code], tau.value)
                if ret is None:
                    raise RuntimeError(f'Cannot {cmd} ! Error: {str(sud.lastresp)}')
    

    def flash_stock(self, wdir):
        self.wdir = wdir
        sud = self.sud
        
        self.connect()
        self.check_battery()
        
        log.info(f'Firmware directory: "{wdir}"')
        log.info(f'test = {self.test}')
        
        self.activate_flashmode()

        if not self.test:
            txt = sud.dump_err_log()
            if txt is None:
                log.error(f'Cannot get Error log: {sud.lastresp}')

        # ------------ Repartition ----------------------------------------
        pdir = self.wdir + os.path.sep + 'partition'
        if not os.path.exists(pdir):
            log.warn(f'Directory "{pdir}" not found!')
        else:
            plst = self.get_partition_list('xml')
            if not plst:
                plst = self.get_partition_list('dir')
            if not plst:
                raise RuntimeError(f'Partition SINs not founded!')
            
            self.process_partition(plst)

        # ------------ sin-files ----------------------------------------
        for fn in os.listdir(self.wdir): 
            filename = self.wdir + osp.sep + fn
                
            if not fn.endswith('.sin'):
                continue

            if 'partition' in fn.lower():
                continue

            if 'persist' in fn.lower():
                continue
                
            log.info(f'Processing "{fn}" ...')
            
            imgname = self.get_imgname_by_sin(filename)
            if not imgname:
                raise RuntimeError(f'Cannot get image name for SIN: "{fn}"')
            
            if self.flash_booth_slots:
                if imgname in [ 'bootloader', 'bluetooth', 'dsp', 'modem', 'rdimage' ]:
                    try:
                        remember_current_slot = self.current_slot
                        self.current_slot = 'b' if self.current_slot == 'a' else 'a'
                        self.process_sin(filename)
                    finally:
                        self.current_slot = remember_current_slot
                    pass
        
            if self.test >= 101:
                if osp.getsize(filename) > 200*1000*1000:
                    log.info(f'  Skip SIN "{osp.basename(filename)}" ! Too large! test = {self.test}')
                    continue
            
            self.process_sin(filename)
        
        # ------------ ta-files ----------------------------------------
        for fn in os.listdir(self.wdir): 
            filename = self.wdir + osp.sep + fn
            if fn.endswith('.ta'):
                log.info(f'Processing "{fn}" ...')
                ret = self.check_in_updatexml(fn)
                log.debug(f'check_in_updatexml("{fn}") => "{ret}"')
                if ret and ret == 'NOERASE':
                    if not self.erase_user_data:
                        log.debug(f'  Skip TA-file "{fn}". Reason: update.xml = "{ret}" and erase_user_data is False')
                        continue
                
                self.process_ta(filename, max_units = 1)
        
        # ------------ xboot image ----------------------------------------
        bd = self.get_boot_delivery()
        #print(json.dumps(bd, indent = 4))
        
        log.info(f'Boot delivery product: {bd["product"]}')
        log.info(f'Boot delivery version: {bd["version"]}')
        log.info(f'Verifying if boot delivery match with device...')
        bd_conf = None
        for key, conf in bd['configs'].items():
            attrs = conf['attrs']
            if self.def_security == 'OFF':
                if 'DEFAULT_SECURITY' in attrs:
                    if attrs['DEFAULT_SECURITY'] == 'OFF':
                        bd_conf = conf
                        break
            else:
                plat_id = '00' + self.platform_id[2:]
                if 'PLATFORM_ID' in attrs and 'PLF_ROOT_HASH' in attrs:
                    PLF_ROOT_HASH = bytes.fromhex(attrs['PLF_ROOT_HASH'])
                    if attrs['PLATFORM_ID'] == plat_id and PLF_ROOT_HASH == self.root_key_hash:
                        bd_conf = conf
                        break

        if not bd_conf:
            raise RuntimeError(f'Didn\'t found boot_delivery that match your device!')

        log.info(f'Found boot delivery match: "{bd_conf["name"]}"')
        log.debug(f'Boot delivery selected configuration: \n' + json.dumps(bd_conf, indent = 4))
        boot_images = bd_conf['boot_images']

        if not boot_images:
            raise RuntimeError(f'Cannot found SIN-file for boot image!')

        if len(boot_images) > 1:
            raise RuntimeError(f'Cannot flash several boot images!')
            
        bootdir = self.wdir + osp.sep + 'boot'

        boot_sin_fn = boot_images[0]
        if not boot_sin_fn:
            raise RuntimeError(f'Cannot found SIN-file for boot image! Empty SIN filename!')
            
        boot_sin_filename = bootdir + osp.sep + boot_sin_fn
        if not osp.isfile(boot_sin_filename):
            raise RuntimeError(f'File "boot/{boot_sin_fn}" not found!')
        
        for fn in bd_conf['boot_config']: 
            filename = bootdir + osp.sep + fn
            if not fn.endswith('.ta'):
                raise RuntimeError(f'Incorrect TA-file name: "{fn}"')
            
            log.info(f'Processing "boot/{fn}" ...')
            self.process_ta(filename, max_units = None)
            
        log.info(f'Processing "boot/{boot_sin_fn}" ...')
        imgname = self.get_imgname_by_sin(boot_sin_filename)
        if imgname != 'bootloader':
            raise RuntimeError(f'Incorrect SIN image name: "{imgname}"')
        
        self.process_sin(boot_sin_filename)
        
        # ------------ xboot log ----------------------------------------
        if self.test < 100:
            txt = sud.dump_err_log()
            if txt is None:
                log.error(f'Cannot get Error log: {sud.lastresp}')

            #txt = sud.dump_xbl_log()
            #if txt is None:
            #    log.error(f'Cannot get XBoot log: {sud.lastresp}')

        # ------------ fw history log ------------------------------------
        if self.test < 100:
            txt = sud.read_ta( [2, 2475] )   # FLASH_LOG
            if txt is None:
                log.error(f'Cannot get FW history log: {sud.lastresp}')
            else:
                log.debug('Firmware history log: \n' + txt.decode('latin-1'))
        
        # ------------ set slot active ----------------------------------
        if not self.test and self.current_slot is not None:
            slot = sud.set_current_slot(self.current_slot)
            if slot:
                log.info(f'Set slot "{slot}" active')
        
        # ------------ get out of flash mode ----------------------------
        self.deactivate_flashmode()
        
        # ------------ Sync -----------------------------------------
        log.info(f'Sent command: "Sync" ...')
        if self.test:
            log.info(f'  Skip "Sync" command! Reason: test = {self.test}')
        else:
            trw = sud.get_timeouts()
            sud.set_timeouts(self.sync_timeout * 1000) # default: 30 seconds

            ret = sud.command('Sync')
            if ret is None:
                log.error(f'Command "Sync" fail: {sud.lastresp}')
            
            sud.set_timeouts(trw)
            log.info(f'Command "Sync" completed!')
        
        # ------------ finish -----------------------------------------
        log.info(f'======= Flashing completed ======= test: {self.test}')
        if not self.test:
            txt = sud.dump_err_log()


if __name__ == '__main__':
    import optparse
    parser = optparse.OptionParser("usage: %prog [options]", add_help_option = False)
    parser.add_option("-d", "--dir", dest = "dir", default = "", type = "string")
    parser.add_option("-t", "--test", dest = "test", default = 1, type = "int")
    parser.add_option("-T", "--timeout", dest = "timeout", default = None, type = "int")
    parser.add_option("", "--rt", dest = "read_timeout", default = 4000, type = "int")
    parser.add_option("", "--wt", dest = "write_timeout", default = 4000, type = "int")
    parser.add_option("-S", "--sync", dest = "sync_timeout", default = 30, type = "int")
    parser.add_option("-v", "--verbose", dest = "verbose", default = 1, type = "int")
    parser.add_option("-e", "--eud", dest = "erase_user_data", action="store_true", default = False)
    (opt, args) = parser.parse_args() 
    
    if not opt.dir:
        log.error(f'Working directory not specified')
        exit(1)

    if not osp.isdir(opt.dir):
        log.error(f'Working directory "{opt.dir}" not found')
        exit(1)
     
    try:
        loglevel = logging.DEBUG if opt.verbose else logging.INFO
        sxf = SXFlasher(loglevel = loglevel)
        sxf.test = opt.test
        
        if opt.timeout:
            rt = opt.timeout
            wt = opt.timeout
        else: 
            rt = opt.read_timeout
            wt = opt.write_timeout
            
        log.info(f'Set read  timeout = {rt} ms')
        sxf.sud.read_timeout = rt
        log.info(f'Set write timeout = {wt} ms')
        sxf.sud.write_timeout = wt
        
        sxf.erase_user_data = opt.erase_user_data
        sxf.sync_timeout = opt.sync_timeout
        
        sxf.flash_stock(opt.dir)
    
    except Exception:
        log.error('CRITICAL ERROR')
        log.set_level(100)
        log.exception('CRITICAL ERROR')
        if sxf and sxf.flashmode:
            sxf.deactivate_flashmode(fin = True)
        raise
    
    except KeyboardInterrupt:
        log.error('---- KeyboardInterrupt ----')
        log.set_level(100)
        log.exception('---- KeyboardInterrupt ----')
        if sxf and sxf.flashmode:
            sxf.deactivate_flashmode(fin = True)
        raise








