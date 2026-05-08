import platform
import collections
import sys

# ── WMI Hang Bypass ───────────────────────────────────────────────────────────
platform.system = lambda: "Windows"
platform.machine = lambda: "AMD64"
platform.release = lambda: "10"
platform.version = lambda: "10.0.19041"
_Uname = collections.namedtuple("uname_result", ["system", "node", "release", "version", "machine", "processor"])
platform.uname = lambda: _Uname("Windows", "DESKTOP", "10", "10.0.19041", "AMD64", "AMD64")
platform.win32_ver = lambda *a, **k: ("10", "10.0.19041", "SP0", "Multiprocessor Free")
# ──────────────────────────────────────────────────────────────────────────────

from celery.bin.celery import main as celery_main

if __name__ == "__main__":
    sys.argv[0] = "celery"
    sys.exit(celery_main())
