"""Small portable runtime boundaries; these do not change routing policy."""
import os


def lock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        os.lseek(descriptor, 0, os.SEEK_END)
    else:
        import fcntl
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(descriptor, fcntl.LOCK_UN)
