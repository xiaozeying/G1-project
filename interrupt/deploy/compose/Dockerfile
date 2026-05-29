FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INTERRUPT_RUNTIME_ROOT=/opt/interrupt-runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    curl \
    ffmpeg \
    git \
    gstreamer1.0-tools \
    iproute2 \
    libasound2 \
    libasound2-data \
    libasound2-dev \
    libportaudio2 \
    libpulse0 \
    libv4l-0 \
    libv4l-dev \
    portaudio19-dev \
    pulseaudio-utils \
    v4l-utils \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/interrupt-build
COPY interrupt/requirements.txt ./requirements.txt

RUN python -m venv /opt/interrupt-venv \
  && /opt/interrupt-venv/bin/pip install --upgrade pip setuptools wheel \
  && /opt/interrupt-venv/bin/pip install -r ./requirements.txt

ENV PATH="/opt/interrupt-venv/bin:${PATH}"

WORKDIR /workspace
CMD ["bash"]
