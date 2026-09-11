#!/usr/bin/env bash
# Cluttered labelled depth dataset capture — runs INSIDE fieldguard-sim; the renderer must be idle.
# Spec: docs/design/DEPTH_SEGMENTER_DESIGN.md §5 (+ §5.2 harness requirements 1-3, all enforced here).
# Input : /tmp/stations.json  = {"stations":[{id, cam_enu:[E,N,U], cam_yaw_deg, cam_rpy_deg?, bird_enu:[E,N,U], ...}]}
# Output: /tmp/depthset/<id>.npy (float32 HxW pinhole Z-depth), labels.jsonl (station record + every readback),
#         groups.jsonl (one line per camera pose: vehicle/link readbacks, parked birds), camera_info_<world>.json
# One gz launch per distinct camera pose (pose baked into the SDF copy); bird_0 teleported per station, every
# actuation verified by /world/<w>/pose/info readback (fail-closed, exit 4). COMMITTED 125x110 plane, never extended.
source /root/ardu_ws/install/setup.bash   # before set -u: colcon's setup reads COLCON_TRACE unguarded
set -u
export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share"
REPO=/workspace/fieldguard; OUT=${OUT:-/tmp/depthset}; STATIONS=${1:-/tmp/stations.json}
POSE_TOL_M=0.05; YAW_TOL_DEG=0.5
PARK1="-200 -190 50"; PARK2="-200 -180 50"     # bird_1 / bird_2 parks — distinct from the F-group park (-200,-200,50)
mkdir -p "$OUT"; : > "$OUT/labels.jsonl"; : > "$OUT/groups.jsonl"
GZP=""
fail() { echo "[capture] FAIL: $*"; [ -n "$GZP" ] && kill "$GZP" 2>/dev/null; exit 4; }

gz_server_pids() {  # never `pgrep -f` (self-matches the calling shell); argv-positional like the committed harness
  ps -eo pid=,args= 2>/dev/null | awk '
    { prog = $2; sub(/.*\//, "", prog); second = $3; sub(/.*\//, "", second) }
    prog == "gz" && $3 == "sim"                              { print $1; next }
    prog ~ /^ruby[0-9.]*$/ && second == "gz" && $4 == "sim"  { print $1 }'
}
# ---- guards (design §5.2) ----
[ -n "$(gz_server_pids)" ] && fail "a gz server is already running: $(gz_server_pids | tr '\n' ' ')"
ps -eo args= | grep -qE '[d]rive_birds|[b]ird_drive' && fail "a bird driver is running — it would move the birds under the capture"
grep -q '<size>125.00 110.00</size>' "$REPO/sim/worlds/farmguard_field.sdf" || fail "committed world lacks the 125x110 field_ground"
grep -q 'gz-sim-physics-system' "$REPO/sim/worlds/farmguard_field.sdf" || fail "committed world lacks the physics system (set_pose needs it)"
[ -f "$STATIONS" ] || fail "no station file at $STATIONS"

# prints "x y z yaw_deg qx qy qz qw" or NOT_FOUND. proto text omits fields that are exactly 0 -> dict defaults.
pose_of() { # world entity
  timeout 20 gz topic -e -t "/world/$1/pose/info" -n 1 2>/dev/null | python3 -c '
import sys, re, math
name = sys.argv[1]; txt = sys.stdin.read()
for block in re.split(r"(?:^|\n)pose \{", txt)[1:]:
    if not re.search(r"name: \"%s\"\s" % re.escape(name), block): continue
    pos = re.search(r"position\s*\{([^}]*)\}", block); ori = re.search(r"orientation\s*\{([^}]*)\}", block)
    p = dict(re.findall(r"([xyz]):\s*(-?[0-9.eE+-]+)", pos.group(1))) if pos else {}
    o = dict(re.findall(r"([xyzw]):\s*(-?[0-9.eE+-]+)", ori.group(1))) if ori else {}
    x, y, z = (float(p.get(k, 0.0)) for k in "xyz")
    qx, qy, qz = (float(o.get(k, 0.0)) for k in "xyz"); qw = float(o.get("w", 0.0 if o else 1.0))
    yaw = math.degrees(math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)))
    print(x, y, z, yaw, qx, qy, qz, qw); break
else:
    print("NOT_FOUND")' "$2"
}
within() { # readback x y z [yaw]  -> exit 0 iff position within POSE_TOL_M (and yaw within YAW_TOL_DEG when given)
  python3 -c '
import sys
rb = sys.argv[1].split(); w = [float(v) for v in sys.argv[2:5]]; ptol, ytol = float(sys.argv[6]), float(sys.argv[7])
if rb[0] == "NOT_FOUND": sys.exit(1)
ok = max(abs(float(a) - b) for a, b in zip(rb[:3], w)) <= ptol
if sys.argv[5] != "-":
    d = (float(rb[3]) - float(sys.argv[5]) + 180.0) % 360.0 - 180.0
    ok = ok and abs(d) <= ytol
sys.exit(0 if ok else 1)' "$1" "$2" "$3" "$4" "${5:--}" "$POSE_TOL_M" "$YAW_TOL_DEG"
}
teleport() { # world entity x y z  -> echoes the verified readback
  local reply rb
  reply=$(gz service -s "/world/$1/set_pose" --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 2000 \
          --req "name: \"$2\", position: {x: $3, y: $4, z: $5}, orientation: {z: 0.0, w: 1.0}" 2>&1)
  case "$(printf '%s' "$reply" | tr -d '[:space:]')" in *data:true*) ;; *) fail "set_pose($2) refused: ${reply:-<empty>}";; esac
  sleep 2                                    # physics consumes the WorldPoseCmd; the render follows
  rb=$(pose_of "$1" "$2")
  within "$rb" "$3" "$4" "$5" || fail "$2 did not land at ($3, $4, $5); readback: $rb"
  echo "$rb"
}

# ---- group stations by camera pose (E N U roll pitch yaw) ----
python3 - "$STATIONS" <<'PY' > /tmp/depthset_groups.txt
import json, sys
d = json.load(open(sys.argv[1])); st = d["stations"] if isinstance(d, dict) else d
groups = {}
for s in st:
    rpy = s.get("cam_rpy_deg") or [0.0, 0.0, float(s.get("cam_yaw_deg", 0.0))]
    key = tuple(round(float(x), 3) for x in list(s["cam_enu"]) + list(rpy))
    groups.setdefault(key, []).append(s["id"])
for key, ids in groups.items():
    print(" ".join(str(v) for v in key), ",".join(ids))
PY
NST=$(python3 -c "import json;d=json.load(open('$STATIONS'));print(len(d['stations'] if isinstance(d,dict) else d))")
echo "[capture] $(wc -l < /tmp/depthset_groups.txt) camera groups, $NST stations, plane=COMMITTED 125x110, out=$OUT"

G=0
while read -r E N U R P YAW IDS; do
  G=$((G+1)); W="dset$G"; T0=$(date +%s)
  # ---- world copy: renamed world + topics, camera pose baked in, gravity zeroed; plane untouched (asserted) ----
  printf '%s\n' "/<world name=\"$W\">/a <gravity>0 0 0</gravity>" > /tmp/$W.sed
  sed -e "s/<world name=\"farmguard_field\">/<world name=\"$W\">/" -e "s|fg/sensor|$W/sensor|g" -e "s|fg/depth|$W/depth|g" \
      -e "s|<pose degrees=\"true\">0 0 0.195 0 0 90</pose>|<pose degrees=\"true\">$E $N $U $R $P $YAW</pose>|" \
      -f /tmp/$W.sed "$REPO/sim/worlds/farmguard_field.sdf" > /tmp/$W.sdf
  [ "$(grep -c '<gravity>0 0 0</gravity>' /tmp/$W.sdf)" = 1 ] || fail "group $G: gravity edit did not apply exactly once"
  [ "$(grep -c "<pose degrees=\"true\">$E $N $U $R $P $YAW</pose>" /tmp/$W.sdf)" = 1 ] || fail "group $G: vehicle pose edit did not apply exactly once"
  grep -q '<size>125.00 110.00</size>' /tmp/$W.sdf || fail "group $G: the copy's field_ground is not the committed 125x110 plane"
  grep -q '<size>425.00' /tmp/$W.sdf && fail "group $G: the copy carries the 425 m check-world extension"
  [ -n "$(gz_server_pids)" ] && fail "group $G: a gz server appeared before launch"
  gz sim -v1 -s -r --headless-rendering /tmp/$W.sdf > /tmp/$W.log 2>&1 &
  GZP=$!
  n=0; until timeout 5 gz topic -l 2>/dev/null | grep -q "^/$W/depth/image$"; do
    sleep 1; n=$((n+1)); kill -0 $GZP 2>/dev/null || fail "group $G: gz server died (see /tmp/$W.log)"
    [ $n -gt 120 ] && fail "group $G: /$W/depth/image never appeared"; done
  sleep 5
  # ---- §5.2 req 1: vehicle pose + yaw readback; camera LINK pose readback (parent-relative, recorded raw) ----
  VEH=$(pose_of "$W" iris_with_gimbal_ndvi)
  within "$VEH" "$E" "$N" "$U" "$YAW" || fail "group $G: vehicle is not parked at ($E,$N,$U yaw $YAW); readback: $VEH"
  LINK=$(pose_of "$W" fg_depth_mount)
  [ "$LINK" != "NOT_FOUND" ] || fail "group $G: no pose published for link fg_depth_mount"
  # ---- §5.2 req 2: park the other two birds out of every frustum, verified ----
  B1=$(teleport "$W" bird_1 $PARK1); B2=$(teleport "$W" bird_2 $PARK2)
  timeout 15 gz topic -e -t "/$W/depth/camera_info" -n 1 --json-output > "$OUT/camera_info_$W.json" 2>/dev/null \
    || fail "group $G: no camera_info"
  echo "[capture] group $G ($W) up in $(( $(date +%s)-T0 ))s: cam ($E,$N,$U) rpy ($R,$P,$YAW) | vehicle rb [$VEH] | link rb [$LINK] | stations: $IDS"
  python3 - <<PY >> "$OUT/groups.jsonl"
import json
print(json.dumps({"group": $G, "world": "$W", "cam_enu_cmd": [$E, $N, $U], "cam_rpy_deg_cmd": [$R, $P, $YAW],
  "vehicle_readback": "$VEH", "depth_link_readback_parent_relative": "$LINK", "bird_1_park_readback": "$B1",
  "bird_2_park_readback": "$B2", "camera_info": "camera_info_$W.json", "stations": "$IDS".split(","),
  "readback_format": "x y z yaw_deg qx qy qz qw (world frame for models; parent-relative for the link)"}))
PY
  IFS=',' read -ra IDARR <<< "$IDS"; PREV_SHA=""
  for ID in "${IDARR[@]}"; do
    read -r BE BN BU <<< "$(python3 -c "
import json; d=json.load(open('$STATIONS')); st={s['id']:s for s in (d['stations'] if isinstance(d,dict) else d)}
print(*st['$ID']['bird_enu'])")"
    BRB=$(teleport "$W" bird_0 "$BE" "$BN" "$BU")
    timeout 30 gz topic -e -t "/$W/depth/image" -n 1 --json-output > /tmp/dset_frame.json 2>/dev/null || fail "$ID: no depth frame within 30 s"
    LINE=$(SID="$ID" OUT="$OUT" STATIONS="$STATIONS" W="$W" GNUM="$G" VEH="$VEH" LINK="$LINK" BRB="$BRB" PREV_SHA="$PREV_SHA" python3 - <<'PY'
import os, sys, json, base64, hashlib, numpy as np
e = os.environ; sid = e["SID"]
d = json.load(open(e["STATIONS"])); st = {s["id"]: s for s in (d["stations"] if isinstance(d, dict) else d)}[sid]
m = json.load(open("/tmp/dset_frame.json")); w, h = int(m["width"]), int(m["height"])
buf = base64.b64decode(m["data"])
if len(buf) != w * h * 4: print(f"BAD frame byte length {len(buf)} != {w*h*4}"); sys.exit(4)
dep = np.frombuffer(buf, dtype="<f4").reshape(h, w)
np.save(f"{e['OUT']}/{sid}.npy", dep)
sha = hashlib.sha1(dep.tobytes()).hexdigest()
rb = [float(v) for v in e["BRB"].split()]
fin = np.isfinite(dep)
rec = {"id": sid, "station": st, "group": int(e["GNUM"]), "world": e["W"],
       "vehicle_readback": e["VEH"], "depth_link_readback_parent_relative": e["LINK"],
       "bird_0_readback": {"enu": rb[:3], "yaw_deg": rb[3]}, "teleport_verified": True,
       "frame": {"file": f"{sid}.npy", "shape": [h, w], "dtype": "float32", "sha1": sha,
                 "stamp": m.get("header", {}).get("stamp"), "finite_frac": float(fin.mean()),
                 "px_pos_inf": int(np.isposinf(dep).sum()), "px_neg_inf": int(np.isneginf(dep).sum()),
                 "min_finite_m": float(dep[fin].min()) if fin.any() else None,
                 "same_as_prev_station": bool(sha == e["PREV_SHA"]),
                 "units": "pinhole Z-depth m; +inf beyond far clip, -inf inside near clip"}}
open(f"{e['OUT']}/labels.jsonl", "a").write(json.dumps(rec) + "\n")
print(sha, f"{rec['frame']['finite_frac']:.3f}", rec["frame"]["min_finite_m"], rec["frame"]["same_as_prev_station"])
PY
) || fail "$ID: frame decode failed: $LINE"
    read -r SHA FF MINF SAME <<< "$LINE"; PREV_SHA=$SHA
    echo "[capture]   $ID bird ($BE,$BN,$BU) rb [$BRB] finite $FF min $MINF sha1 ${SHA:0:8}$([ "$SAME" = True ] && echo ' SAME-AS-PREV')"
  done
  kill $GZP; t0=$(date +%s); while kill -0 $GZP 2>/dev/null; do sleep 1; [ $(( $(date +%s)-t0 )) -gt 60 ] && { kill -9 $GZP; break; }; done
  GZP=""
  while timeout 5 gz topic -l 2>/dev/null | grep -q "^/$W/depth/image$"; do sleep 1; [ $(( $(date +%s)-t0 )) -gt 90 ] && break; done
  echo "[capture] group $G down ($(( $(date +%s)-t0 ))s teardown, $(( $(date +%s)-T0 ))s total)"
done < /tmp/depthset_groups.txt
python3 - "$OUT" "$NST" <<'PY'
import json, sys
out, nst = sys.argv[1], int(sys.argv[2])
recs = [json.loads(l) for l in open(f"{out}/labels.jsonl")]
shas = [r["frame"]["sha1"] for r in recs]; same = [r["id"] for r in recs if r["frame"]["same_as_prev_station"]]
print(f"[capture] DONE: {len(recs)}/{nst} frames in {out}; distinct sha1 {len(set(shas))}; same-as-previous-station: {same or 'none'}")
sys.exit(0 if len(recs) == nst and not same else 3)
PY
RC=$?; echo "CAPTURE_DONE rc=$RC"; exit $RC
