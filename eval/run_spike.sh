#!/usr/bin/env bash
# One-shot ADR-003 spike run: label GT -> run both baselines -> score + decide.
# Params mirror eval/scenarios/spike_birds.yaml. Assumes the clip already exists
# (regenerate: python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42).
# PYTHON env var lets CI/devs point at the venv with numpy+scipy.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

PYTHON="${PYTHON:-python3}"
CLIP="${CLIP:-sim/spike/out/spike_seed42}"
RESULTS="${RESULTS:-eval/results}"
mkdir -p "$RESULTS"

"$PYTHON" eval/label_from_sim.py --clip "$CLIP" --out "$RESULTS/ground_truth.json" \
  --verify --overlay "$RESULTS/overlays"
"$PYTHON" eval/baseline_ndvi.py --clip "$CLIP" --out "$RESULTS/detections_ndvi.json"
"$PYTHON" eval/baseline_rgb.py  --clip "$CLIP" --out "$RESULTS/detections_rgb.json"
"$PYTHON" eval/score.py --ground-truth "$RESULTS/ground_truth.json" \
  --detections "$RESULTS/detections_ndvi.json" "$RESULTS/detections_rgb.json" \
  --iou 0.3 --out "$RESULTS/spike_scores.json"
