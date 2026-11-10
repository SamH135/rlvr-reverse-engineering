"""fcntl shim so verifiers.v1 imports on Windows hosts.

Only `flock` over a whole file is used (rate limiters, compose locks); it is
mapped onto msvcrt.locking of byte 0. On POSIX the real stdlib module wins
because lib-dynload precedes the .pth-added src dir on sys.path.
"""

import msvcrt
import os

LOCK_SH = 1
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def flock(fd: int, op: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if op & LOCK_UN:
        mode = msvcrt.LK_UNLCK
    elif op & LOCK_NB:
        mode = msvcrt.LK_NBLCK
    else:
        # shortcut: LK_LOCK retries internally for ~10s, not a true blocking wait
        mode = msvcrt.LK_LOCK
    msvcrt.locking(fd, mode, 1)
    os.lseek(fd, 0, os.SEEK_SET)
