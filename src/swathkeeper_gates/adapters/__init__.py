"""Sniff the magic bytes and hand the file to its adapter (design §1). A missing parser extra is a
refusal naming the extra (exit 2), never an ImportError traceback: exit 1 would read as a FAIL."""
from ..contract import Refusal

DATAFLASH, ULOG = b"\xa3\x95", b"ULog\x01\x12\x35"


def load(path):
    try:
        with open(path, "rb") as f:
            head = f.read(len(ULOG))
    except OSError as e:
        raise Refusal(f"cannot read the log: {e}") from None
    if head.startswith(DATAFLASH):
        from . import ardupilot
        return ardupilot.read(path)
    if head.startswith(ULOG):
        raise Refusal("PX4 ULog detected: the px4 adapter is not shipped in this version "
                      "(design §1, stretch), so nothing was judged")
    raise Refusal(f"unknown log format: magic {head[:4].hex()} is neither DataFlash (a395) nor ULog")
