# Perception & ML Engineer — Memory Index

- [NDVI-vs-RGB spike (ADR-003)](project_ndvi_rgb_spike.md) — framing DECIDED on synthetic (0.445 is the bar); criterion 3 still OPEN, now on label timing
- [Bird label timing](project_bird_label_timing.md) — the render lags labels 0.12-0.81 s; only the driver's applied-pose log makes a real clip scoreable
- [Eval harness core](reference_eval_harness.md) — eval/ pipeline + score.py's TWO refusal guards (denominator, label provenance)
