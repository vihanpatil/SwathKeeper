---
name: host-quiet-is-a-flight-gate
description: Check for other Docker containers / heavy host load BEFORE and AFTER every throughput flight — a concurrent Supabase stack halved both camera bands and voided a flight on 2026-08-22
metadata:
  type: feedback
---

Before starting any throughput/recording flight, check what else is running on the host
(`docker ps`), and check again after it lands. If anything heavy started during the flight window,
the flight is **VOID for absolute throughput** — report it as void, do not interpret the numbers,
and do not let the abort gate blame the code.

**Why:** on 2026-08-22 the F5 instrumented-baseline flight came in at `red_frames/camera_info_frames`
= 16.8 % against F4's 31.09 % — far enough below to trip the round's abort gate, whose stated
reading was "the counters themselves cost throughput; thin the set and re-fly." That reading was
wrong. `docker inspect` showed a 12-container Supabase stack starting at 03:17:48-03:20:10 UTC,
**68 seconds into** the 03:16:40-03:21:43 flight, sharing the same 8-CPU / 9.4 GB Docker Desktop VM
with a software-rendered (llvmpipe) Gazebo. The runbook's own performance rule already says a busy
host makes the camera pipeline drop frames per-band — this is that rule, measured.

**UPDATE 2026-08-22, and it matters:** the re-fly on a *quiet* host (sampled every 15 s throughout:
mostly 5-30 % of one core, one 81 % sample) came back at **17.31 %** — reproducing the 16.81 %.
So host load explains the F5a *startup burst* but does NOT explain the 2x shortfall against F4's
31.09 %. Something changed between 2026-08-21 (F1-F4) and 2026-08-22 that halves both image bands
and is still unattributed. Do not close this as "it was just the host".

**Sampling gotcha:** a single `docker stats --no-stream` is not evidence of a quiet host. One
snapshot read 41 % total; sampling three times 8 s apart caught bursts of 267 % and 352 % (realtime
160 %, analytics 219 %). Sample repeatedly, or better, log load *during* the flight so the flight
self-certifies.

**How to apply:**
- The tell that it is the HOST and not your change: **both bands degrade together and by the same
  factor.** F5 lost red 31.1 %→16.8 % (0.54x) *and* NIR 58.9 %→29.3 % (0.50x), while the NIR image
  path had received nothing but a deque append. A code cost lands asymmetrically on the path you
  touched; host load halves everything at once.
- `camera_info_frames` being in band (690 vs the 692-698 control) does **not** clear a flight. It
  only proves the exposure window and the render tick were the same; it says nothing about
  transport contention. Host-quiet is a second, independent precondition.
- RTF is also not a tell — F5's RTF was a normal ~0.545 while transport delivered half.
- Do **not** stop the user's other containers to make room. They are someone else's running work
  (a Postgres among them). Report the blocker and let a human quiet the host.
- Ratio-based results still survive a loaded flight (see
  [[throughput-instrumentation-results]]) — counters that compare two things measured in the same
  flight are fine; absolute yields are not.
