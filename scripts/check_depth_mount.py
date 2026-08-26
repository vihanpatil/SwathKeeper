#!/usr/bin/env python3
"""HOST-side geometry gate for the ADR-019 forward depth mount. ~50 ms, no container, no render.

WHY IT EXISTS, and why it exists BEFORE the sensor has ever been rendered. The ADR-007 nadir mount
was authored under a pinhole Z-forward mental model, so it faced the HORIZON, upside down, from the
day it was written -- and all four of its gates passed anyway, for two weeks and five recorded
flights, because every gate measured VALUES (band separation, topic rates) and none measured
GEOMETRY (ADR-007 amendment 5). Gazebo camera sensors look along the SENSOR FRAME's +X. The
"obvious" ROS answer for a forward camera, rpy (-pi/2, 0, -pi/2), aims this one out of the right
flank; this script is what makes that impossible to ship.

WHAT IT PROVES (all of it from the COMMITTED artifacts, so it is a real gate and not a restatement
of the config):
  A. The generated SDF actually carries the depth link, joint, sensor type and topic, and carries
     NO <camera_info_topic> element -- which for `depth_camera` would be silently ignored by
     gz-sensors and is therefore dead config that looks live.
  B. The SDF's mount pose is the one config/depth_camera.json declares, and the importable mirror
     in `depth_detect` is the same pose again. Three copies, pinned equal.
  C. The optical axis derived FROM THE SDF's rpy is body +X (forward) to 1e-9, and the image axes
     are u+ = body -Y (right), v+ = body -Z (down).
  D. THE CROSS-CHECK THAT MAKES C TRUSTWORTHY: the same general rpy -> optical-axis function, fed
     the NADIR mount's rpy READ OUT OF THE SAME SDF, must reproduce `ndvi_georef`'s
     CAMERA_TO_BODY_SIGNS -- the extrinsic that was verified in the real render to 2.2 px against a
     15 px bar. If the formula is wrong, this check fails on known-good geometry.
  E. A bird can be both IN FRAME and RESOLVABLE at the same time: the +/-`vertical_threat_m` band
     is covered from a range NEARER than the acquisition range.
  F. The bridge yaml bridges the depth image and the DERIVED camera_info name.

WHAT IT CANNOT PROVE, and what therefore still owes the live gates D1-D6 (docs/runbooks/
FORWARD_DEPTH_SENSOR.md): that gz agrees with this arithmetic in the actual render, that the
airframe does not occlude the aperture, that the derived info topic really is /fg/depth/camera_info,
and what the real acquisition range is once anti-aliasing and depth quantisation have had their say.
Static geometry checks are necessary and never sufficient -- that is the whole ADR-007 am. 5 lesson.

Run:  python3 scripts/check_depth_mount.py            (exit 0 = PASS, 1 = FAIL)
Dependency: stdlib only.
"""
from __future__ import annotations

import inspect
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_policy import PolicyParams          # noqa: E402
from fieldguard_planning.depth_detect import (                          # noqa: E402
    DEPTH_OPTICAL_TO_BODY, FORWARD_MOUNT_OFFSET_BODY_M, FORWARD_MOUNT_RPY_RAD,
    DepthDetectionSource, acquisition_range_m, band_covered_from_m, mat_vec, optical_axis_body,
    optical_to_body_matrix,
)
from fieldguard_planning.ndvi_georef import CAMERA_TO_BODY_SIGNS        # noqa: E402

WORLD = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"
DEPTH_CONFIG = REPO_ROOT / "config" / "depth_camera.json"
NDVI_CONFIG = REPO_ROOT / "config" / "ndvi_camera.json"
BIRDS_CONFIG = REPO_ROOT / "config" / "birds" / "farm_world_birds.json"
BRIDGE_YAML = REPO_ROOT / "sim" / "bridge" / "fg_sensor_bridge.yaml"

TOL = 1e-9
VEHICLE_MODEL = "iris_with_gimbal_ndvi"


def _link(world_root: ET.Element, link_name: str) -> ET.Element:
    model = next(m for m in world_root.find("world").findall("model")
                 if m.get("name") == VEHICLE_MODEL)
    return next(l for l in model.findall("link") if l.get("name") == link_name)


def _pose(link: ET.Element) -> Tuple[float, ...]:
    return tuple(float(v) for v in link.find("pose").text.split())


def _bridge_entries(text: str) -> List[dict]:
    """The bridge yaml as a list of dicts, parsed STRUCTURALLY rather than grepped.

    A substring check ("is this topic name in the file?") passes on a commented-out entry, on a
    topic named only in the header prose, and on an entry whose ros/gz names disagree -- all three
    of which would leave the bridge advertising silence. Twelve lines of parser beat that, and
    stdlib-only keeps this gate runnable on a bare interpreter like every other host tool here
    (the file is a flat list of `key: value` mappings; PyYAML would be a dependency for nothing)."""
    entries: List[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- "):
            entries.append({})
            line = line.lstrip()[2:]
        elif not entries:
            continue
        if ":" not in line:
            continue
        key, _, value = line.strip().partition(":")
        entries[-1][key.strip()] = value.strip().strip('"').strip("'")
    return entries


def _derived_info_topic(topic: str) -> str:
    """gz-sensors8 CameraSensor::AdvertiseInfo when infoTopic is empty (src/CameraSensor.cc:662):
    split the topic on '/', DROP THE LAST SEGMENT, rejoin with leading slashes, append
    '/camera_info'. Reimplemented here (six lines) rather than assumed, because this is the exact
    step that decides whether the bridge entry is right."""
    parts = [p for p in topic.split("/")[:-1] if p]
    return "".join("/" + p for p in parts) + "/camera_info"


def check() -> Tuple[bool, List[str]]:
    """Returns (ok, report lines). Every line starts PASS/FAIL so the output greps cleanly."""
    out: List[str] = []
    ok = True

    def rec(good: bool, msg: str) -> None:
        nonlocal ok
        ok = ok and good
        out.append(f"  {'PASS' if good else 'FAIL'}  {msg}")

    cfg = json.loads(DEPTH_CONFIG.read_text())
    mount, cam = cfg["mount"], cfg["camera"]
    root = ET.parse(WORLD).getroot()

    # ---- A. the SDF really carries the sensor, and carries no dead camera_info_topic ------------
    link = _link(root, mount["mount_link_name"])
    sensor = next(s for s in link.findall("sensor") if s.get("name") == "fg_depth_camera")
    rec(sensor.get("type") == cfg["depth"]["gz_sensor_type"],
        f"SDF sensor type is {cfg['depth']['gz_sensor_type']!r} (got {sensor.get('type')!r})")
    sdf_topic = sensor.find("topic").text.strip()
    want_topic = cam["topics"]["depth_image"].lstrip("/")
    rec(sdf_topic == want_topic, f"SDF <topic> is {want_topic!r} (got {sdf_topic!r})")
    rec(sensor.find("camera/camera_info_topic") is None,
        "SDF emits NO <camera_info_topic> (DepthCameraSensor::Load ignores it -- it would be dead "
        "config that looks live)")
    derived = _derived_info_topic("/" + sdf_topic)
    rec(derived == cam["topics"]["depth_camera_info"],
        f"gz will DERIVE the info topic as {derived} (config declares "
        f"{cam['topics']['depth_camera_info']})")
    joint = next(j for j in next(m for m in root.find("world").findall("model")
                                 if m.get("name") == VEHICLE_MODEL).findall("joint")
                 if j.get("name") == mount["mount_joint_name"])
    rec(joint.get("type") == "fixed"
        and joint.find("parent").text.strip() == mount["parent_link_scoped_from_wrapper"]
        and joint.find("child").text.strip() == mount["mount_link_name"],
        f"fixed joint {mount['mount_joint_name']} attaches {mount['mount_link_name']} to "
        f"{mount['parent_link_scoped_from_wrapper']}")
    rec(link.find("visual") is None and link.find("collision") is None,
        "depth mount link carries sensors only (no visual/collision -- it cannot occlude a camera)")

    # ---- B. SDF pose == config pose == the importable mirror in depth_detect --------------------
    sdf_pose = _pose(link)
    cfg_pose = tuple(float(v) for v in mount["mount_pose_xyz_rpy"])
    rec(len(sdf_pose) == 6 and all(abs(a - b) < TOL for a, b in zip(sdf_pose, cfg_pose)),
        f"SDF mount pose {sdf_pose} == config mount_pose_xyz_rpy {cfg_pose}")
    mirror = tuple(FORWARD_MOUNT_OFFSET_BODY_M) + tuple(FORWARD_MOUNT_RPY_RAD)
    rec(all(abs(a - b) < TOL for a, b in zip(mirror, cfg_pose)),
        f"depth_detect mirror {mirror} == config pose (the transform must not drift from the world)")
    sig = inspect.signature(DepthDetectionSource.__init__).parameters
    rec(sig["min_range_m"].default == cam["clip_near_m"]
        and sig["max_range_m"].default == cam["clip_far_m"],
        f"DepthDetectionSource's default range window ({sig['min_range_m'].default}, "
        f"{sig['max_range_m'].default}) m == the SDF clip planes ({cam['clip_near_m']}, "
        f"{cam['clip_far_m']}) m -- gz writes +/-inf outside them, so a wider window would accept "
        f"a value the renderer never measured")

    # ---- C. the aim, derived from the SDF, not from the mirror ----------------------------------
    m_sdf = optical_to_body_matrix(*sdf_pose[3:])
    axis = optical_axis_body(m_sdf)
    rec(all(abs(a - b) < TOL for a, b in zip(axis, (1.0, 0.0, 0.0))),
        f"optical axis from the SDF rpy is body +X = FORWARD (got {tuple(round(a, 12) for a in axis)}"
        f"; the rejected pinhole-instinct rpy (-pi/2,0,-pi/2) would give (0,-1,0), the right flank)")
    u_axis = mat_vec(m_sdf, (1.0, 0.0, 0.0))
    v_axis = mat_vec(m_sdf, (0.0, 1.0, 0.0))
    rec(all(abs(a - b) < TOL for a, b in zip(u_axis, (0.0, -1.0, 0.0))),
        f"image u+ maps to body -Y = the vehicle's RIGHT (got {tuple(round(a, 12) for a in u_axis)})")
    rec(all(abs(a - b) < TOL for a, b in zip(v_axis, (0.0, 0.0, -1.0))),
        f"image v+ maps to body -Z = DOWN (got {tuple(round(a, 12) for a in v_axis)})")
    rec(all(abs(m_sdf[i][j] - DEPTH_OPTICAL_TO_BODY[i][j]) < TOL for i in range(3) for j in range(3)),
        "depth_detect.DEPTH_OPTICAL_TO_BODY equals the matrix derived from the SDF pose")

    # ---- D. the cross-check on LIVE-VERIFIED geometry -------------------------------------------
    ndvi_mount = json.loads(NDVI_CONFIG.read_text())["mount"]
    ndvi_link = _link(root, ndvi_mount["mount_link_name"])
    ndvi_rpy = _pose(ndvi_link)[3:]
    m_ndvi = optical_to_body_matrix(*ndvi_rpy)
    diag = tuple(m_ndvi[i][i] for i in range(3))
    off_diag_zero = all(abs(m_ndvi[i][j]) < TOL for i in range(3) for j in range(3) if i != j)
    rec(off_diag_zero and all(abs(a - b) < TOL for a, b in zip(diag, CAMERA_TO_BODY_SIGNS)),
        f"CROSS-CHECK: the same formula at the NADIR mount's SDF rpy "
        f"{tuple(round(a, 6) for a in ndvi_rpy)} reproduces ndvi_georef.CAMERA_TO_BODY_SIGNS "
        f"{CAMERA_TO_BODY_SIGNS} (got diag {tuple(round(a, 12) for a in diag)}) -- the extrinsic "
        f"verified in the real render to 2.2 px")
    ndvi_axis = optical_axis_body(m_ndvi)
    rec(all(abs(a - b) < TOL for a, b in zip(ndvi_axis, (0.0, 0.0, -1.0))),
        f"CROSS-CHECK: and it puts the nadir optical axis at body -Z = DOWN "
        f"(got {tuple(round(a, 12) for a in ndvi_axis)})")
    rec(tuple(FORWARD_MOUNT_OFFSET_BODY_M) != tuple(
            json.loads(NDVI_CONFIG.read_text())["mount"]["mount_pose_xyz_rpy"][:3]),
        "the two mounts are at DIFFERENT places on the airframe (a shared offset would mean one "
        "aperture was copied onto the other)")

    # ---- E. in-frame AND resolvable overlap -----------------------------------------------------
    fx = (cam["image_width_px"] / 2.0) / math.tan(cam["horizontal_fov_rad"] / 2.0)
    cy = cam["image_height_px"] / 2.0
    band_half = float(PolicyParams().vertical_threat_m)
    r_bird = max(b["physical_radius_m"] for b in json.loads(BIRDS_CONFIG.read_text())["birds"])
    from_m = band_covered_from_m(fx, cy, band_half)     # fy == fx for this square-pixel model
    acq_m = acquisition_range_m(fx, r_bird)
    rec(from_m < acq_m,
        f"the +/-{band_half:g} m threat band is in frame from {from_m:.2f} m, and a {r_bird:g} m "
        f"bird still resolves out to {acq_m:.2f} m -- a {acq_m - from_m:.2f} m window where a "
        f"threat is both visible and detectable")
    # VALUES, not just ordering: an ordering-only assertion stays green while the band-coverage
    # range doubles, and this is the number the no-tilt decision rests on.
    rec(abs(from_m - 13.00) <= 0.05 and abs(acq_m - 46.80) <= 0.05,
        f"and they are the PUBLISHED values -- band from {from_m:.2f} m (13.00 expected), "
        f"acquisition {acq_m:.2f} m (46.80 expected). Moving either re-opens ADR-020's geometry "
        f"argument and the booking-gate margin")
    # The far cull is on EUCLIDEAN slant range while the stored value is Z-depth, so the effective
    # Z horizon at the frame CORNER is far/|ray|, not far. Comparing against the on-axis 60 m
    # overstates the headroom by an order of magnitude (22 % against the true 1.6 %).
    corner_ray = math.sqrt(1.0 + (cam["image_width_px"] / 2.0 / fx) ** 2 + (cy / fx) ** 2)
    far_corner = cam["clip_far_m"] / corner_ray
    rec(acq_m <= far_corner,
        f"far clip {cam['clip_far_m']:g} m on-axis = {far_corner:.2f} m of Z-depth at the FRAME "
        f"CORNER (|ray| {corner_ray:.3f}x; the far cull is on Euclidean slant range, the stored "
        f"value is Z-depth), which still clears the {acq_m:.2f} m resolution limit -- by "
        f"{100.0 * (far_corner - acq_m) / acq_m:.1f} %, NOT the "
        f"{100.0 * (cam['clip_far_m'] - acq_m) / acq_m:.0f} % the on-axis number suggests")

    # ---- F. the bridge carries both topics ------------------------------------------------------
    entries = _bridge_entries(BRIDGE_YAML.read_text())
    by_topic = {e.get("ros_topic_name"): e for e in entries}
    for topic, ros_type, gz_type in (
            (cam["topics"]["depth_image"], "sensor_msgs/msg/Image", "gz.msgs.Image"),
            (cam["topics"]["depth_camera_info"], "sensor_msgs/msg/CameraInfo",
             "gz.msgs.CameraInfo")):
        e = by_topic.get(topic)
        rec(e is not None and e.get("gz_topic_name") == topic
            and e.get("ros_type_name") == ros_type and e.get("gz_type_name") == gz_type
            and e.get("direction") == "GZ_TO_ROS",
            f"{topic} is bridged GZ_TO_ROS as {ros_type}/{gz_type} in "
            f"{BRIDGE_YAML.relative_to(REPO_ROOT)} (parsed entry: {e})")
    rec(not any("/points" in (e.get("ros_topic_name") or "") for e in entries),
        "the depth point cloud is NOT bridged (gz only builds it when subscribed -- leaving it "
        "unbridged costs nothing and saves a per-frame XYZRGB pass)")
    # ADR-007 state, guarded from this side too: the four nadir topics must survive every edit to
    # this file, and ADR-019 item 7 freezes them.
    rec(sum(1 for t in by_topic if (t or "").startswith("/fg/sensor/")) == 4,
        f"the four ADR-007 /fg/sensor/* entries are untouched "
        f"(found {sorted(t for t in by_topic if (t or '').startswith('/fg/sensor/'))})")

    return ok, out


def main(argv: Optional[List[str]] = None) -> int:
    ok, lines = check()
    print("SwathKeeper forward depth mount -- static geometry gate (ADR-019)")
    print("\n".join(lines))
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} -- {len(lines)} checks, "
          f"{sum(1 for l in lines if l.strip().startswith('FAIL'))} failed."
          + ("" if ok else "  Do NOT render or fly this mount until they are green."))
    print("  NOTE: static geometry only. The render still owes docs/runbooks/"
          "FORWARD_DEPTH_SENSOR.md gates D1-D6 -- ADR-007 am. 5 happened under four green "
          "value-only gates.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
