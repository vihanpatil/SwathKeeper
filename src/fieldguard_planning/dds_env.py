"""DDS/transport environment snapshot — the control that makes a lever flight attributable.

Round 3 (2026-08-22) traced the large-sample frame loss to a Fast DDS mechanism, not to QoS: every
sample fragments at **65,384 B even over shared memory** (SHM's own `max_message_size` defaults to
65500 and the participant takes the MINIMUM across registered transports, where UDPv4 is hard-capped
at 65500), and only **eight** such fragments fit in the default 512 KiB SHM segment. On exhaustion
Fast DDS discards the fragment and reports success — no error, no warning, no counter. That silence
is why this file exists.

The lever is a Fast DDS XML profile that enlarges the segment. Its failure mode is equally silent:
**malformed XML falls back to defaults with only a log line**, so a flight can read 20 % delivery and
be unattributable between "the lever did nothing" and "the lever never loaded". The two numbers that
separate those are here:

  * `shm_segments.max_bytes` — proves the profile took effect at all (default segment files measure
    **549,408 B** = 512 KiB + ~25 KB header; an 8 MiB profile measures ~8.4 MB).
  * `shm_segments.min_bytes` — proves NO participant missed it. Segments are container-global, so one
    reader sees every participant's segment; a single un-injected process leaves a 549,408 B segment
    in the set. Partial injection is the round's sharpest self-inflicted risk and it is invisible
    from anywhere else.

Stdlib only (the `fieldguard_planning` default — this module is NOT part of the numpy-scoped NDVI
slice), so it imports on a bare interpreter and can be called from a node, a test, or a bench script.

ABSENCE SEMANTICS, same rule as `read_fuser_stats` and the recorder counters: a field that could not
be read is `None` with its reason recorded in `unreadable`, **never** a fabricated 0. A
`shm_segments.min_bytes` of 0 would read as "a participant has no segment", which is a different and
much more alarming claim than "this process could not list /dev/shm".
"""
from __future__ import annotations

import glob
import os
from typing import Optional, Tuple

# Where Fast DDS puts its shared-memory files. Segment files are named `fastrtps_<hex>`; the PORT
# queues are `fastrtps_port<n>` and are a FIXED 52,416 B regardless of segment_size -- including them
# would peg min_bytes at 52,416 forever and destroy the partial-injection check, which is the whole
# point of tracking the minimum.
SHM_DIR = "/dev/shm"
SEGMENT_GLOB = os.path.join(SHM_DIR, "fastrtps_*")
PORT_PREFIX = "fastrtps_port"
# Fast DDS also creates a ZERO-BYTE `<name>_el` companion beside every segment and every port queue
# (measured live 2026-08-22: `fastrtps_23d604b34d071ce1` 549,408 B next to
# `fastrtps_23d604b34d071ce1_el` 0 B). Counting those pins min_bytes at 0 forever, which silently
# destroys the partial-injection check -- the first bench arm reported min=0/max=549,408 and the
# minimum was meaningless. Excluded by suffix.
EVENT_SUFFIX = "_el"

# ROS 2 Humble's default when RMW_IMPLEMENTATION is unset. Recorded as a resolved VALUE with its
# source, so a reader never has to know the default to interpret the field.
DEFAULT_RMW = "rmw_fastrtps_cpp"

# The two kernel socket limits, recorded as a CLOSED line of inquiry rather than a lever: /proc/sys
# is read-only in this container and `docker run --sysctl net.core.rmem_max=...` is rejected by runc
# on this Docker Desktop kernel. They are captured so the next reader can see they were checked and
# does not spend a session rediscovering that.
RMEM_MAX_PATH = "/proc/sys/net/core/rmem_max"
WMEM_MAX_PATH = "/proc/sys/net/core/wmem_max"


def _read_int_file(path: str) -> Tuple[Optional[int], Optional[str]]:
    try:
        with open(path) as fh:
            return int(fh.read().strip()), None
    except Exception as exc:  # noqa: BLE001 -- any failure is "unreadable", and it must not raise
        return None, f"{type(exc).__name__}: {exc}"


def _shm_segment_sizes() -> Tuple[list, Optional[str]]:
    """Sizes of the Fast DDS SHM SEGMENT files (port queues excluded -- see PORT_PREFIX)."""
    try:
        sizes = []
        for path in glob.glob(SEGMENT_GLOB):
            name = os.path.basename(path)
            if name.startswith(PORT_PREFIX) or name.endswith(EVENT_SUFFIX):
                continue
            try:
                sizes.append(os.path.getsize(path))
            except OSError:
                continue  # a segment torn down between glob and stat is not an error
        return sorted(sizes), None
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def dds_env_snapshot() -> dict:
    """What transport stack is this process actually running on? Cheap (a glob + two small reads),
    side-effect free, and safe to call from a node constructor."""
    unreadable = {}

    rmw = os.environ.get("RMW_IMPLEMENTATION")
    rmw_source = "env" if rmw else "default"
    rmw = rmw or DEFAULT_RMW

    profiles_file = os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE")
    if profiles_file:
        try:
            profiles_file_present = os.path.isfile(profiles_file)
        except Exception as exc:  # noqa: BLE001
            profiles_file_present = None
            unreadable["profiles_file_present"] = f"{type(exc).__name__}: {exc}"
    else:
        # Not set is a MEASUREMENT (the baseline arm), not a failure -- so False, not None.
        profiles_file, profiles_file_present = None, False

    try:
        st = os.statvfs(SHM_DIR)
        shm_capacity_bytes = int(st.f_blocks * st.f_frsize)
        shm_free_bytes = int(st.f_bavail * st.f_frsize)
    except Exception as exc:  # noqa: BLE001
        shm_capacity_bytes = shm_free_bytes = None
        unreadable["shm_capacity_bytes"] = unreadable["shm_free_bytes"] = \
            f"{type(exc).__name__}: {exc}"

    sizes, seg_err = _shm_segment_sizes()
    if seg_err:
        unreadable["shm_segments"] = seg_err
    segments = {
        "count": len(sizes),
        # None, not 0, for an empty set: "no participant has a segment" and "we could not look" must
        # not both read as zero bytes.
        "min_bytes": (sizes[0] if sizes else None),
        "max_bytes": (sizes[-1] if sizes else None),
    }

    rmem_max, err = _read_int_file(RMEM_MAX_PATH)
    if err:
        unreadable["rmem_max"] = err
    wmem_max, err = _read_int_file(WMEM_MAX_PATH)
    if err:
        unreadable["wmem_max"] = err

    return {
        "rmw": rmw,
        "rmw_source": rmw_source,
        "profiles_file": profiles_file,
        "profiles_file_present": profiles_file_present,
        "shm_capacity_bytes": shm_capacity_bytes,
        "shm_free_bytes": shm_free_bytes,
        "shm_segments": segments,
        "rmem_max": rmem_max,
        "wmem_max": wmem_max,
        "unreadable": unreadable,
        "note": ("shm_segments EXCLUDES fastrtps_port* (fixed 52,416 B port queues). max_bytes "
                 "proves a profile loaded (default segment file is 549,408 B); min_bytes proves no "
                 "participant missed it. Socket buffers are recorded, not tunable: /proc/sys is "
                 "read-only here and --sysctl is rejected by runc on this kernel."),
    }
