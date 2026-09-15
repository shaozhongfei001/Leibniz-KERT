"""P24 验收专用：以真实工作区启动 Leibniz-KERT HTTP 服务（含 SP-15 技能注册）。

DKWS（8106）版本的 skills.py 未包含 SP-15，导致后端 product-recommendation
fail-closed。本脚本以 Leibniz-KERT 源码 + 同一工作区启动到 8107。
"""
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kert.api.server import create_app  # noqa: E402

WORKSPACE = Path("/home/szf/dev/deepseek_harness/data_knowledge_ws/demo_workspace")

if __name__ == "__main__":
    app = create_app(WORKSPACE, service_id="product_knowledge")
    uvicorn.run(app, host="127.0.0.1", port=8107, log_level="info")
