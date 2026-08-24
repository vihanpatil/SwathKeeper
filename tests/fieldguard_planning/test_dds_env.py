"""Tests for dds_env.py — the transport-stack snapshot that makes a lever flight attributable.

What these pin is not arithmetic, it is HONESTY under partial information. The round-3 lever (a Fast
DDS XML profile enlarging the SHM segment) has two silent failure modes, and this module is the only
thing that can see either:

  * the profile did not load at all — malformed XML falls back to defaults with only a log line, so
    `max_bytes` staying at the 549,408 B default is the tell;
  * the profile loaded for SOME participants — `bash -c` never sources .bashrc and there are three
    separate docker-exec sites, so a missed one leaves a default-sized segment in a
    container-global set, and only `min_bytes` sees it.

Both tells are destroyed by two easy mistakes, so both are tested: counting the fixed-size
`fastrtps_port*` queue files as segments, and reporting an empty/unreadable set as 0 bytes.

Stdlib only — dds_env.py is not part of the numpy-scoped NDVI slice, so this runs on a bare
interpreter like most of tests/fieldguard_planning.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning import dds_env  # noqa: E402
from fieldguard_planning.dds_env import DEFAULT_RMW, dds_env_snapshot  # noqa: E402

# The two numbers the whole admissibility check rests on (Fast DDS 2.6.11, measured in-container).
DEFAULT_SEGMENT_BYTES = 549_408      # 512 KiB + ~25 KB segment header
TUNED_SEGMENT_BYTES = 8_413_088      # 8 MiB + the same header
PORT_QUEUE_BYTES = 52_416            # fixed, regardless of segment_size


class _ShmSandbox:
    """Point dds_env at a temp dir standing in for /dev/shm, and control the env it reads."""

    def __init__(self, segments=(), ports=(), env=None, event_files=True):
        self.segments, self.ports, self.env = segments, ports, env or {}
        self.event_files = event_files

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        for i, size in enumerate(self.segments):
            (d / f"fastrtps_{i:016x}").write_bytes(b"\0" * size)
            if self.event_files:   # Fast DDS's real zero-byte companion, measured live
                (d / f"fastrtps_{i:016x}_el").write_bytes(b"")
        for i, size in enumerate(self.ports):
            (d / f"fastrtps_port{7411 + i}").write_bytes(b"\0" * size)
            if self.event_files:
                (d / f"fastrtps_port{7411 + i}_el").write_bytes(b"")
            (d / f"sem.fastrtps_port{7411 + i}_mutex").write_bytes(b"\0" * 32)
        self._saved = (dds_env.SHM_DIR, dds_env.SEGMENT_GLOB)
        dds_env.SHM_DIR = str(d)
        dds_env.SEGMENT_GLOB = os.path.join(str(d), "fastrtps_*")
        self._env_saved = {k: os.environ.get(k) for k in
                           ("RMW_IMPLEMENTATION", "FASTRTPS_DEFAULT_PROFILES_FILE")}
        for k in self._env_saved:
            os.environ.pop(k, None)
        os.environ.update(self.env)
        return d

    def __exit__(self, *exc):
        dds_env.SHM_DIR, dds_env.SEGMENT_GLOB = self._saved
        for k, v in self._env_saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()
        return False


class TestSegmentAccounting(unittest.TestCase):
    def test_port_queue_files_are_not_counted_as_segments(self):
        """THE trap. Port queues are a fixed 52,416 B whatever segment_size is, so counting them
        pins min_bytes at 52,416 forever and the partial-injection check silently dies."""
        with _ShmSandbox(segments=[TUNED_SEGMENT_BYTES, TUNED_SEGMENT_BYTES],
                         ports=[PORT_QUEUE_BYTES] * 5):
            seg = dds_env_snapshot()["shm_segments"]
        self.assertEqual(seg["count"], 2)
        self.assertEqual(seg["min_bytes"], TUNED_SEGMENT_BYTES)
        self.assertEqual(seg["max_bytes"], TUNED_SEGMENT_BYTES)

    def test_zero_byte_event_companions_are_not_counted_as_segments(self):
        """THE OTHER trap, and this one shipped: Fast DDS drops a zero-byte `<name>_el` beside every
        segment AND every port queue. Counting them pins min_bytes at 0 forever -- the very first
        live bench arm reported min=0 / max=549,408, i.e. an admissibility check that could never
        fail. Measured names, not guessed: fastrtps_23d604b34d071ce1 (549,408 B) alongside
        fastrtps_23d604b34d071ce1_el (0 B)."""
        with _ShmSandbox(segments=[DEFAULT_SEGMENT_BYTES, DEFAULT_SEGMENT_BYTES],
                         ports=[PORT_QUEUE_BYTES], event_files=True):
            seg = dds_env_snapshot()["shm_segments"]
        self.assertEqual(seg["count"], 2)
        self.assertEqual(seg["min_bytes"], DEFAULT_SEGMENT_BYTES)
        self.assertNotEqual(seg["min_bytes"], 0)

    def test_a_single_participant_that_missed_the_profile_is_visible_in_min_bytes(self):
        """Partial injection: max_bytes says 'the profile loaded', min_bytes says 'but not for
        everyone'. Reading only the max is how this ships green and measures the wrong stack."""
        with _ShmSandbox(segments=[TUNED_SEGMENT_BYTES, TUNED_SEGMENT_BYTES,
                                   DEFAULT_SEGMENT_BYTES]):
            seg = dds_env_snapshot()["shm_segments"]
        self.assertEqual(seg["max_bytes"], TUNED_SEGMENT_BYTES)   # looks tuned
        self.assertEqual(seg["min_bytes"], DEFAULT_SEGMENT_BYTES)  # ...but is not
        self.assertEqual(seg["count"], 3)

    def test_a_fully_baseline_stack_reads_default_on_both_ends(self):
        with _ShmSandbox(segments=[DEFAULT_SEGMENT_BYTES] * 4):
            seg = dds_env_snapshot()["shm_segments"]
        self.assertEqual((seg["min_bytes"], seg["max_bytes"]),
                         (DEFAULT_SEGMENT_BYTES, DEFAULT_SEGMENT_BYTES))

    def test_no_segments_reports_none_not_zero(self):
        """'no participant has a segment' and '0 bytes' are different claims; only one is true."""
        with _ShmSandbox(segments=[], ports=[PORT_QUEUE_BYTES]):
            seg = dds_env_snapshot()["shm_segments"]
        self.assertEqual(seg["count"], 0)
        self.assertIsNone(seg["min_bytes"])
        self.assertIsNone(seg["max_bytes"])


class TestAbsenceSemantics(unittest.TestCase):
    def test_an_unreadable_shm_dir_yields_nulls_with_reasons_never_zeros(self):
        with _ShmSandbox() as d:
            dds_env.SHM_DIR = str(Path(d) / "does_not_exist")
            snap = dds_env_snapshot()
        self.assertIsNone(snap["shm_capacity_bytes"])
        self.assertIsNone(snap["shm_free_bytes"])
        self.assertIn("shm_capacity_bytes", snap["unreadable"])
        self.assertIn("FileNotFoundError", snap["unreadable"]["shm_capacity_bytes"])

    def test_unreadable_socket_limits_are_null_with_a_reason(self):
        """Recorded, not tuned: /proc/sys is read-only in the container and --sysctl is rejected by
        runc on this kernel. On a macOS host the files do not exist at all -- which must read as
        'could not look', not as 'the buffers are 0'."""
        with _ShmSandbox():
            dds_env.RMEM_MAX_PATH = "/nonexistent/rmem_max"
            dds_env.WMEM_MAX_PATH = "/nonexistent/wmem_max"
            try:
                snap = dds_env_snapshot()
            finally:
                dds_env.RMEM_MAX_PATH = "/proc/sys/net/core/rmem_max"
                dds_env.WMEM_MAX_PATH = "/proc/sys/net/core/wmem_max"
        self.assertIsNone(snap["rmem_max"])
        self.assertIsNone(snap["wmem_max"])
        self.assertIn("rmem_max", snap["unreadable"])

    def test_a_healthy_snapshot_reports_no_unreadable_fields(self):
        with _ShmSandbox(segments=[DEFAULT_SEGMENT_BYTES]) as d:
            dds_env.RMEM_MAX_PATH = str(Path(d) / "rmem")
            dds_env.WMEM_MAX_PATH = str(Path(d) / "wmem")
            Path(dds_env.RMEM_MAX_PATH).write_text("212992\n")
            Path(dds_env.WMEM_MAX_PATH).write_text("212992\n")
            try:
                snap = dds_env_snapshot()
            finally:
                dds_env.RMEM_MAX_PATH = "/proc/sys/net/core/rmem_max"
                dds_env.WMEM_MAX_PATH = "/proc/sys/net/core/wmem_max"
        self.assertEqual(snap["unreadable"], {})
        self.assertEqual(snap["rmem_max"], 212992)
        self.assertIsNotNone(snap["shm_capacity_bytes"])


class TestRmwAndProfile(unittest.TestCase):
    def test_unset_rmw_resolves_to_the_humble_default_and_says_so(self):
        with _ShmSandbox():
            snap = dds_env_snapshot()
        self.assertEqual(snap["rmw"], DEFAULT_RMW)
        self.assertEqual(snap["rmw_source"], "default")

    def test_an_explicit_rmw_is_reported_as_env(self):
        with _ShmSandbox(env={"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}):
            snap = dds_env_snapshot()
        self.assertEqual((snap["rmw"], snap["rmw_source"]), ("rmw_cyclonedds_cpp", "env"))

    def test_no_profile_is_a_measurement_not_an_absence(self):
        """The baseline arm legitimately has no profile; that is False, not None -- reserving None
        for 'we could not tell'."""
        with _ShmSandbox():
            snap = dds_env_snapshot()
        self.assertIsNone(snap["profiles_file"])
        self.assertIs(snap["profiles_file_present"], False)

    def test_a_profile_path_that_does_not_exist_is_reported_present_false(self):
        """The exact shape of 'the flag was set but the file is missing' — which fails over to
        defaults silently inside Fast DDS."""
        with _ShmSandbox(env={"FASTRTPS_DEFAULT_PROFILES_FILE": "/workspace/nope.xml"}):
            snap = dds_env_snapshot()
        self.assertEqual(snap["profiles_file"], "/workspace/nope.xml")
        self.assertIs(snap["profiles_file_present"], False)

    def test_an_existing_profile_path_is_reported_present_true(self):
        with tempfile.NamedTemporaryFile(suffix=".xml") as fh:
            with _ShmSandbox(env={"FASTRTPS_DEFAULT_PROFILES_FILE": fh.name}):
                snap = dds_env_snapshot()
        self.assertIs(snap["profiles_file_present"], True)


class TestSerialisation(unittest.TestCase):
    def test_snapshot_is_json_serialisable_with_plain_types(self):
        """It lands in meta.json; a non-JSON type here fails the write that closes the clip."""
        with _ShmSandbox(segments=[DEFAULT_SEGMENT_BYTES], ports=[PORT_QUEUE_BYTES]):
            snap = dds_env_snapshot()
        round_tripped = json.loads(json.dumps(snap))
        self.assertEqual(round_tripped["shm_segments"]["count"], 1)
        for k in ("shm_capacity_bytes", "rmem_max"):
            self.assertIn(type(snap[k]), (int, type(None)), msg=f"{k} is {type(snap[k])}")

    def test_snapshot_never_raises_even_with_everything_broken(self):
        """It is called from a node constructor. Instrumentation must never take a flight down."""
        with _ShmSandbox():
            dds_env.SHM_DIR = "/nonexistent"
            dds_env.SEGMENT_GLOB = "/nonexistent/fastrtps_*"
            dds_env.RMEM_MAX_PATH = "/nonexistent/a"
            dds_env.WMEM_MAX_PATH = "/nonexistent/b"
            try:
                snap = dds_env_snapshot()
            finally:
                dds_env.RMEM_MAX_PATH = "/proc/sys/net/core/rmem_max"
                dds_env.WMEM_MAX_PATH = "/proc/sys/net/core/wmem_max"
        self.assertEqual(snap["shm_segments"]["count"], 0)
        json.dumps(snap)


if __name__ == "__main__":
    unittest.main()
