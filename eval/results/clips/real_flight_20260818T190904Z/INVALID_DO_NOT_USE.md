# INVALID CLIP — recorded with the horizon-facing mount (2026-08-18)

The ADR-007 sensor mount rpy aimed the camera at the horizon (upside-down) from the day it was
authored (Gazebo cameras look along sensor +X; the rpy was derived under a pinhole Z-forward
mental model). Every frame in this clip images the wrong scene geometry. Found via the tree-position
check; fixed in config/ndvi_camera.json + verified by scripts/verify_mount_geometry.sh (canopy
centroid within 2.2 px of the georef prediction). Do not stitch or eval against this clip.
