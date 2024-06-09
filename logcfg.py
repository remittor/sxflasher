import os
import sys
import logging
from datetime import datetime

import logging
import logging.config


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "for_files": {
            "format": "%(asctime)s [%(levelname)-5s] %(message)s"
        },
        "for_stdout": {
            "format": "[%(levelname)-5s] %(message)s"
        }
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": None,
            "formatter": "for_files",
            "level": "DEBUG"
        },
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "for_stdout",
            "level": "DEBUG"
        }
    },
    "loggers": {
        "sxflasher": {
            "handlers": [ "file", "console" ],
            "propagate": "no"
        }
    },
    "root": {
        "handlers": [ "file", "console" ]
    }
}


log = None
_init_time = None

def _set_log_level(level, hnum = 1):
    log.handlers[hnum].setLevel(level)

def get_logger():
    _log = logging.getLogger('sxflasher')
    _log.set_level = _set_log_level
    _log.warn = _log.warning
    return _log


try:  
    _init_time = os.environ["SXF_INIT_TIME"]
except KeyError:
    _init_time = None


   
if _init_time is not None:
    log = get_logger()
else:
    basedir = os.path.dirname(__file__)
    logsdir = os.path.join(basedir, "logs")
    os.makedirs(logsdir, exist_ok = True)
    
    _init_time = datetime.now().strftime('%Y-%m-%d__%H-%M-%S')
    log_file = os.path.join(logsdir, f"sxf__{_init_time}.log")

    os.environ["SXF_INIT_TIME"] = _init_time

    LOGGING_CONFIG['handlers']['file']['filename'] = log_file
    logging.config.dictConfig(LOGGING_CONFIG)

    log = get_logger()
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.set_level(logging.DEBUG)
    log.debug(f'====================== sxflasher =========================')
    log.set_level(logging.ERROR)


