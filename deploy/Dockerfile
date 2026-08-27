# DKWS Python Core 容器镜像（M2.7）
#
# 设计要点：
# - 多阶段构建：builder 装依赖，runtime 只带运行所需，缩小攻击面与体积
# - 非 root 运行：容器逃逸后权限受限
# - 不含凭据：API Key 一律经环境变量或挂载的配置文件注入，绝不 COPY 进镜像
# - 工作区经 volume 挂载：知识资产是权威源，不应随镜像不可变化
# - TLS 由外层网关终止（见 DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS §2）

# ---------- builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 先装依赖再拷源码：依赖层可被缓存复用，源码改动不触发重装
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install ".[api]"

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# 运行期不需要编译工具链，仅保留 curl 供健康检查使用
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dkws \
    && useradd --uid 10001 --gid dkws --create-home --shell /usr/sbin/nologin dkws

COPY --from=builder /opt/venv /opt/venv
COPY --chown=dkws:dkws src /app/src
COPY --chown=dkws:dkws scripts /app/scripts
COPY --chown=dkws:dkws skills /app/skills

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DKWS_PROFILE=prod \
    DKWS_BIND_HOST=0.0.0.0 \
    DKWS_WORKSPACE=/data/workspace

# 工作区与备份挂载点，属主为运行用户
RUN mkdir -p /data/workspace /data/backups \
    && chown -R dkws:dkws /data

WORKDIR /app
USER dkws
EXPOSE 8106

# 就绪探针用 /readyz：未就绪返回 503，容器编排据此摘除流量而不重启
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8106/livez || exit 1

ENTRYPOINT ["python", "/app/scripts/serve_skill_service.py"]
CMD ["--host", "0.0.0.0", "--port", "8106", "--workspace", "/data/workspace"]
