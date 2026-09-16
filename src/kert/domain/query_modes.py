"""检索 / 图谱查询的**模式与方向**值域（三个合同 `enum`、四个字段）：单一命名源
（D-28 层 2 第六片）。

**为什么这处该立源**（自问"是不是外部结论 / 推模式入参的如实镜像"）：**不是**（该立源）。
三个词表的值虽由**调用方传入**，但实现侧**拥有其闭集**：
`application.services.KnowledgeService.search / graph` 都做**闭集校验**（不在集合内 ⇒ 具名拒绝），
随后**按名分支**（是否走向量/混合、是否展开闭包、Cypher 用哪个箭头、ranking policy 取哪个版本）
⇒ 改名会**静默**改变行为或产出。这与 D-43（`GateAuditRequest.decision` 纯透传：零校验、零分支）
**正相反** —— 那条判"只登记事实"，这条判"该立源"。

三个词表**互不通用，禁止合并**（两个 schema 里都有名为 `mode` 的字段，但值域不同）：

- :data:`SEARCH_MODES` —— `SearchRequest.mode`；
- :data:`GRAPH_DIRECTIONS` —— `GraphQueryRequest.direction`；
- :data:`GRAPH_MODES` —— `GraphQueryRequest.mode`。

⚠ **表外同名异域（不得误合并）**：`src/kert/cli/main.py` 另有 `--mode fast|full`
（无关命令的开关；值域与本模块**无交集**）。

⚠ **已知残留（E-13）**：`src/kert/cli/main.py` 含他人在途改动 ⇒ 本片不碰它，
其 3 处**默认值字面量**（`--mode neighbor` / `--mode FULLTEXT` / graph `--mode`）为**显式登记的残留**，
见 `tests/unit/test_query_modes_single_source.py`（该文件的防复发断言**显式限定范围**并登记此残留）。
"""

from __future__ import annotations

#: 检索模式（`SearchRequest.mode`）：顺序 = 合同 `enum` 顺序。
SEARCH_MODES: tuple[str, ...] = ("FULLTEXT", "VECTOR", "HYBRID")
#: 具名常量：生产者/消费者**不得**再散落字面量。
SEARCH_MODE_FULLTEXT, SEARCH_MODE_VECTOR, SEARCH_MODE_HYBRID = SEARCH_MODES

#: 图关系方向（`GraphQueryRequest.direction`）：顺序 = 合同 `enum` 顺序。
GRAPH_DIRECTIONS: tuple[str, ...] = ("OUT", "IN", "BOTH")
DIRECTION_OUT, DIRECTION_IN, DIRECTION_BOTH = GRAPH_DIRECTIONS

#: 图遍历模式（`GraphQueryRequest.mode`）：顺序 = 合同 `enum` 顺序。
GRAPH_MODES: tuple[str, ...] = ("neighbor", "closure", "paths")
GRAPH_MODE_NEIGHBOR, GRAPH_MODE_CLOSURE, GRAPH_MODE_PATHS = GRAPH_MODES

#: 方向 → **Cypher 关系箭头**（该域到后端语法的投影表）：两处查表共用一张，
#: 键直接取自 :data:`GRAPH_DIRECTIONS` ⇒ 改名自动跟随、缺键即 `KeyError`（不再有第二份字面量地图）。
GRAPH_CYPHER_ARROWS: dict[str, str] = {
    DIRECTION_OUT: "->",
    DIRECTION_IN: "<-",
    DIRECTION_BOTH: "-",
}
