"""Bounded, descriptor-relative reads for the local operator console."""
from contextlib import ExitStack, contextmanager
import os
import stat

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW


@contextmanager
def directory(root, parts=()):
    # Resolve each component against the open parent with O_NOFOLLOW. A concurrent
    # rename can replace a receipt but cannot redirect the open through a symlink.
    with ExitStack() as stack:
        fd = os.open(root, _DIRECTORY_FLAGS)
        stack.callback(os.close, fd)
        for part in parts:
            fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd


def read(root, parts, limit, *, growing=False):
    try:
        with directory(root, parts[:-1]) as parent:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or (not growing and before.st_size > limit):
                    return None
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(limit + 1)
                after = os.fstat(fd)
                if not growing and (len(data) != before.st_size or len(data) > limit
                                    or before.st_mtime_ns != after.st_mtime_ns
                                    or before.st_size != after.st_size):
                    return None
                return data, before.st_mtime_ns
            finally:
                os.close(fd)
    except OSError:
        return None


def names(root, parts):
    try:
        with directory(root, parts) as fd:
            return sorted(os.listdir(fd))
    except OSError:
        return []
