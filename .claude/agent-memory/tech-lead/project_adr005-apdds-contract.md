---
name: adr005-apdds-contract
description: ADR-005 decided — AP_DDS enabled via explicit param file; /ap/* contract locked to pinned SHA, live-bridge confirmation still owed
metadata:
  type: project
---

ADR-005 (enable AP_DDS + lock the /ap/* topic/service/frame contract) is **ACCEPTED,
confirmation-pending** as of 2026-08-04. Decision: enable AP_DDS via explicit param file
(`config/sitl_params/dds_udp.parm`: DDS_ENABLE=1, DDS_UDP_PORT=2019) loaded via
`sim_vehicle.py --add-param-file`; keep DDS_USE_NS=0 (flat `/ap/<name>`); lock the full topic/service
map, verified from AP_DDS source at pinned ArduPilot commit
`9895756d874ec9128d50918f6747a83706f4e221` (every `#if AP_DDS_*_ENABLED` gate checked, not docs).

**Three non-obvious findings baked into the contract (interview gold, don't lose):** (1)
/ap/pose/filtered and /ap/twist/filtered are frame-mislabeled — frame_id=base_link but content is
world-ENU; treat content not frame_id as authoritative. (2) subscriber is bare /clock, NOT /ap/clock
(absolute-path special case). (3) DDS_ENABLE compiled default is untrustworthy because a persisted
eeprom.bin overrides it — hence the explicit param file.

**How to apply:** the /ap/* contract is the stable interface Week 3-4 perception/planner nodes code
against — treat it as locked, re-verify only if the pinned SHA is bumped. Open follow-up: the contract
is source-verified but the live bridge only comes up in the human Docker run, so `ros2 topic list` /
`ros2 topic hz` confirmation against running SITL+micro-ROS-agent is still owed before fully validated.

**Coordination:** two confirmation-pending items are both gated on the human Docker run — ADR-005's
live `ros2 topic` check and [[adr003-ndvi-detection]]'s real-Gazebo-render spike re-run. Batch both
into the same Docker session so neither slips.
