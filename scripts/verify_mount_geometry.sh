#!/usr/bin/env bash
# The GEOMETRIC gate for the ADR-007 sensor mount — run inside the fieldguard-sim container.
#
# Born 2026-08-18: the mount was aimed at the horizon (upside-down) from the day it was authored,
# because Gazebo cameras look along sensor +X while the mount rpy was derived under a pinhole
# Z-forward mental model — and EVERY gate passed anyway, because every gate measured VALUES
# (band separation, topic rates), never geometry. Five recorded flights were lost to it.
#
# This script is the gate that was missing: it launches a physics-free copy of the farm world
# (physics plugin stripped — a NESTED-include vehicle does NOT inherit <static> from its wrapper
# and free-falls otherwise, which cost this project several hours of self-contradictory probes),
# parks the vehicle 1 m north of tree_row1_1 at 10 m, captures one RGB frame, and asserts the
# canopy blob centroid lands within TOL px of the pixel `ndvi_georef.world_enu_to_pixel` predicts
# — the SAME transform the heatmap stitch and the GT labeler use. Passing means aim, image
# orientation, and the georef extrinsic all agree, end to end.
#
# Run after ANY change to: config/ndvi_camera.json (mount block), gen_farm_world's vehicle/sensor
# SDF, or ndvi_georef's extrinsic constants:
#
#   bash /workspace/fieldguard/scripts/verify_mount_geometry.sh
#
# Exit 0 = geometry verified; nonzero = investigate before trusting ANY recorded imagery.
# source BEFORE `set -u`: colcon's setup.bash trips on unbound COLCON_TRACE under -u
# (the same class as docs/runbooks/SIM_BRINGUP.md bringup bug #2).
source /root/ardu_ws/install/setup.bash
set -euo pipefail

REPO=/workspace/fieldguard
TOL_PX=15
export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share"

sed -e 's/<world name="farmguard_field">/<world name="mountcheck">/' \
    -e 's|fg/sensor|mountcheck/sensor|g' \
    -e '/gz-sim-physics-system/d' \
    -e 's|<pose degrees="true">0 0 0.195 0 0 90</pose>|<pose degrees="true">40 16 10 0 0 90</pose>|' \
    "$REPO/sim/worlds/farmguard_field.sdf" > /tmp/mountcheck.sdf

gz sim -v1 -s -r --headless-rendering /tmp/mountcheck.sdf > /tmp/mountcheck.log 2>&1 &
GZ_PID=$!
trap 'kill $GZ_PID 2>/dev/null || true' EXIT

N=0
until gz topic -l 2>/dev/null | grep -q "mountcheck/sensor/rgb/image"; do
  sleep 1; N=$((N+1))
  if [ $N -gt 30 ]; then echo "[verify_mount_geometry] FAIL: camera topic never appeared"; exit 2; fi
done
sleep 5
timeout 15 gz topic -e -t /mountcheck/sensor/rgb/image -n 1 --json-output > /tmp/mountcheck_frame.json

python3 - "$TOL_PX" <<'PYEOF'
import base64, json, math, sys
sys.path.insert(0, "/workspace/fieldguard/src")
import numpy as np
from fieldguard_planning.ndvi_georef import CameraIntrinsics, world_enu_to_pixel

tol = float(sys.argv[1])
arr = np.frombuffer(base64.b64decode(json.load(open("/tmp/mountcheck_frame.json"))["data"]),
                    dtype=np.uint8).reshape(480, 640, 3)
r, g = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int)
canopy = (g - r > 30) & (g < 170)
if canopy.sum() < 5000:
    print(f"[verify_mount_geometry] FAIL: canopy blob absent/tiny ({canopy.sum()} px) -- "
          f"camera not nadir over the tree, or trees not rendering")
    raise SystemExit(1)
vs, us = np.nonzero(canopy)
cu, cv = us.mean(), vs.mean()
q = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))  # vehicle yaw 90 (nose north)
intr = CameraIntrinsics(width_px=640, height_px=480, fx=520.0057, fy=520.0057, cx=320.0, cy=240.0)
pu, pv = world_enu_to_pixel((40.0, 15.0, 3.0), (40.0, 16.0, 10.0), q, intr, (0.0, 0.0, -0.08))
err = math.hypot(pu - cu, pv - cv)
verdict = "PASS" if err <= tol else "FAIL"
print(f"[verify_mount_geometry] {verdict}: canopy centroid ({cu:.0f},{cv:.0f}) vs "
      f"georef-predicted ({pu:.0f},{pv:.0f}) -- error {err:.1f}px (tol {tol:.0f})")
raise SystemExit(0 if err <= tol else 1)
PYEOF
