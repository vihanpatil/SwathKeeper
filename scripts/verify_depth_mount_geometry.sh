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
# WHAT IT DOES. Launches a ZERO-GRAVITY copy of the farm world (the two edits are spelled out
# below), parks the vehicle at (60, 30, 15) nose-EAST — clear of both tree rows, with open sky along
# the optical axis — and teleports `bird_0` to known places, VERIFYING every teleport by reading the
# pose back off `/world/depthcheck/pose/info` before it scores a single pixel.
#
# THE TWO EDITS THIS SCRIPT MAKES TO ITS COPY OF THE WORLD, AND WHY (both dated 2026-09-06, the
# first time this gate was ever run):
#
#   1. PHYSICS IS KEPT AND GRAVITY IS ZEROED. The first version of this script deleted the physics
#      plugin so the nested-include vehicle would not free-fall — and every teleport then did
#      nothing at all. `/world/<w>/set_pose` is served by UserCommands, whose `PoseCommand::Execute`
#      -> `updatePose()` ONLY creates/updates a `components::WorldPoseCmd` component (gz-sim8
#      `src/systems/user_commands/UserCommands.cc`); the ONLY consumer of that component is
#      `PhysicsPrivate::UpdatePhysics` (`src/systems/physics/Physics.cc`, ~L2873-2946), which
#      applies the pose through `entityModelMap` and removes the component on the next iteration.
#      No Physics system => the command is queued and never consumed => the bird never moves. The
#      service still replies `data: true`, because that Boolean means QUEUED, not MOVED — which is
#      exactly how the first run of this gate scored a bird that was never in frame: D2 CLEAR and
#      D2 FAR "passed" while RANGE/AIM/OFFAX/AXES/NEAR read nan and D3 came back 0.0 m.
#      The vehicle cannot be made `<static>` instead: it is a NESTED include and does not inherit
#      `<static>` from its wrapper model (the 2026-08-18 finding, reconfirmed 2026-09-06 — with
#      `<static>true</static>` on the wrapper it still fell 15.0 -> 0.19 m). Zeroing gravity leaves
#      physics honest and parks a free body with no forces on it: the vehicle held EXACTLY
#      (60, 30, 15) from t0 to the end of a >25 s probe. This script ASSERTS that twice (world-up
#      and after the last capture) rather than assuming it.
#
#   2. field_ground's plane grows 125.00 -> 425.00 m east-west, IN THE COPY ONLY. The real ground is
#      a 125.00 x 110.00 m plane centred at (37.5, 30), so its east edge is x = 100 — just 39.85 m
#      ahead of the parked camera at x = 60.15. Nothing in the real world reaches the 60 m far clip
#      from this pose, so D2 CULL has nothing to measure: the first run read a greatest finite
#      Z-depth of 39.70 m, which is the scene's EDGE, not the clip. The extension changes nothing
#      about the sensor, the mount, the bird or any other gate; the finite/+inf boundary it creates
#      is a clean curve (24 partially-finite rows, ZERO fragment components through the morphology),
#      and with it the 10 m frame reads 57.99 m at |ray| 1.034 = far/|ray|, which is the assertion.
#
# Both edits live ONLY in /tmp/depthcheck/world.sdf. `sim/worlds/farmguard_field.sdf` and
# `scripts/gen_farm_world.py` are untouched (the host suite pins that), and this script refuses to
# launch — exit 4 — if the copy did not come out with exactly the edits described above.
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
#         far/|ray| at its own pixel, not `far`. (This is the assertion edit 2 exists for.)
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
#       AND THE SWEEP IS ASSERTED TO BE A SWEEP, TWICE OVER:
#         · G105 DISTINCTNESS. Every captured frame is hashed (sha1 over the base64 image data) and
#           any two identical frames are a harness failure, exit 4. A wedged renderer that
#           republishes one frame would score every range off ONE capture and hand back a long,
#           entirely false prefix -- the same shape as the run that scored a bird that never moved,
#           with the repetition on the sensor side instead of the pose side. Until 2026-09-07 the
#           only protection was INCIDENTAL (offaxis and near are captured AFTER the sweep, so a
#           stuck frame would fail D2 OFFAX / D2 NEAR); incidental is not gated.
#         · PER-STATION DEPTH EVIDENCE (2026-09-07, QA). Distinctness is necessary and NOT
#           sufficient: fifteen different frames can still be fifteen frames of a bird that is not
#           where the sweep thinks it is (sensor noise alone makes two captures of one scene
#           distinct). So each station's detected component must also CARRY ITS RANGE: the median
#           finite depth inside the blob's box must match the bird's true Z (R - 0.18 m) within
#           TOL_M. A component in the right place with the wrong depth is a frame from another
#           station or a mis-teleport, and `r_apparent` cannot tell either apart -- at these
#           ranges the footprint has PLATEAUED at 4x4 px, so apparent size stops changing with
#           range while depth does not. Any station failing this makes the sweep NOT A MEASUREMENT:
#           the booking line is refused and the run exits 4, the harness class, because a stuck
#           frame or a mis-teleport is a fact about the harness and not about the mount.
#           Measured on the run-2 frames (2026-09-07): member depths track true Z to 0.02-0.16 m at
#           every station 10..58 m, so TOL_M 0.20 m is a real bound and not a formality.
#       D3 PRINTS TWO NUMBERS, and only one of them books a flight (ADR-020 amendment 1, after the
#       2026-09-06 run detected at EVERY swept range out to 58 m):
#         · the OPTICAL PREFIX — the contiguous prefix itself. In this sky-backed scene an analytic
#           sphere plus gz's hardcoded AA(2) returns a finite depth for any pixel a sample touches,
#           so the footprint PLATEAUS at a 4x4 px patch instead of shrinking, and the prefix is
#           clip-limited rather than optics-limited. It is a resolvability FLOOR, not a horizon.
#         · the BOOKABLE range — the longest prefix range that also sits inside the frame-corner
#           Z-depth horizon far/|ray_corner| (47.56 m on today's live fx/cy). Past that bound the
#           SAME target away from the optical axis is culled to +inf, which is the asymmetry D2 CULL
#           measures two gates up; a horizon has to hold at the worst pixel, not the best one.
#       Feed the BOOKABLE number to the booking gate — ONLY from a run that exited 0. The gate takes
#       all SIX intrinsics off ONE live camera_info or none (a partial set is exit 2: a live number
#       beside a config number is an answer assembled from two different cameras), so this script
#       prints the whole command with the SIX LIVE VALUES already substituted, read from the
#       camera_info this run captured:
#           python3 scripts/predict_forward_lead.py --speed <mission> \
#                   --fx <K[0]> --fy <K[4]> --cx <K[2]> --cy <K[5]> --width <W> --height <H> \
#                   --acq-range-m <D3 BOOKABLE> --acq-optical-prefix-m <D3 OPTICAL PREFIX>
#       If camera_info did NOT parse, that command line is REFUSED rather than printed with the
#       config fallback in it: six config numbers wearing the live flags is the same lie the gate's
#       own exit 2 exists to prevent, and it would be undetectable downstream.
#       Host-side arithmetic predicts 46.80 m; THIS is the number ADR-019 item 6 means by "from the
#       sensor, never from config prose". On a FAILING run the sweep still prints as a diagnostic,
#       but the number is labelled NOT A MEASUREMENT and the command line above is refused: it was
#       read through geometry the same run disproved, and it is the one line whose whole purpose is
#       to authorise a flight.
#
# Run after ANY change to config/depth_camera.json's mount block, the vehicle SDF, or depth_detect's
# extrinsic — and once before the dodge flight is booked:
#
#   bash /workspace/fieldguard/scripts/verify_depth_mount_geometry.sh
#
# EXIT CODES
#   0  GATE VERIFIED — D2 + D2-OFFAXIS + D2-CULL all PASS. (D3 is a MEASUREMENT and never fails the
#      gate on its own; a SHORT D3 is reported and then fails the BOOKING gate, which is the correct
#      place for it to bite.)
#   1  GATE FAIL, from the python scoring block, with the failing assertion named. Do NOT trust any
#      depth-derived detection from this mount.
#   2  the depth topic never appeared — the world did not load, or it does not carry the sensor.
#   3  D1: /<world>/depth/camera_info is not the name gz derived from <topic>. The bridge yaml is
#      bridging a topic that does not exist and will advertise silence.
#   4  HARNESS SELF-CHECK FAILED — a stale gz server was already up, the world copy did not get its
#      two edits, a teleport did not apply, TWO SWEEP FRAMES CAME BACK BYTE-IDENTICAL (a repeated
#      frame is not a sweep), A SWEEP STATION'S BLOB CARRIED THE WRONG DEPTH (its median finite
#      depth is further than TOL_M from the bird's true Z — a frame from another station, or a bird
#      that did not go where it was told), a probe the run depends on did not answer, or the vehicle
#      is not parked where every D2 prediction assumes.
#      NOTHING PRINTED IS A MEASUREMENT: the scene is not the scene these gates score.
#   124/130/143  ABORTED, NOT SCORED (a `timeout` expired, Ctrl-C, SIGTERM) — same standing as 4,
#      but reached WITHOUT a banner, so read the code. Every abort the script can anticipate is
#      routed through `harness_fail` into 4 instead; these are what is left when the run is killed
#      from outside. The distinction that matters is not which code: it is that codes 0 and 1 are
#      the ONLY two that say anything about the mount. (2026-09-06: before this table grew these
#      rows, an unguarded `grep` exited 1 and an unguarded `timeout` exited 124 — one wearing the
#      gate-fail code, one wearing nothing at all.)
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
# Every teleport and both vehicle-park checks are read back to this tolerance. It is tight on
# purpose: these are commanded poses in a world with no forces, so anything that is not a rounding
# difference means the pose did not apply.
POSE_TOL_M=0.05
VEHICLE=iris_with_gimbal_ndvi
BIRD=bird_0
# field_ground's east-west extent IN THE CHECK COPY ONLY (the committed world is 125.00) — see
# edit 2 in the header. Both the visual and the collision plane are rewritten.
GROUND_EW_M=425.00
# Vehicle parked here; camera sits 0.15 m further east (the mount offset), nose-east so body +X is
# world +X. Ranges are Z-DEPTH from the camera.
PARK_E=60; PARK_N=30; PARK_U=15
CAM_E=60.15
D2_RANGE=10
# 5 m steps out to 40, then 2 m to 58, where the pinhole bound (46.80 m) says the target stops
# resolving: the number the booking gate consumes deserves better than a 5 m quantum there. The tail
# past 54 is not padding — the 2026-09-06 probe still resolved a 4x4 px component at 46 m (min_area
# 6), so the contiguous prefix may run well past the host-side bound, and a sweep that ENDS while
# still detecting reports a FLOOR, not a horizon. 58 m on-axis has slant 58 m < the 60 m far clip,
# so the last step is not culled; going further would measure the clip instead of the target.
SWEEP_RANGES="10 20 25 30 35 40 42 44 46 48 50 52 54 56 58"
# Off-axis probe: Z-depth 20 m at pixel (cx+240, cy-120). Right and UP so the background is sky and
# the blind mask still works; the down-and-right corner would sit in the ground band, which is the
# clutter-merging case the segmenter session owns (see the runbook's Known gaps).
OFFAXIS_Z=20.0; OFFAXIS_DU=240.0; OFFAXIS_DV=-120.0
NEAR_PROBE_M=0.25          # bird CENTRE 0.25 m ahead -> near surface 0.07 m, inside the 0.1 m clip

export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share"

harness_fail() {
  echo "[verify_depth_mount] FAIL (harness self-check): $*"
  echo "[verify_depth_mount] exit 4 — NOTHING PRINTED IS A MEASUREMENT. The scene is not the"
  echo "                     scene these gates score; fix the harness, then re-run. (2026-09-06:"
  echo "                     a run that could not move the bird still printed two PASSes.)"
  exit 4
}

# --- teardown, and it WAITS -----------------------------------------------------------------------
# A stale server keeps advertising this world's topics and would answer a LATER gate's probes, so
# "we sent SIGTERM" is not teardown; "the topics are gone" is.
gz_alive() {
  kill -0 "${GZ_PID:-}" 2>/dev/null || return 1
  # A ZOMBIE is not alive: `kill -0` keeps succeeding on one until the shell reaps it, and this
  # loop would otherwise spin its whole timeout and then SIGKILL a corpse.
  case "$(ps -o stat= -p "$GZ_PID" 2>/dev/null | tr -d ' ')" in Z*|"") return 1 ;; esac
  return 0
}

teardown() {
  [ -n "${GZ_PID:-}" ] || return 0
  local n=0 m=0
  kill "$GZ_PID" 2>/dev/null || true
  while gz_alive; do
    sleep 1; n=$((n + 1))
    if [ "$n" -ge 60 ]; then
      echo "[verify_depth_mount] teardown: pid $GZ_PID ignored SIGTERM for 60 s — sending SIGKILL"
      kill -9 "$GZ_PID" 2>/dev/null || true
      break
    fi
  done
  wait "$GZ_PID" 2>/dev/null || true
  while gz topic -l 2>/dev/null | grep -q "^${TOPIC}$"; do
    sleep 1; m=$((m + 1))
    if [ "$m" -ge 30 ]; then
      echo "[verify_depth_mount] teardown WARNING: ${TOPIC} is STILL advertised ${m} s after the"
      echo "                     server exited. Something else is serving this world — find it"
      echo "                     before running any gate that probes /${WORLD}/."
      break
    fi
  done
  echo "[verify_depth_mount] teardown: server gone in ${n} s, its topics gone ${m} s later"
}
trap teardown EXIT

# --- stale-server guard, BEFORE anything is launched or measured ----------------------------------
gz_server_pids() {
  # `pgrep -f "gz sim"` is the wrong tool and cost a probe on 2026-09-06: -f matches the WHOLE
  # command line, so any `bash -c '... gz sim ...'` wrapper — including this gate — matches itself
  # and gets killed. `pgrep -x gz` is worse: it is VACUOUS, because /usr/bin/gz is a ruby script and
  # the server's comm is `ruby`. So read argv positionally instead: argv[0] is the program (`gz`, or
  # the `ruby` that `gz` execs) and `sim` is its first real argument. A shell can never match this.
  ps -eo pid=,args= 2>/dev/null | awk '
    { prog = $2; sub(/.*\//, "", prog); second = $3; sub(/.*\//, "", second) }
    prog == "gz" && $3 == "sim"                          { print $1; next }
    prog ~ /^ruby[0-9.]*$/ && second == "gz" && $4 == "sim" { print $1 }'
}
STALE_TOPICS="$(gz topic -l 2>/dev/null | grep "^/${WORLD}/" || true)"
STALE_PIDS="$(gz_server_pids || true)"
if [ -n "$STALE_TOPICS" ] || [ -n "$STALE_PIDS" ]; then
  echo "[verify_depth_mount] a gz server is ALREADY running:"
  [ -z "$STALE_PIDS" ]   || echo "$STALE_PIDS" | sed 's/^/    pid /'
  [ -z "$STALE_TOPICS" ] || echo "$STALE_TOPICS" | sed 's/^/    still advertising /'
  harness_fail "refusing to start a second server. A leftover /${WORLD}/ server answers THIS" \
               "gate's probes with ITS scene, and a bringup's Gazebo starves the renderer" \
               "both would share. Tear it down first — 'scripts/fly_pipeline.sh down' for a" \
               "bringup, or 'kill <pid>' for a leftover (its topics go within ~3 s) — then re-run."
fi

rm -rf "$OUT"; mkdir -p "$OUT"

# --- the check-world copy: two edits, both asserted -----------------------------------------------
make_check_world() {   # $1 = source SDF, $2 = destination SDF
  # ORDER MATTERS: the world rename runs first (the -e list), so the `a` command's address in the
  # -f script matches the ALREADY-RENAMED line. sed concatenates -e and -f in argv order.
  # The append is a separate -f script because the POSIX `a\` form needs its own line, and that form
  # is the one both GNU sed (container) and BSD sed (the host test) accept.
  cat > "$2.sed" <<SEDEOF
/<world name="${WORLD}">/a\\
<gravity>0 0 0</gravity>
s|<size>125.00 110.00</size>|<size>${GROUND_EW_M} 110.00</size>|
SEDEOF
  # `fg/` -> `depthcheck/` renames BOTH camera namespaces at once, so this world cannot collide with
  # a live bringup on either the NDVI or the depth topics.
  sed -e "s/<world name=\"farmguard_field\">/<world name=\"${WORLD}\">/" \
      -e "s|fg/sensor|${WORLD}/sensor|g" \
      -e "s|fg/depth|${WORLD}/depth|g" \
      -e "s|<pose degrees=\"true\">0 0 0.195 0 0 90</pose>|<pose degrees=\"true\">${PARK_E} ${PARK_N} ${PARK_U} 0 0 0</pose>|" \
      -f "$2.sed" \
      "$1" > "$2"
}

make_check_world "$REPO/sim/worlds/farmguard_field.sdf" "$OUT/world.sdf"

# The copy is the harness. A sed that silently matched nothing (a regenerated world, a reformatted
# element) would put a falling vehicle or an unmovable bird under gates that cannot see either.
grep -q 'gz-sim-physics-system' "$OUT/world.sdf" || harness_fail \
  "the copy lost the Physics system — set_pose would be a silent no-op (see edit 1 in the header)"
WORLD_LINE="$(grep -n "<world name=\"${WORLD}\">" "$OUT/world.sdf" | head -1 | cut -d: -f1 || true)"
GRAV_LINE="$(grep -n '<gravity>0 0 0</gravity>' "$OUT/world.sdf" | head -1 | cut -d: -f1 || true)"
GRAV_N="$(grep -c '<gravity>0 0 0</gravity>' "$OUT/world.sdf" || true)"
GROUND_N="$(grep -c "<size>${GROUND_EW_M} 110.00</size>" "$OUT/world.sdf" || true)"
if [ -z "$WORLD_LINE" ] || [ "$GRAV_N" != "1" ] || [ "$GRAV_LINE" != "$((WORLD_LINE + 1))" ]; then
  harness_fail "expected exactly one <gravity>0 0 0</gravity> as the first child of <world" \
               "name=\"${WORLD}\"> (found ${GRAV_N} at line ${GRAV_LINE:-none}, world at" \
               "line ${WORLD_LINE:-none}) — the vehicle would free-fall out of the scene"
fi
[ "$GROUND_N" = "2" ] || harness_fail \
  "the ground-plane extension hit ${GROUND_N} of the 2 planes (visual + collision) — D2 CULL" \
  "would measure the scene's 39.85 m edge instead of the 60 m far clip"
grep -q "<pose degrees=\"true\">${PARK_E} ${PARK_N} ${PARK_U} 0 0 0</pose>" "$OUT/world.sdf" || \
  harness_fail "the vehicle park pose did not apply — every D2 prediction assumes (${PARK_E}," \
               "${PARK_N}, ${PARK_U}) nose-east"
echo "[verify_depth_mount] world copy OK: physics KEPT + gravity zeroed, field_ground extended to" \
     "${GROUND_EW_M} m E-W (copy only), vehicle parked at (${PARK_E}, ${PARK_N}, ${PARK_U})"

gz sim -v1 -s -r --headless-rendering "$OUT/world.sdf" > "$OUT/gz.log" 2>&1 &
GZ_PID=$!

N=0
# ANCHORED, exactly like the listing below it. An unanchored wait would accept a topic under some
# other prefix and then hand the anchored listing nothing to print — turning "the sensor is
# namespaced somewhere unexpected" into a bare abort instead of this loop's documented exit 2.
until gz topic -l 2>/dev/null | grep -q "^/${WORLD}/depth/image$"; do
  sleep 1; N=$((N+1))
  if [ $N -gt 30 ]; then echo "[verify_depth_mount] FAIL: depth topic never appeared"; exit 2; fi
done

# The DERIVED info-topic name, printed as evidence rather than assumed. gz-sensors8 builds it by
# dropping the LAST SEGMENT of <topic> (CameraSensor::AdvertiseInfo), because DepthCameraSensor
# never calls CameraSensor::Load and so ignores <camera_info_topic> entirely. If it comes back as
# .../image/camera_info, sim/bridge/fg_sensor_bridge.yaml is bridging a topic that does not exist
# and the bridge will sit there advertising silence.
echo "[verify_depth_mount] advertised depth topics:"
# `|| harness_fail`, because an unmatched grep is exit 1 under `set -euo pipefail` — the code the
# table above sells as GATE FAIL, with the D1 diagnostic below never reaching the screen.
gz topic -l | grep "^/${WORLD}/depth" | sed 's/^/    /' || harness_fail \
  "the depth topic list did not print — nothing is advertised under /${WORLD}/depth, though the" \
  "wait loop just saw ${TOPIC}. The server is going away underneath this gate, or the topic" \
  "namespace changed between the two probes."
if ! gz topic -l | grep -qx "/${WORLD}/depth/camera_info"; then
  echo "[verify_depth_mount] FAIL (D1): /${WORLD}/depth/camera_info is not advertised — gz derived a"
  echo "                     different name. Fix the bridge yaml to match what is printed above; do"
  echo "                     NOT add a <camera_info_topic> to the world (this sensor ignores it)."
  exit 3
fi
gz topic -e -t "/${WORLD}/depth/camera_info" -n 1 --json-output > "$OUT/camera_info.json" 2>/dev/null || true
# The booking gate takes the SIX as a SET off ONE message or refuses (exit 2), so all six print
# here, spelled as the flags they travel on. Full repr, not rounded: fx and fy differ in the last
# ULP on this sensor and a rounded pair would read as "square pixels, confirmed" when it is only
# "square to 15 digits". The scoring block below re-reads the same file and prints the whole
# command line with these values substituted.
echo "[verify_depth_mount] LIVE intrinsics — the booking gate takes all SIX or none (its exit 2):"
python3 -c "
import json
try:
    ci=json.load(open('$OUT/camera_info.json'))
    k=ci['intrinsics']['k']
    print('    --fx', repr(k[0]), '--fy', repr(k[4]), '--cx', repr(k[2]), '--cy', repr(k[5]))
    print('    --width', ci['width'], '--height', ci['height'])
except Exception as exc:
    print('    (could not parse camera_info:', exc, '- read', '$OUT/camera_info.json', 'by hand.')
    print('     The booking command line will be REFUSED: config numbers wearing the live flags')
    print('     are exactly what the booking gate refuses a partial set to prevent.)')
"

# --- pose readback: the only thing that knows whether a teleport happened -------------------------
pose_check() {  # $1 = model, $2 = east, $3 = north, $4 = up. Prints the ACTUAL pose; returns 1 if
                # it is further than POSE_TOL_M from the request on any axis (or absent entirely).
  timeout 10 gz topic -e -t "/world/${WORLD}/pose/info" -n 1 \
    > "$OUT/pose_info.txt" 2>/dev/null || true
  python3 - "$OUT/pose_info.txt" "$1" "$2" "$3" "$4" "$POSE_TOL_M" <<'PYEOF'
import re, sys
path, name = sys.argv[1], sys.argv[2]
want = [float(v) for v in sys.argv[3:6]]
tol = float(sys.argv[6])
try:
    text = open(path).read()
except OSError:
    print("unreadable"); raise SystemExit(1)
got = None
for block in text.split("\npose {"):          # one Pose_V message: a block per entity
    if f'name: "{name}"' in block:
        body = re.search(r"position\s*{([^}]*)}", block)
        if body:                              # proto text omits fields that are exactly 0.0
            v = dict(re.findall(r"([xyz]):\s*(-?[0-9.eE+-]+)", body.group(1)))
            got = [float(v.get(k, 0.0)) for k in "xyz"]
        break
if got is None:
    print("no pose published"); raise SystemExit(1)
print(f"{got[0]:.3f}, {got[1]:.3f}, {got[2]:.3f}")
raise SystemExit(0 if all(abs(g - w) <= tol for g, w in zip(got, want)) else 1)
PYEOF
}

BIRD_POSE="(not yet teleported)"

teleport() {  # $1 = east, $2 = north, $3 = up (world metres) — and it VERIFIES
  local reply got
  reply="$(gz service -s "/world/${WORLD}/set_pose" --reqtype gz.msgs.Pose \
           --reptype gz.msgs.Boolean \
           --timeout 2000 --req "name: \"${BIRD}\", position: {x: $1, y: $2, z: $3}, orientation: {z: 0.0, w: 1.0}" 2>&1 || true)"
  # `data: true` means the command was QUEUED (UserCommands replies from ServiceHandler, before
  # anything is applied). It is necessary and NOT sufficient — hence the readback below.
  case "$(printf '%s' "$reply" | tr -d '[:space:]')" in
    *data:true*) ;;
    *) harness_fail "set_pose(${BIRD} -> $1, $2, $3) was refused; the reply was:" \
                    "${reply:-<empty>}" ;;
  esac
  sleep 1                                   # one physics iteration consumes the WorldPoseCmd
  if ! got="$(pose_check "$BIRD" "$1" "$2" "$3")"; then
    harness_fail "${BIRD} DID NOT MOVE. Requested ($1, $2, $3); /world/${WORLD}/pose/info reads" \
                 "(${got}) — beyond ${POSE_TOL_M} m. set_pose is applied ONLY by the Physics" \
                 "system, so check the copy still has gz-sim-physics-system (header, edit 1)."
  fi
  BIRD_POSE="$got"
}

vehicle_check() {  # $1 = when, for the message
  local got
  if ! got="$(pose_check "$VEHICLE" "$PARK_E" "$PARK_N" "$PARK_U")"; then
    harness_fail "the vehicle is NOT parked where every D2 prediction assumes ($1). Requested" \
                 "(${PARK_E}, ${PARK_N}, ${PARK_U}); pose/info reads (${got}). A drifting or" \
                 "falling vehicle makes RANGE, AIM, OFFAX and CULL measurements of nothing."
  fi
  echo "[verify_depth_mount] vehicle parked at (${got}) — $1"
}

capture() {  # $1 = label, $2 = what the bird is doing in this frame
  sleep 2
  echo "[verify_depth_mount] capturing $1 — ${BIRD} at (${BIRD_POSE}): $2"
  printf '%s\n' "$BIRD_POSE" > "$OUT/pose_$1.txt"
  # Bare, an expired `timeout` aborts the whole run at exit 124 — a code no gate assertion can
  # produce — with no banner and a 0-byte frame left behind. Name it instead.
  timeout 30 gz topic -e -t "$TOPIC" -n 1 --json-output > "$OUT/frame_$1.json" || harness_fail \
    "no depth frame within 30 s at capture $1 — the run is not scoreable. The renderer stalled or" \
    "the publisher stopped; ${OUT}/frame_$1.json is truncated or empty. Check ${OUT}/gz.log."
}

distinct_frames() {  # $@ = frame json files. Prints how many are DISTINCT; returns 1, naming the
                     # colliding pair, if any two carry the same pixels. A repeated frame means the
                     # renderer wedged and every range after it was scored off one capture.
                     # The delimiter is PYHASH and not PYEOF on purpose: the host test indexes the
                     # PYEOF heredocs positionally (0 = pose_check's, 1 = the scoring block's).
  python3 - "$@" <<'PYHASH'
import hashlib, json, sys
seen = {}
for path in sys.argv[1:]:
    try:
        data = json.load(open(path))["data"]
    except Exception as exc:
        print(f"{path} is unreadable or carries no image data ({exc})")
        raise SystemExit(1)
    digest = hashlib.sha1(data.encode()).hexdigest()
    if digest in seen:
        print(f"{path} is byte-identical to {seen[digest]} (sha1 {digest[:12]})")
        raise SystemExit(1)
    seen[digest] = path
print(len(seen))
PYHASH
}

# DepthCameraSensor::Update returns early when NOTHING is subscribed (gz-sensors8), so each frame is
# produced BECAUSE of this subscription. The first sleep also lets ogre2 warm up on llvmpipe.
sleep 5
vehicle_check "at world-up"

# --- the sweep (D3) + the 10 m on-axis capture (D2) ----------------------------------------------
SWEEP_N=0
SWEEP_FRAMES=""
for R in $SWEEP_RANGES; do
  E=$(python3 -c "print(f'{${CAM_E} + $R:.4f}')")
  teleport "$E" "${PARK_N}.0" "${PARK_U}.0"
  capture "$R" "Z-depth ${R} m from the camera at x=${CAM_E}"
  SWEEP_N=$((SWEEP_N + 1))
  SWEEP_FRAMES="$SWEEP_FRAMES $OUT/frame_$R.json"
done

# The list is built from the loop that captured it (not from a glob), so "all distinct" also means
# "all present". Unquoted on purpose: it is a whitespace-separated list of paths under $OUT.
if ! DISTINCT="$(distinct_frames $SWEEP_FRAMES)"; then
  harness_fail "the sweep frames are NOT all distinct — ${DISTINCT}. A wedged renderer repeating" \
               "one frame is not a sweep: every range would be scored off ONE capture, and D3" \
               "would report a contiguous prefix that measures the stuck frame rather than the" \
               "target. Check ${OUT}/gz.log."
fi
echo "[verify_depth_mount] sweep frames: ${DISTINCT} distinct of ${SWEEP_N} captured (sha1 over" \
     "each frame's base64 image data) — no frame was repeated"

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
capture "offaxis" "Z-depth ${OFFAXIS_Z} m, off-axis by (${OFFAXIS_DU}, ${OFFAXIS_DV}) px"

# --- the near-clip probe (D2-CULL) ----------------------------------------------------------------
teleport "$(python3 -c "print(f'{${CAM_E} + ${NEAR_PROBE_M}:.4f}')")" "${PARK_N}.0" "${PARK_U}.0"
capture "near" "centre ${NEAR_PROBE_M} m ahead — inside the 0.1 m near clip"

vehicle_check "after the last capture"

python3 - "$OUT" "$D2_RANGE" "$TOL_PX" "$TOL_M" "$SWEEP_RANGES" "$OFFAXIS_Z" "$OFFAXIS_DU" \
         "$OFFAXIS_DV" "$NEAR_PROBE_M" <<'PYEOF'
import base64, json, math, sys
sys.path.insert(0, "/workspace/fieldguard/src")
import numpy as np
# The corner bound is IMPORTED, never re-derived. It was inlined here until 2026-09-07 and was the
# THIRD copy of the formula and the wrong one: it read the principal point as w/2 and cy, divided
# both terms by fx, and never touched K[2] or K[4] at all. Each of those fails DANGEROUS -- an
# off-centre principal point makes the near corner give a LONGER, unmeasurable horizon -- and this
# bound is what CLAMPS the acquisition range a flight gets booked on (ADR-020 am. 1). The primitive
# lives beside `depth_pixel_to_enu`, which is the consumer that eats the error.
from fieldguard_planning.depth_detect import acquisition_range_m, corner_ray_ratio
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


def bird_pose(tag):
    """The VERIFIED pose the harness read back before this frame -- evidence, not a request."""
    try:
        return open(f"{out}/pose_{tag}.txt").read().strip()
    except OSError:
        return "?"


def blind_boxes(d):
    """The mask a detector would use with no knowledge of where the bird was put: any FINITE
    return. Sky past the far clip is +inf and the ground slab far exceeds DEFAULT_MAX_AREA, so the
    bird is the only component that survives the adopted morphology. Valid ONLY against sky."""
    return detect_blobs(np.isfinite(d), DEFAULT_MIN_AREA, DEFAULT_MAX_AREA)


results = []


def rec(name, good, detail):
    results.append((name, bool(good), detail))


# ---------------- D2: mount geometry, from the close on-axis capture ------------------------------
d = load(int(d2_range))
h, w = d.shape
# ALL SIX come off the SAME live camera_info or NONE of them does -- the booking gate's own rule
# (predict_forward_lead refuses a partial set, exit 2), and the corner bound below needs all six.
# The source is carried into the print rather than assumed: a corner bound computed from the config
# fallback is arithmetic, not a measurement, and the reader has to be able to tell. `intr_live` is
# what decides whether this run is entitled to print a booking command line at all.
try:
    ci = json.load(open(f"{out}/camera_info.json"))
    kk = ci["intrinsics"]["k"]
    fx, fy = float(kk[0]), float(kk[4])
    cx_px, cy_px = float(kk[2]), float(kk[5])
    ci_w, ci_h = float(ci["width"]), float(ci["height"])
    # Called for its REFUSAL, here where the fallback is still reachable: a camera_info that parses
    # but carries a degenerate set (fx 0, a 0-px frame) would otherwise raise out of the corner
    # bound 200 lines below and abort at exit 1 -- the code the exit table sells as a MOUNT verdict.
    corner_ray_ratio(ci_w, ci_h, fx, fy, cx_px, cy_px)
    intr_live = True
    intr_source = "live camera_info (fx=K[0], fy=K[4], cx=K[2], cy=K[5], width, height)"
except Exception as exc:
    fx = fy = (w / 2.0) / math.tan(1.1033 / 2.0)
    cx_px, cy_px = w / 2.0, h / 2.0
    ci_w, ci_h = float(w), float(h)
    intr_live = False
    intr_source = (f"CONFIG FALLBACK -- camera_info did NOT parse ({exc}): fx=fy from hfov 1.1033 "
                   f"rad, cx/cy at the frame centre, WxH from the frame itself")
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
    f"(tol {tol_m:.2f} m) with the bird read back at ({bird_pose(int(d2_range))}); a NADIR mount "
    f"from this pose would read 15.000 m to the ground")
rec("D2 AIM  ", err_px <= tol_px,
    f"blind near-cluster centroid ({cu:.0f},{cv:.0f}) vs principal point ({w/2:.0f},{h/2:.0f}) "
    f"-- error {err_px:.1f} px (tol {tol_px:.0f}), {len(boxes)} component(s) survived")

# ---------------- D2-OFFAXIS: the reading is Z-DEPTH, not slant range -----------------------------
doa = load("offaxis")
fin_oa = np.isfinite(doa)
# Vertical term over fy, horizontal over fx. They agree to 1 ULP on this sensor (square pixels),
# and the arithmetic must not silently depend on that staying true -- the same three-way rule
# `corner_ray_ratio` is written down for.
ratio = math.sqrt(1.0 + (oa_du / fx) ** 2 + (oa_dv / fy) ** 2)
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
ray = math.sqrt(1.0 + ((uu[i] - cx_px) / fx) ** 2 + ((vv[i] - cy_px) / fy) ** 2)
rec("D2 CULL ", abs(float(zz[i]) - FAR_M / ray) <= 1.0,
    f"greatest finite Z-depth {float(zz[i]):.2f} m at pixel ({uu[i]},{vv[i]}) where |ray| = "
    f"{ray:.3f}: matches far/|ray| = {FAR_M / ray:.2f} m, NOT the on-axis {FAR_M:g} m -- the far "
    f"cull is on EUCLIDEAN slant range while the value stored is Z-depth")

# ---------------- the verdicts, BEFORE anything they qualify --------------------------------------
# The fold runs first so D3 below knows whether it is entitled to hand over a number, and the
# per-gate lines print first so the failing assertion is NAMED before the long sweep table rather
# than buried under it. The one-line summary still goes last (see the bottom of this block).
ok = all(good for _, good, _ in results)
for name, good, detail in results:
    print(f"[verify_depth_mount] {name} {'PASS' if good else 'FAIL'}: {detail}")

# ---------------- D3: the acquisition-range MEASUREMENT -------------------------------------------
print("[verify_depth_mount] D3 acquisition sweep -- BEST-CASE-SCENE RESOLVABILITY")
print("    (no clutter, static vehicle, noiseless sensor, sky background: an UPPER BOUND on the")
print("     mission horizon, where the bird crosses canopies and the ground band)")
if not ok:
    print("    !! A MOUNT GATE FAILED ABOVE. What follows is DIAGNOSTIC ONLY -- do not write it")
    print("       down, and do not carry it to the booking gate.")
detected = []
depth_bad = []          # stations whose blob is in the right place carrying the WRONG range
for r in ranges:
    dr = load(int(r))
    bs = blind_boxes(dr)
    hit = [b for b in bs
           if abs(0.5 * (b[0] + b[2]) - w / 2.0) <= 20 and abs(0.5 * (b[1] + b[3]) - h / 2.0) <= 20]
    span = (0.0 if not hit else 0.25 * ((hit[0][2] - hit[0][0]) + (hit[0][3] - hit[0][1])))
    # PER-STATION DEPTH EVIDENCE. Distinctness (G105, above) proves the frames DIFFER; it cannot
    # prove each one is of THIS station -- sensor noise alone makes two captures of one scene
    # distinct. So the component has to carry its range: the median FINITE depth inside its box
    # (boxes are half-open, and +inf background inside the box is excluded by the mask) against the
    # bird's true near-surface Z. r_apparent cannot substitute: the footprint has PLATEAUED at
    # 4x4 px from 40 m out, so apparent size stops discriminating range exactly where the booking
    # number is read. A MISSED station is not checked -- a miss is the horizon, which is the thing
    # being measured, not a harness fault.
    want_z = r - BIRD_R
    z_med = float("nan")
    if hit:
        x0, y0, x1, y1 = (int(v) for v in hit[0])
        patch = dr[y0:y1, x0:x1]
        member = patch[np.isfinite(patch)]
        if member.size:
            z_med = float(np.median(member))
    z_ok = bool(hit) and math.isfinite(z_med) and abs(z_med - want_z) <= tol_m
    if hit and not z_ok:
        depth_bad.append((r, z_med, want_z))
    print(f"    {r:5.1f} m  {'DETECTED' if hit else 'missed  '}  "
          f"r_app {span:5.2f} px (pinhole {fx * BIRD_R / max(r, 1e-9):5.2f})  "
          f"z_med {z_med:6.2f} vs {want_z:6.2f} m{'' if not hit or z_ok else '  <<< WRONG DEPTH'}"
          f"   bird read back at ({bird_pose(int(r))})")
    detected.append(bool(hit))

# The sweep is scored ONLY if every detected station carried its own range. This runs before the
# prefix is computed, so a bad sweep can reach neither the bookable number nor the command line.
if depth_bad:
    print("[verify_depth_mount] FAIL (harness self-check): the D3 sweep is NOT A MEASUREMENT --")
    for r, zm, wz in depth_bad:
        gap = abs(zm - wz)
        print(f"    {r:5.1f} m station: blob median depth {zm:.3f} m vs the bird's true Z "
              f"{wz:.3f} m -- {gap:.3f} m apart (tol {tol_m:.2f} m), bird read back at "
              f"({bird_pose(int(r))})")
    print("    A component at the principal point carrying the WRONG depth is a frame from ANOTHER")
    print("    station, or a bird that did not go where it was told. Frame distinctness cannot see")
    print("    either (noise makes any two captures differ) and r_apparent cannot either (the")
    print("    footprint plateaus at 4x4 px past 40 m). A contiguous prefix built from those")
    print("    stations would be a horizon measured off the wrong scene, and it is the number that")
    print("    authorises a flight.")
    print("[verify_depth_mount] exit 4 — NOTHING PRINTED IS A MEASUREMENT. This is the HARNESS")
    print("                     class, not a mount verdict: a stuck frame or a mis-teleport says")
    print("                     nothing about the mount. Check /tmp/depthcheck/gz.log, then re-run.")
    raise SystemExit(4)

# CONTIGUOUS PREFIX, not max(): one lucky hit beyond a miss is aliasing, and letting it set the
# horizon would promote the booking gate to exit 0 on noise. The reported number is the longest
# range such that EVERY shorter tested range also detected.
# The loop variable is NOT called `ok`: that is the verdict, folded above, and a `for` target leaks
# in python. Named `ok`, a sweep that detected at every range would hand a FAILED mount a PASS.
acq = 0.0
for r, seen in zip(ranges, detected):
    if not seen:
        break
    acq = r
gaps = [r for r, seen in zip(ranges, detected) if seen and r > acq]
if gaps:
    print(f"[verify_depth_mount] D3 NOTE: isolated detections beyond the prefix at {gaps} m were "
          f"IGNORED -- a hit after a miss is aliasing, not horizon.")

# THE PREFIX IS NOT THE BOOKABLE NUMBER (ADR-020 amendment 1, 2026-09-06). The far cull is on
# EUCLIDEAN slant range -- D2 CULL above MEASURED that in this render -- so the Z-depth at which a
# target at the FRAME CORNER is still returned is far/|ray_corner|, not `far`. A range the optics
# resolve on-axis past that bound is a fact about the optics and NOT a horizon the vehicle can be
# flown on: the same target away from the axis is culled to +inf. So the number handed to the
# booking gate is the longest CONTIGUOUS-PREFIX range that ALSO sits inside the corner bound, and
# the prefix is reported beside it as a best-case-scene resolvability floor. `min()` of the two is
# deliberately taken at a SWEPT value: the bound itself is a computed number at which nothing was
# ever measured to be detectable, and the quantisation rounds the horizon DOWN, i.e. toward less
# lead time -- conservative by construction.
corner_ray = corner_ray_ratio(ci_w, ci_h, fx, fy, cx_px, cy_px)
far_corner = FAR_M / corner_ray
acq_book = max([r for r, seen in zip(ranges, detected) if seen and r <= acq and r <= far_corner],
               default=0.0)
above = [r for r in ranges if r > acq_book]
if ok:
    # The pinhole x morphology bound is CORROBORATION, not a term in `acq_book` -- see the comment
    # above and ADR-020 am. 2's four-bound table. Derived from the LIVE fx rather than printed as
    # the literal 46.80 it was until 2026-09-07: a hardcoded corroborating number goes stale
    # silently the first time this mount's optics change, and a stale number beside a live one is
    # the two-cameras-in-one-answer defect in miniature.
    print(f"[verify_depth_mount] D3 OPTICAL PREFIX: {acq:.1f} m -- longest CONTIGUOUS prefix of "
          f"detected ranges (host pinhole x morphology bound, from this run's fx: "
          f"{acquisition_range_m(fx, BIRD_R):.2f} m -- corroboration, NOT a term in the bookable "
          f"number below). Resolvability, NOT a horizon.")
    print(f"[verify_depth_mount] D3 MEASURED acquisition range, BOOKABLE: {acq_book:.1f} m -- the "
          f"longest prefix range inside the {far_corner:.2f} m frame-corner Z-depth horizon "
          f"({FAR_M:g} m / |ray_corner| {corner_ray:.3f} at the corner FARTHEST from the principal "
          f"point), from fx {fx:.3f} / fy {fy:.3f} / cx {cx_px:.1f} / cy {cy_px:.1f} px over "
          f"{ci_w:.0f}x{ci_h:.0f}, all from {intr_source}.")
    if above and acq_book > 0.0:      # `0.0 is the last swept value under the bound` is nonsense
        print(f"    SWEEP QUANTUM: the next swept range is {above[0]:.1f} m, so {acq_book:.1f} is "
              f"the last SWEPT value under the bound, not the bound. The true horizon lies in "
              f"[{acq_book:.1f}, {min(above[0], far_corner):.2f}] m; booking the low end costs "
              f"lead time, which is the safe direction to be wrong in.")
    if acq > acq_book:
        print(f"    NOTE: the optics still resolved the bird at {acq:.1f} m, past the corner "
              f"horizon. That excess is NOT bookable, and raising clip_far_m to chase it walks "
              f"the finite-ground band UP into the +/-6 m threat band -- see ADR-020 am. 1.")
    if acq_book > 0.0 and intr_live:
        # The SIX are substituted from THIS run's camera_info, at full repr: the gate refuses a
        # partial set (exit 2) and a hand-retyped intrinsic is how a partial set happens. fx and fy
        # differ in the last ULP on this sensor, so rounding them would print two numbers that are
        # equal when the sensor's are not. Only --speed stays a placeholder -- it is the one input
        # that is a decision rather than a measurement.
        print(f"    python3 scripts/predict_forward_lead.py --speed <mission> \\")
        print(f"        --fx {fx!r} --fy {fy!r} --cx {cx_px!r} --cy {cy_px!r} \\")
        print(f"        --width {ci_w:.0f} --height {ci_h:.0f} \\")
        print(f"        --acq-range-m {acq_book:.1f} --acq-optical-prefix-m {acq:.1f}")
    elif acq_book > 0.0:
        print("    REFUSING to print a booking command line: the intrinsics are the CONFIG "
              "FALLBACK, not this run's camera_info. Six config numbers wearing the live flags "
              "would pass the gate's set check and answer ADR-019 item 6 with prose. Fix "
              f"{out}/camera_info.json (it is captured right after the D1 check) and re-run.")
    else:
        print("    REFUSING to print a booking command line: no swept range was both in the "
              "contiguous prefix AND inside the frame-corner horizon, so this run measured no "
              "bookable acquisition range at all.")
    if acq >= max(ranges):
        print("[verify_depth_mount] NOTE: the bird was still detected at the LONGEST swept range, "
              "so the OPTICAL PREFIX is a floor, not the horizon. The sweep already ends just "
              "inside the far clip, so bounding it further needs a longer clip in "
              "config/depth_camera.json -- a pinned-config change, with a DECISIONS.md entry, and "
              "ADR-020 am. 1 argues against it.")
else:
    # The sweep prefix still printed above, because it is the diagnostic that tells you whether the
    # target was even resolvable. What it is NOT is a property of this mount: it was measured
    # through geometry this run just disproved. So the number is labelled and the one line an
    # operator would copy -- the command that books a flight -- is refused outright.
    print(f"[verify_depth_mount] D3 (NOT A MEASUREMENT OF THIS MOUNT -- the gate FAILED above): "
          f"the contiguous prefix reached {acq:.1f} m in a scene whose geometry is wrong.")
    print("    REFUSING to print a predict_forward_lead.py command line. An acquisition range read "
          "through a mount that failed D2 cannot authorise a flight: fix the mount, re-run this "
          "gate to exit 0, and take the number from THAT run.")

print(f"[verify_depth_mount] {'PASS' if ok else 'FAIL'} -- forward depth mount geometry "
      f"{'agrees with' if ok else 'DISAGREES WITH'} scripts/check_depth_mount.py")
raise SystemExit(0 if ok else 1)
PYEOF
