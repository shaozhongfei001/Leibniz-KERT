# KERT Python Core 容器镜像（M2.7）
#
# 设计要点：
# - 多阶段构建：builder 装依赖，runtime 只带运行所需，缩小攻击面与体积
# - 非 root 运行：容器逃逸后权限受限
# - 不含凭据：API Key 一律经环境变量或挂载的配置文件注入，绝不 COPY 进镜像
# - 工作区经 volume 挂载：知识资产是权威源，不应随镜像不可变化
# - TLS 由外层网关终止（见 KERT_HYBRID_DEPLOYMENT_AND_OPERATIONS §2）

# ---------- builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 可选：pip 索引源。**默认留空 ⇒ 行为与原来完全一致**（用 pip 默认 PyPI）。
# 在到 PyPI 慢/受限的构建环境里传入可避免拉大包（pyarrow 等）超时导致
# `Could not find a version ... (from versions: none)`：
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple make deploy-build
# 由 compose 的 build.args 透传（见 deploy/docker-compose.yml）。
ARG PIP_INDEX_URL=""

# 先装依赖再拷源码：依赖层可被缓存复用，源码改动不触发重装
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install ${PIP_INDEX_URL:+--index-url="$PIP_INDEX_URL"} --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install ${PIP_INDEX_URL:+--index-url="$PIP_INDEX_URL"} ".[api]"

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# 可选：Debian apt 源根（**默认留空 ⇒ 行为与原来完全一致**，用 deb.debian.org）。
# 在到 deb.debian.org 很慢的环境里传入可显著缩短构建（实测本机 541s 才下 ~500KB）：
#   APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn make deploy-build
# 由 compose 的 build.args 透传（见 deploy/docker-compose.yml）。
ARG APT_MIRROR=""

# 运行期不需要编译工具链，仅保留 curl 供健康检查使用
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/|$APT_MIRROR/|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 kert \
    && useradd --uid 10001 --gid kert --create-home --shell /usr/sbin/nologin kert

COPY --from=builder /opt/venv /opt/venv
COPY --chown=kert:kert src /app/src
COPY --chown=kert:kert scripts /app/scripts
COPY --chown=kert:kert skills /app/skills
# 外部 Skill 包（bank-front-*）。镜像若不带上它，容器内 bank-front 技能会全部不可用
# （运行时表现为 UNKNOWN_SKILL）——见 evidence/kert-e2e-ci/TASK_PACKAGE_D-E2E-01.md。
COPY --chown=kert:kert examples /app/examples

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    KERT_SKILL_PACKAGES=/app/examples/bank-front-skills \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KERT_PROFILE=prod \
    KERT_BIND_HOST=0.0.0.0 \
    KERT_WORKSPACE=/data/workspace

# 工作区与备份挂载点，属主为运行用户
RUN mkdir -p /data/workspace /data/backups \
    && chown -R kert:kert /data

WORKDIR /app
USER kert
EXPOSE 8106

# 就绪探针用 /readyz：未就绪返回 503，容器编排据此摘除流量而不重启
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8106/livez || exit 1

ENTRYPOINT ["python", "/app/scripts/serve_skill_service.py"]
CMD ["--host", "0.0.0.0", "--port", "8106", "--workspace", "/data/workspace"]
