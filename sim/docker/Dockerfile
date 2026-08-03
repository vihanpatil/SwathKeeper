# FieldGuard — Week 1 starter sim image.
#
# This is intentionally a "get it green" sketch, not a hardened/CI image. It gets ROS 2 Humble +
# Gazebo Harmonic + the ArduPilot toolchain installed and buildable inside one container so the
# Week 1 bringup checklist in docs/WEEK1_BRINGUP.md can run end to end on macOS via Docker Desktop.
#
# devops-reliability-engineer owns turning this into the production image (multi-stage build,
# non-root user, exact commit SHAs baked in rather than resolved at container-start time, CI
# wiring) once Week 1 is confirmed green and the versions in CLAUDE.md are locked.
#
# Pinned versions (see CLAUDE.md "Pinned versions" for the human-confirmed source of truth):
#   Ubuntu 22.04 (jammy) | ROS 2 Humble | Gazebo Harmonic (GZ_VERSION=harmonic)
#   ardupilot_gz@main | ardupilot_gazebo@ros2 | ardupilot@master (pin exact SHA post-Week-1)
#
# Build (from repo root):
#   docker build -t fieldguard-sim:week1 -f sim/docker/Dockerfile .
# On Apple Silicon, if arm64 package resolution breaks (see WEEK1_BRINGUP.md gotcha #2), retry with:
#   docker build --platform linux/amd64 -t fieldguard-sim:week1 -f sim/docker/Dockerfile .

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV GZ_VERSION=harmonic
ENV ROS_DISTRO=humble

# --- Base tools -------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 lsb-release wget git python3-pip \
        software-properties-common locales sudo ca-certificates \
    && locale-gen en_US.UTF-8 \
    && add-apt-repository universe \
    && rm -rf /var/lib/apt/lists/*

# --- ROS 2 Humble ------------------------------------------------------------
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
        http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/ros2.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-desktop \
        python3-colcon-common-extensions \
        python3-rosdep \
        python3-vcstool \
    && rm -rf /var/lib/apt/lists/* \
    && rosdep init || true

# --- Gazebo Harmonic ---------------------------------------------------------
RUN wget https://packages.osrfoundation.org/gazebo.gpg -O /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
        http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
        | tee /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        gz-harmonic \
        libgz-sim8-dev \
        rapidjson-dev \
        libopencv-dev \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-libav \
        gstreamer1.0-gl \
    && rm -rf /var/lib/apt/lists/*

# --- OSRF Gazebo rosdep rules -------------------------------------------------
# Lets `rosdep install` (run in WEEK1_BRINGUP §3) resolve Harmonic's gz-* keys — gz-sim8, gz-msgs10,
# gz-plugin2, gz-cmake3, gz-transport13, sdformat14, ... — to the installed gz-harmonic packages,
# driven by GZ_VERSION. Without it rosdep can't map those keys and aborts, installing nothing.
RUN wget -q https://raw.githubusercontent.com/osrf/osrf-rosdep/master/gz/00-gazebo.list \
        -O /etc/ros/rosdep/sources.list.d/00-gazebo.list

# --- ArduPilot + ros_gz build prerequisites ----------------------------------
# libgflags-dev: ros_gz_sim #includes <gflags/gflags.h> and links libgflags at runtime; rosdep
# doesn't reliably pull it, so bake it in.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ccache g++ gawk python3-dev python3-pexpect \
        python3-setuptools python3-numpy python3-pyparsing python3-psutil \
        rsync libgflags-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Micro-XRCE-DDS-Gen (ArduPilot AP_DDS code generator) --------------------
# ArduPilot SITL (AP_DDS / ROS 2 enabled on master) needs `microxrceddsgen` on PATH, or waf configure
# fails with "Could not find the program ['microxrceddsgen']". Branch v4.7.0 aligns with firmware 4.7+.
RUN apt-get update && apt-get install -y --no-install-recommends default-jdk \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --recurse-submodules --branch v4.7.0 \
        https://github.com/ardupilot/Micro-XRCE-DDS-Gen.git /opt/Micro-XRCE-DDS-Gen \
    && cd /opt/Micro-XRCE-DDS-Gen && ./gradlew assemble
ENV PATH="/opt/Micro-XRCE-DDS-Gen/scripts:${PATH}"

WORKDIR /root

# NOTE: the ros2_gz.repos import + colcon build + ArduPilot ./waf build are deliberately NOT baked
# into this image yet — do them interactively per docs/WEEK1_BRINGUP.md §3-4 against a named volume
# (/root/ardu_ws) so first-run failures are visible and fixable step by step. Once Week 1 is green,
# devops-reliability-engineer should bake the resolved SHAs + build into this image for CI.

RUN echo 'source /opt/ros/humble/setup.bash' >> /root/.bashrc \
 && echo 'export GZ_VERSION=harmonic'        >> /root/.bashrc

CMD ["/bin/bash"]
