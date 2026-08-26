#!/usr/bin/env bash
# The IN-RENDER gate for the ADR-019 forward depth mount — run inside the fieldguard-sim container.
# One Gazebo launch, four measurements: D2 (mount geometry), D2-OFFAXIS (Z-depth is not slant
# range), D2-CULL (the near/far refusal, in literal pixel values) and D3 (the acquisition range the
# booking gate refuses to run without).
#
# Sibling of scripts/verify_mount_geometry.sh, deliberately NOT folded into it: that script is the
# live-verified ADR-007 gate (2.2 px against a 15 px bar) and ADR-019 forbids re-opening closed NDVI
# state to save one Gazebo launch. It costs a second rendering Gazebo on a machine the runbooks tell
# you to keep quiet — so run this ALONE, before a bringup, never during a recording flight.
#
# WHY IT EXISTS. Gazebo cameras look along the sensor frame's +X. The nadir mount was authored under
# a pinhole Z-forward model and faced the HORIZON, upside down, for two weeks and five recorded
# flights while all four of its gates stayed green — every gate measured VALUES, none measured
# GEOMETRY (ADR-007 amendment 5). `scripts/check_depth_mount.py` proves the ARITHMETIC on the host
# in 50 ms; this proves GAZEBO AGREES WITH IT, which is the half that actually failed last time.
#
# WHAT IT DOES. Launches a physics-free copy of the farm world (physics stripped — a NESTED-include
# vehicle does not inherit <static> from its wrapper and free-falls otherwise; that cost several
# hours in 2026-08-18), parks the vehicle at (60, 30, 15) nose-EAST — clear of both tree rows, with
# open sky along the optical axis — and teleports `bird_0` to known places.
#
#   D2  MOUNT GEOMETRY, from the 10 m on-axis capture:
#         AIM    the near-cluster centroid lands within TOL_PX of the principal point. A camera
#                aimed at the right flank (the rpy (-pi/2,0,-pi/2) trap) never sees the bird at all,
#                and a nadir one reads the ground: AIM and RANGE together catch every mis-aim.
#         RANGE  the nearest finite depth is the bird's near surface, 9.82 m, within TOL_M. A nadir
#                mount from this pose would read 15.00 m to the ground.
#         CLEAR  no finite depth pixel nearer than 1.0 m — i.e. the airframe does not occlude the
#                aperture. This is the one thing host-side math cannot settle.
#
#   D2-OFFAXIS  THE ON-AXIS CAPTURE CANNOT SEE THIS BUG. On the optical axis, Z-depth and slant
#         range are identical by construction, so a mount that reported slant range would pass D2
#         perfectly and then place every off-axis obstacle up to 1.17x too far at the frame edge
#         (1.26x at the corner — ~8 m of error at 46 m, straight through depth_pixel_to_enu). The
#         bird is teleported to Z-depth 20.0 m at pixel (560, 120): the reading must be the Z-depth
#         19.84 m, NOT the slant 22.33 m, and those are 2.49 m apart against a 0.20 m tolerance.
#         The same capture pins the image-axis signs in the render (u+ right, v+ down).
#
#   D2-CULL  REFUSAL, NOT CLAMP, MEASURED. gz writes -inf inside the near clip and +inf past the far
#         clip, and `DepthDetectionSource` refuses both rather than clamping them to a clip plane —
#         which would report a confident obstacle at exactly 60.0 m. Until now that rested on
#         reading gz-rendering source. Here it is read off literal pixels: the bird parked 0.25 m
#         ahead (near surface 0.07 m, inside the 0.1 m near clip) must print `-inf`, and the ground
#         beyond the far clip must print `inf`. The far cull is also shown to be on EUCLIDEAN slant
#         range while the stored value is Z-depth: the greatest finite Z-depth in the frame is
#         far/|ray| at its own pixel, not `far`.
#
#   D3  ACQUISITION RANGE — a BEST-CASE-SCENE RESOLVABILITY measurement, and it must be read as one.
#       The greatest range at which the bird still produces exactly one component through the
#       ADOPTED morphology (ndvi_detect.detect_blobs, min_area 6), with a BLIND mask (`isfinite`
#       and nothing else) that works only because the sky past the far clip is +inf and the ground
#       slab exceeds max_area. The scene is deliberately the friendliest one that exists: no
#       clutter, a static vehicle, a noiseless sensor, and a sky background. That discharges the
#       anti-aliasing unknown the host-side 46.80 m bound could not — and it remains an UPPER BOUND
#       on the mission horizon, where the bird crosses tree canopies and the ground band. The
#       aggregator takes the longest CONTIGUOUS PREFIX of detected ranges, not the maximum: one
#       lucky far hit after a miss is aliasing, and letting it set the number would promote the
#       booking gate to exit 0 on noise.
#       Feed the printed number to the booking gate:
#           python3 scripts/predict_forward_lead.py --speed <mission> --fx <K[0]> --cy <K[5]> \
#                   --acq-range-m <D3>
#       Host-side arithmetic predicts 46.80 m; THIS is the number ADR-019 item 6 means by "from the
#       sensor, never from config prose".
#
# Run after ANY change to config/depth_camera.json's mount block, the vehicle SDF, or depth_detect's
# extrinsic — and once before the dodge flight is booked:
#
#   bash /workspace/fieldguard/scripts/verify_depth_mount_geometry.sh
#
# Exit 0 = D2 + D2-OFFAXIS + D2-CULL verified (D3 is a measurement and never fails the gate on its
# own; a SHORT D3 is reported and then fails the BOOKING gate, which is the correct place for it to
# bite). Nonzero = do NOT trust any depth-derived detection from this mount.
#
# source BEFORE `set -u`: colcon's setup.bash trips on unbound COLCON_TRACE under -u
# (the same class as docs/runbooks/SIM_BRINGUP.md bringup bug #2).
source /root/ardu_ws/install/setup.bash
set -euo pipefail

REPO=/workspace/fieldguard
WORLD=depthcheck
TOPIC=/${WORLD}/depth/image
OUT=/tmp/depthcheck
TOL_PX=15
TOL_M=0.20
# Vehicle parked here; camera sits 0.15 m further east (the mount offset), nose-east so body +X is
# world +X. Ranges are Z-DEPTH from the camera.
PARK_E=60; PARK_N=30; PARK_U=15
CAM_E=60.15
D2_RANGE=10
# 5 m steps out to 40, then 2 m through the band where the pinhole bound (46.80 m) says the target
# stops resolving: the number the booking gate consumes deserves better than a 5 m quantum there.
SWEEP_RANGES="10 20 25 30 35 40 42 44 46 48 50 52 54"
# Off-axis probe: Z-depth 20 m at pixel (cx+240, cy-120). Right and UP so the background is sky and
# the blind mask still works; the down-and-right corner would sit in the ground band, which is the
# clutter-merging case the segmenter session owns (see the runbook's Known gaps).
OFFAXIS_Z=20.0; OFFAXIS_DU=240.0; OFFAXIS_DV=-120.0
NEAR_PROBE_M=0.25          # bird CENTRE 0.25 m ahead -> near surface 0.07 m, inside the 0.1 m clip

export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share"
rm -rf "$OUT"; mkdir -p "$OUT"

# `fg/` -> `depthcheck/` renames BOTH camera namespaces at once, so this world cannot collide with a
# live bringup on either the NDVI or the depth topics.
sed -e "s/<world name=\"farmguard_field\">/<world name=\"${WORLD}\">/" \
    -e "s|fg/sensor|${WORLD}/sensor|g" \
    -e "s|fg/depth|${WORLD}/depth|g" \
    -e '/gz-sim-physics-system/d' \
    -e "s|<pose degrees=\"true\">0 0 0.195 0 0 90</pose>|<pose degrees=\"true\">${PARK_E} ${PARK_N} ${PARK_U} 0 0 0</pose>|" \
    "$REPO/sim/worlds/farmguard_field.sdf" > "$OUT/world.sdf"

gz sim -v1 -s -r --headless-rendering "$OUT/world.sdf" > "$OUT/gz.log" 2>&1 &
GZ_PID=$!
trap 'kill $GZ_PID 2>/dev/null || true' EXIT

N=0
until gz topic -l 2>/dev/null | grep -q "${WORLD}/depth/image"; do
  sleep 1; N=$((N+1))
  if [ $N -gt 30 ]; then echo "[verify_depth_mount] FAIL: depth topic never appeared"; exit 2; fi
done

# The DERIVED info-topic name, printed as evidence rather than assumed. gz-sensors8 builds it by
# dropping the LAST SEGMENT of <topic> (CameraSensor::AdvertiseInfo), because DepthCameraSensor
# never calls CameraSensor::Load and so ignores <camera_info_topic> entirely. If it comes back as
# .../image/camera_info, sim/bridge/fg_sensor_bridge.yaml is bridging a topic that does not exist
# and the bridge will sit there advertising silence.
echo "[verify_depth_mount] advertised depth topics:"
gz topic -l | grep "^/${WORLD}/depth" | sed 's/^/    /'
if ! gz topic -l | grep -qx "/${WORLD}/depth/camera_info"; then
  echo "[verify_depth_mount] FAIL (D1): /${WORLD}/depth/camera_info is not advertised — gz derived a"
  echo "                     different name. Fix the bridge yaml to match what is printed above; do"
  echo "                     NOT add a <camera_info_topic> to the world (this sensor ignores it)."
  exit 3
fi
gz topic -e -t "/${WORLD}/depth/camera_info" -n 1 --json-output > "$OUT/camera_info.json" 2>/dev/null || true
echo "[verify_depth_mount] LIVE intrinsics (feed BOTH to the booking gate, K[0] and K[5]):"
python3 -c "
import json,sys
try:
    k=json.load(open('$OUT/camera_info.json'))
    print('    fx =', k.get('intrinsics',{}).get('k',[None])[0], ' cy =', k.get('intrinsics',{}).get('k',[None]*6)[5])
except Exception as exc:
    print('    (could not parse camera_info:', exc, '- read', '$OUT/camera_info.json', 'by hand)')
"

teleport() {  # $1 = east, $2 = north, $3 = up  (world metres)
  gz service -s "/world/${WORLD}/set_pose" --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
    --timeout 2000 --req "name: \"bird_0\", position: {x: $1, y: $2, z: $3}, orientation: {z: 0.0, w: 1.0}" \
    >/dev/null
}

capture() {  # $1 = label
  sleep 2
  echo "[verify_depth_mount] capturing $1 ..."
  timeout 30 gz topic -e -t "$TOPIC" -n 1 --json-output > "$OUT/frame_$1.json"
}

# DepthCameraSensor::Update returns early when NOTHING is subscribed (gz-sensors8), so each frame is
# produced BECAUSE of this subscription. The first sleep also lets ogre2 warm up on llvmpipe.
sleep 5

# --- the sweep (D3) + the 10 m on-axis capture (D2) ----------------------------------------------
for R in $SWEEP_RANGES; do
  E=$(python3 -c "print(f'{${CAM_E} + $R:.4f}')")
  teleport "$E" "${PARK_N}.0" "${PARK_U}.0"
  capture "$R"
done

# --- the off-axis capture (D2-OFFAXIS) ------------------------------------------------------------
# Placed from the LIVE intrinsics if they parsed, else from the config fx; the python pass recomputes
# the expectation from whatever fx it reads back, so a mismatch cannot silently pass.
read -r OA_E OA_N OA_U <<EOF
$(python3 -c "
import json,math
fx=(640/2)/math.tan(1.1033/2)
z=$OFFAXIS_Z; du=$OFFAXIS_DU; dv=$OFFAXIS_DV
print(f'{$CAM_E + z:.4f}', f'{$PARK_N - du/fx*z:.4f}', f'{$PARK_U - dv/fx*z:.4f}')
")
EOF
teleport "$OA_E" "$OA_N" "$OA_U"
capture "offaxis"

# --- the near-clip probe (D2-CULL) ----------------------------------------------------------------
teleport "$(python3 -c "print(f'{${CAM_E} + ${NEAR_PROBE_M}:.4f}')")" "${PARK_N}.0" "${PARK_U}.0"
capture "near"

python3 - "$OUT" "$D2_RANGE" "$TOL_PX" "$TOL_M" "$SWEEP_RANGES" "$OFFAXIS_Z" "$OFFAXIS_DU" \
         "$OFFAXIS_DV" "$NEAR_PROBE_M" <<'PYEOF'
import base64, json, math, sys
sys.path.insert(0, "/workspace/fieldguard/src")
import numpy as np
from fieldguard_planning.ndvi_detect import DEFAULT_MAX_AREA, DEFAULT_MIN_AREA, detect_blobs

out = sys.argv[1]
d2_range, tol_px, tol_m = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
ranges = [float(r) for r in sys.argv[5].split()]
oa_z, oa_du, oa_dv, near_probe_m = (float(sys.argv[i]) for i in (6, 7, 8, 9))
BIRD_R = 0.18          # config/birds/farm_world_birds.json, all three birds
FAR_M = 60.0           # config/depth_camera.json camera.clip_far_m
NEAR_M = 0.1


def load(tag):
    msg = json.load(open(f"{out}/frame_{tag}.json"))
    w, h = int(msg["width"]), int(msg["height"])
    # R_FLOAT32, one channel, little-endian -- '32FC1' once it crosses the ros_gz bridge.
    return np.frombuffer(base64.b64decode(msg["data"]), dtype="<f4").reshape(h, w).astype(float)


def blind_boxes(d):
    """The mask a detector would use with no knowledge of where the bird was put: any FINITE
    return. Sky past the far clip is +inf and the ground slab far exceeds DEFAULT_MAX_AREA, so the
    bird is the only component that survives the adopted morphology. Valid ONLY against sky."""
    return detect_blobs(np.isfinite(d), DEFAULT_MIN_AREA, DEFAULT_MAX_AREA)


results = []


def rec(name, ok, detail):
    results.append((name, bool(ok), detail))


# ---------------- D2: mount geometry, from the close on-axis capture ------------------------------
d = load(int(d2_range))
h, w = d.shape
fx = None
try:
    fx = float(json.load(open(f"{out}/camera_info.json"))["intrinsics"]["k"][0])
except Exception:
    fx = (w / 2.0) / math.tan(1.1033 / 2.0)
finite = np.isfinite(d)
if not finite.any():
    print("[verify_depth_mount] D2 FAIL: every pixel is non-finite -- nothing in the frustum at all")
    raise SystemExit(1)
expect_m = d2_range - BIRD_R
near_min = float(d[finite].min())
occl = finite & (d < 1.0)
boxes = blind_boxes(d)
if boxes:
    x0, y0, x1, y1 = min(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    cu, cv = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    err_px = math.hypot(cu - w / 2.0, cv - h / 2.0)
else:
    cu = cv = float("nan"); err_px = float("inf")

rec("D2 CLEAR", int(occl.sum()) == 0,
    f"{int(occl.sum())} finite pixels nearer than 1.0 m (airframe self-occlusion; want 0)")
rec("D2 RANGE", abs(near_min - expect_m) <= tol_m,
    f"nearest finite depth {near_min:.3f} m vs the bird's near surface {expect_m:.3f} m "
    f"(tol {tol_m:.2f} m); a NADIR mount from this pose would read 15.000 m to the ground")
rec("D2 AIM  ", err_px <= tol_px,
    f"blind near-cluster centroid ({cu:.0f},{cv:.0f}) vs principal point ({w/2:.0f},{h/2:.0f}) "
    f"-- error {err_px:.1f} px (tol {tol_px:.0f}), {len(boxes)} component(s) survived")

# ---------------- D2-OFFAXIS: the reading is Z-DEPTH, not slant range -----------------------------
doa = load("offaxis")
fin_oa = np.isfinite(doa)
ratio = math.sqrt(1.0 + (oa_du / fx) ** 2 + (oa_dv / fx) ** 2)
expect_z = oa_z - BIRD_R / ratio                 # near surface, expressed as Z-depth
expect_slant = oa_z * ratio - BIRD_R             # what a slant-range sensor would report
boxes_oa = blind_boxes(doa)
if boxes_oa and fin_oa.any():
    bx = min(boxes_oa, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    ou, ov = 0.5 * (bx[0] + bx[2]), 0.5 * (bx[1] + bx[3])
    oa_min = float(doa[fin_oa].min())
else:
    ou = ov = float("nan"); oa_min = float("nan")
want_u, want_v = w / 2.0 + oa_du, h / 2.0 + oa_dv
rec("D2 OFFAX", abs(oa_min - expect_z) <= tol_m and abs(oa_min - expect_slant) > tol_m,
    f"off-axis reading {oa_min:.3f} m == Z-DEPTH {expect_z:.3f} m and NOT slant range "
    f"{expect_slant:.3f} m ({expect_slant - expect_z:.2f} m apart, tol {tol_m:.2f} m). The on-axis "
    f"capture above cannot tell these apart -- they are equal by construction there")
rec("D2 AXES ", math.hypot(ou - want_u, ov - want_v) <= tol_px,
    f"off-axis target lands at ({ou:.0f},{ov:.0f}) vs predicted ({want_u:.0f},{want_v:.0f}) "
    f"-- pins u+ = right and v+ = down IN THE RENDER, not just in the matrix")

# ---------------- D2-CULL: refusal, not clamp -- in literal pixel values --------------------------
dn = load("near")
centre = dn[h // 2 - 2:h // 2 + 2, w // 2 - 2:w // 2 + 2]
near_literals = sorted({repr(float(v)) for v in centre.ravel()})
rec("D2 NEAR ", bool(np.all(np.isneginf(centre))),
    f"bird centre parked {near_probe_m:g} m ahead (surface {near_probe_m - BIRD_R:.2f} m, inside "
    f"the {NEAR_M:g} m near clip): the 4x4 block at the principal point reads {near_literals} "
    f"-- must be ['-inf'], NOT '{NEAR_M}'. This is the clamp `DepthDetectionSource` refuses")
inf_frac = float((~finite).mean())
rec("D2 FAR  ", inf_frac > 0.0,
    f"{100.0 * inf_frac:.0f}% of the 10 m frame is +inf (sky past the {FAR_M:g} m far clip) -- the "
    f"renderer refuses rather than clamping to {FAR_M:g}")
# ...and the far cull is on EUCLIDEAN slant range while the stored value is Z-depth, so the greatest
# finite Z-depth in the frame is far/|ray| AT ITS OWN PIXEL, not `far`.
vv, uu = np.nonzero(finite)
zz = d[finite]
i = int(np.argmax(zz))
ray = math.sqrt(1.0 + ((uu[i] - w / 2.0) / fx) ** 2 + ((vv[i] - h / 2.0) / fx) ** 2)
rec("D2 CULL ", abs(float(zz[i]) - FAR_M / ray) <= 1.0,
    f"greatest finite Z-depth {float(zz[i]):.2f} m at pixel ({uu[i]},{vv[i]}) where |ray| = "
    f"{ray:.3f}: matches far/|ray| = {FAR_M / ray:.2f} m, NOT the on-axis {FAR_M:g} m -- the far "
    f"cull is on EUCLIDEAN slant range while the value stored is Z-depth")

# ---------------- D3: the acquisition-range MEASUREMENT -------------------------------------------
print("[verify_depth_mount] D3 acquisition sweep -- BEST-CASE-SCENE RESOLVABILITY")
print("    (no clutter, static vehicle, noiseless sensor, sky background: an UPPER BOUND on the")
print("     mission horizon, where the bird crosses canopies and the ground band)")
detected = []
for r in ranges:
    dr = load(int(r))
    bs = blind_boxes(dr)
    hit = [b for b in bs
           if abs(0.5 * (b[0] + b[2]) - w / 2.0) <= 20 and abs(0.5 * (b[1] + b[3]) - h / 2.0) <= 20]
    span = (0.0 if not hit else 0.25 * ((hit[0][2] - hit[0][0]) + (hit[0][3] - hit[0][1])))
    print(f"    {r:5.1f} m  {'DETECTED' if hit else 'missed  '}  "
          f"r_apparent {span:5.2f} px (pinhole predicts {fx * BIRD_R / max(r, 1e-9):5.2f} px)")
    detected.append(bool(hit))

# CONTIGUOUS PREFIX, not max(): one lucky hit beyond a miss is aliasing, and letting it set the
# horizon would promote the booking gate to exit 0 on noise. The reported number is the longest
# range such that EVERY shorter tested range also detected.
acq = 0.0
for r, ok in zip(ranges, detected):
    if not ok:
        break
    acq = r
gaps = [r for r, ok in zip(ranges, detected) if ok and r > acq]
print(f"[verify_depth_mount] D3 MEASURED acquisition range: {acq:.1f} m "
      f"(longest CONTIGUOUS prefix of detected ranges; host-side pinhole bound 46.80 m)")
if gaps:
    print(f"[verify_depth_mount] D3 NOTE: isolated detections beyond the prefix at {gaps} m were "
          f"IGNORED -- a hit after a miss is aliasing, not horizon.")
print(f"    python3 scripts/predict_forward_lead.py --speed <mission> "
      f"--fx <K[0]> --cy <K[5]> --acq-range-m {acq:.1f}")
if acq >= max(ranges):
    print("[verify_depth_mount] NOTE: the bird was still detected at the LONGEST swept range, so "
          "this is a floor, not the horizon. Extend SWEEP_RANGES (and the far clip) to bound it.")

ok = True
for name, good, detail in results:
    ok = ok and good
    print(f"[verify_depth_mount] {name} {'PASS' if good else 'FAIL'}: {detail}")
print(f"[verify_depth_mount] {'PASS' if ok else 'FAIL'} -- forward depth mount geometry "
      f"{'agrees with' if ok else 'DISAGREES WITH'} scripts/check_depth_mount.py")
raise SystemExit(0 if ok else 1)
PYEOF
