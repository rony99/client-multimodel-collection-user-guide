FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip git curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --break-system-packages \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    pytest==8.4.1

RUN mkdir -p /app/source
COPY . /app/source
WORKDIR /app/source

RUN python3 -m pip install --no-cache-dir --break-system-packages \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -e ".[dev]"

RUN rm -rf /root/.claude /root/.claude.json && \
    find /app \( -path '*/.claude' -o -name '.claude.json' \) -prune -exec rm -rf {} + 2>/dev/null || true

RUN ln -sf /usr/bin/python3 /usr/bin/python

CMD ["bash"]
