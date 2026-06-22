"""Genesis 建板 · 生态位推断与标的池生成 v2.0（LLM 引擎）。

[Ref: 37_Z0-Genesis建板生态位推断与标的池生成.md v2.0 · 38_AI算力交付链BOM白名单.md]
1. BOM 白名单定义产业链范围 → LLM 在白名单内映射标的
2. 5 因子打分 (moat/growth/profit/localize/policy_bond) + 可审计证据链
3. 排除规则 (ST/立案/商誉暴雷/审计非标) 一票否决
4. A 股概念标签仅用于 policy_bond 加分，不限制候选范围
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from jinja2 import Template

logger = logging.getLogger(__name__)

# v5.2 异步后台任务存储（内存字典）
_TASKS: dict[str, dict[str, Any]] = {}
_TASK_LOCK = asyncio.Lock()
_TASK_TTL_SECONDS = 600  # 单任务 10 分钟后自动清理

# ── BOM 白名单（在 Prompt 中作为硬约束注入 · 权威版本见 38_AI算力交付链BOM白名单.md） ──
_BOM_WHITELIST_NODES = [
    ("ai_chip", "AI 训练/推理芯片", "核心"),
    ("optical_interconnect", "高速光互连 (光模块/光芯片)", "核心"),
    ("hbm_storage", "高带宽存储 (HBM/DRAM)", "重要"),
    ("high_speed_pcb", "高速 PCB / IC 载板", "重要"),
    ("ai_server", "AI 服务器与系统集成", "核心"),
    ("thermal_cooling", "数据中心散热/液冷", "配套"),
    ("ai_power", "AI 专用电源与供电", "配套"),
    ("advanced_packaging", "先进封装与 Chiplet", "重要"),
    ("switch_chip", "交换芯片与高速网络", "重要"),
    ("ai_fpga", "FPGA / 协处理器", "重要"),
    ("llm_platform", "大语言模型平台", "核心"),
    ("ai_dev_tools", "AI 开发工具链与框架", "配套"),
    ("ai_security", "AI 安全与治理", "配套"),
    ("training_data", "高质量训练数据集", "重要"),
    ("data_labeling", "数据标注与治理", "配套"),
]

_BOM_NODES_PROMPT = "\n".join(
    f"- [{tier}] {name} (node_id: {nid})"
    for nid, name, tier in _BOM_WHITELIST_NODES
)


# ── BOM 节点生成 System Prompt（v4.0 · 通用赛道 BOM 分解 · 强化上下游覆盖） ──
_BOM_GENERATION_SYSTEM_PROMPT = """你是一个中国 A 股产业链深度分解专家。你的任务是：

给定一个政策重点赛道（sector）及其关联的 A 股概念板块列表，将该赛道的产业链**全方位**分解为 BOM（Bill of Materials）节点清单。

## 产业链结构要求

你必须从以下四个层次全面覆盖该赛道：

1. **上游 — 基础层**：原材料、设备、工具、IP/EDA、晶圆代工、封装测试、能源等基础支撑环节
2. **中游 — 核心制造**：芯片/核心器件设计、模组/系统集成、平台/OS、中间件等
3. **下游 — 产品与应用**：终端产品、解决方案、运营服务、场景应用等
4. **服务与配套层**：运维、调度、安全、数据、培训、认证、金融等配套服务

每个层次至少应包含 2 个以上节点。全部节点个数应在 23-28 个之间。

## 输出要求

返回一个 JSON 对象，包含以下字段：

### 1. bom_nodes（数组，每个元素包含）
- node_id: 英文短标识（如 "ai_chip"、"data_center_cooling"）
- name: 中文节点名称（如 "AI 训练/推理芯片"、"数据中心散热/液冷"）
- tier: 该节点在产业链中的重要性等级，必须是以下之一：
  - "核心" — 该赛道最不可或缺、价值最高、壁垒最高的环节（至少 3 个）
  - "重要" — 支撑性环节，技术或产能瓶颈，有国产替代空间（至少 4 个）
  - "配套" — 辅助/服务型环节
- layer: 可选字段，仅 **AI算力/半导体/数字科技** 赛道填写。参考 NVIDIA 五层蛋糕架构标注节点所属价值层：
  - "L1" — 基础设施层：电力/数据中心/散热/网络骨干
  - "L2" — 硬件层：AI芯片/HBM/光模块/交换机/服务器/铜互联
  - "L3" — 平台软件层：CUDA生态/k8s/大模型训推平台/LLMOps
  - "L4" — 模型层：基座大模型/推理优化/Token服务/多模态
  - "L5" — 应用层：AI Agent/数字人/企业AI/行业解决方案
  非科技赛道统一填 `null`
- rationale: 简要说明为何此节点属于该 tier（1-2 句话，结合国产替代紧迫度、市场增速、技术壁垒）
- score: 该节点整体的投资价值评分（0-100 整数），综合考虑以下 5 个维度
  - 政策紧迫度：当前政策对该环节的扶持力度
  - 国产替代空间：进口依赖程度 / 被卡脖子风险
  - 市场规模增速：下游需求 CAGR
  - 技术壁垒：进入门槛 / 护城河
  - 盈利可预见性：毛利率 / 订单确定性

### 2. top_recommendations（数组，建议用户优先选择的 node_id 列表，推荐 3-8 个）
- 基于各节点 score 和产业链关键度，推荐最应纳入分析范围的节点
- 必须是来自 bom_nodes 的有效 node_id

### 3. industry_summary（字符串）
- 该赛道的产业链概况描述（2-4 句话，含市场空间和核心驱动因素）

## 约束
1. **必须覆盖上游/中游/下游/服务配套全部四个层次**，不能只聚焦某个单一环节
2. 生成的节点应覆盖该赛道的完整产业链条，但聚焦于 A 股有可映射标的的环节
3. 节点数量 23-28 个，做到大而全
4. tier 标注要严谨：至少 3 个"核心"节点、至少 4 个"重要"节点
5. layer 字段仅对 AI算力/半导体/数字科技等科技赛道填写 L1-L5，非科技赛道统一 `null`，不臆造
6. score 要基于真实的政策导向和产业现状，具有区分度
7. top_recommendations 必须是 bom_nodes 中存在的 node_id
8. 每个 bom_node 的 name 不应与同赛道其他节点近似重复（如"AI芯片"和"AI推理芯片"合并为一个）
9. 【强制】你的回答必须是**纯 JSON 对象**，以 `{` 开头、以 `}` 结尾。不允许有任何解释性文字、思考过程、描述性句子、markdown 标记或多余标点出现在 JSON 之前或之后。

⚠️ 违反此规则的后果：整个输出被视为无效，将触发重试，且浪费一次 API 调用。请直接输出如下格式，**不要多说一个字**：

```json
{"bom_nodes": [...], "top_recommendations": [...], "industry_summary": "..."}
```

## 参考分行业举例（含 layer 标签参考）

- **AI 算力赛道（参考 NVIDIA 五层蛋糕架构）**：
  - L1（基础设施层）：智算中心建设/电力/液冷散热/数据中心光互联
  - L2（硬件层）：AI芯片/HBM/光模块/高速交换机/服务器/铜互联
  - L3（平台软件层）：CUDA生态/大模型训推平台/k8s调度/LLMOps
  - L4（模型层）：基座大模型/推理优化/Token服务/多模态
  - L5（应用层）：AI Agent/数字人/企业AI/行业解决方案
  以上节点须精确标注 `layer` 为 L1 ~ L5，精准映射五层价值堆栈
- **新能源赛道（layer: null）**：上游含锂矿/正负极/隔膜/电解液，中游含电池/逆变器/电机电控，下游含整车/储能/充电桩，配套含回收/碳交易/检测
- **半导体赛道（layer: null）**：上游含硅片/光刻胶/气体/设备/EDA，中游含设计/制造/封测/IP，下游含消费电子/汽车/工业/通信，配套含分销/测试服务
- **消费赛道（layer: null）**：上游含原料/包装/代工，中游含品牌/渠道/物流，下游含零售/电商/出海，配套含营销/数据/支付"""


# ── System Prompt 构建函数（v3.0 · 支持动态 BOM 节点） ──

def _build_bom_prompt(nodes: list[tuple[str, str, str]]) -> str:
    """将 BOM 节点列表格式化为 Prompt 文本段。"""
    if not nodes:
        return "（暂无 BOM 白名单）"
    return "\n".join(f"- [{tier}] {name} (node_id: {nid})" for nid, name, tier in nodes)


def _build_system_prompt(bom_nodes: list[tuple[str, str, str]]) -> str:
    """根据传入的 BOM 节点列表构建 System Prompt。"""
    bom_text = _build_bom_prompt(bom_nodes)
    return f"""你是一个中国 A 股产业生态分析专家。你的任务是：
给定一个政策重点赛道和用户选定的 A 股概念板块，根据下发的产业链 BOM 白名单，
在每个节点范围内生成最具 3-5 年成长潜力的 A 股标的池。

## BOM 白名单（你必须在此范围内映射标的，不得擅自增删）

{bom_text}

## 标的选择与评分标准

对每个 BOM 节点中的每只标的，必须按以下 5 个因子逐项打分，每个因子附带至少 2 条可验证证据：

### 1. moat（壁垒 · 权重 0.30）
评估：市占率 / 技术壁垒 / 客户锁定 / 规模效应
证据要求：至少 2 条 —— 如"全球 800G 光模块市场份额 >40%""英伟达核心供应商，客户认证周期 12-18 个月"

### 2. growth（成长性 · 权重 0.25）
评估：赛道 CAGR / 产能扩张 / 政策直接加速度
证据要求：至少 2 条 —— 如"下游 AI 数据中心 Capex CAGR >30%""公司公告产能扩建 2027 年翻倍"

### 3. profit（盈利质量 · 权重 0.20）
评估：毛利率趋势 / ROE / 经营现金流/净利润
证据要求：至少 2 条 —— 如"毛利率 >30% 且逐年上升""ROE >15%"

### 4. localize（国产替代紧迫度 · 权重 0.15）
评估：进口依赖程度 / 出口管制状态 / 国产化率
证据要求：至少 2 条 —— 如"被列入美国出口管制实体清单""国产化率 <20%"

### 5. policy_bond（政策直接映射 · 加分项）
评估：标的所属 A 股概念标签是否在用户选定的概念列表中
取值：有匹配 → 加 0.2；无匹配 → 0

### 总分公式
composite = moat × 0.30 + growth × 0.25 + profit × 0.20 + localize × 0.15 + policy_bond

## 排除规则（一票否决）

以下任意一条触发 → 该标的从候选池中排除，记录到 excluded_stocks：
1. ST / *ST 标注
2. 近 12 个月被证监会立案调查
3. 商誉 / 净资产 > 50%
4. 近 2 年审计意见为「非标准无保留」

## 硬约束
1. 你必须在 BOM 白名单所列节点范围内进行标的映射。不得擅自新增或删除。
2. 如果你认为白名单外有值得考虑的新节点，写入 suggested_additions 字段。
3. 每个标的必须输出完整的 scoring_detail（含全部 5 个因子 + composite）。
4. 每个因子必须附带至少 2 条可验证的 evidence。
5. 概念标签信息仅用于 policy_bond 加分判断，不可用于限制候选范围。
6. 排除规则检查必须逐项执行，结果记录在 exclusion_check。
7. 输出纯 JSON，不要额外解释。"""

# ── User Prompt 模板 ──
_ECOSYSTEM_PROMPT_TPL = Template("""## 赛道信息

- 赛道名称：{{ sector_display_name }}
- 政策推动力评分（政策动量）：{{ policy_momentum }}/1.0
- 商业轨迹评分：{{ commercial_trajectory }}/1.0
- 资本引力评分：{{ capital_gravity }}/1.0
- 落地质量评分：{{ implementation_quality }}/1.0
- 综合投资级评分（Z0+）：{{ z0_plus_score }}/1.0
- 增长阶段：{{ growth_stage }}
- 利润池特征：{{ profit_pool }}
- 估值层级：{{ valuation_tier }}
- 机构资金流向：{{ institutional_flow }}
- 政策阶段：{{ policy_phase }}
- 落地力度：{{ imp_strength }}
- 政策加速度：{{ policy_acceleration }}
- 制度变化次数：{{ regime_change_count }}

## 用户选定的 A 股概念板块（仅用于 policy_bond 加分判断）

{% for concept in selected_concepts %}
### {{ concept.sub_name }}
- 关联政策文档数：{{ concept.doc_count }}
- 平均政策得分：{{ "%.1f" | format(concept.avg_composite) }}/100
{% if concept.evidence_quotes %}
- 政策证据引述（最近3条）：
{% for eq in concept.evidence_quotes[:3] %}
  · 「{{ eq.get('excerpt', '')[:200] }}」
{% endfor %}
{% endif %}
{% endfor %}

## 任务

### 1. 推断产业生态位拓扑
分析该赛道的产业生态全景，划分为 4 层：
- 上游：原材料/核心技术/基础设施
- 中游：核心制造/平台/系统集成
- 下游：终端产品/应用/服务
- 服务层：配套服务/软件/数据/渠道

每层写出 1-3 句该层在赛道中的角色描述。

### 2. 为每个 BOM 节点生成标的池
对 BOM 白名单中的每个节点：
- 确定该节点在生态位中的位置（上游/中游/下游/服务层）
- 列出该节点下最具 3-5 年成长潜力的 3-8 个 A 股标的
- 每个标的必须附带完整 scoring_detail 和 exclusion_check

### 3. 输出 JSON Schema（严格遵循）

```json
{
  "sector": "{{ sector_display_name }}",
  "ecosystem_topology": {
    "upstream": { "role": "该层角色描述", "key_segments": ["细分1", "细分2"] },
    "midstream": { "role": "", "key_segments": [] },
    "downstream": { "role": "", "key_segments": [] },
    "service_layer": { "role": "", "key_segments": [] }
  },
  "investment_thesis": "整体投资逻辑摘要 ≤150字",
  "bom_nodes": [
    {
      "node_id": "ai_chip",
      "name": "AI 训练/推理芯片",
      "ecosystem_layer": "upstream|midstream|downstream|service_layer",
      "tier": "核心",
      "rationale": "为什么该节点在3-5年内有成长空间 ≤100字",
      "stocks": [
        {
          "symbol": "688256",
          "stock_name": "寒武纪",
          "ecosystem_position": "AI训练芯片-上游-核心硬件",
          "scoring_detail": {
            "moat": {"score": 0.90, "evidence": ["证据1", "证据2"], "evidence_source": "基于训练知识"},
            "growth": {"score": 0.85, "evidence": ["证据1", "证据2"], "evidence_source": "基于训练知识"},
            "profit": {"score": 0.60, "evidence": ["证据1", "证据2"], "evidence_source": "基于训练知识"},
            "localize": {"score": 0.95, "evidence": ["证据1", "证据2"], "evidence_source": "基于训练知识"},
            "policy_bond": {"score": 0.2, "matched_concepts": ["概念名"], "note": "说明哪个概念匹配"},
            "composite": 0.92
          },
          "exclusion_check": {"st": false, "investigation": false, "goodwill_ratio_ok": true, "audit_clean": true, "passed": true}
        }
      ]
    }
  ],
  "suggested_additions": [
    {"node_name": "建议新增的节点名", "rationale": "为什么应该纳入"]
  ],
  "excluded_stocks": [
    {"symbol": "000000", "stock_name": "某标的", "reason": "排除原因", "exclusion_rule": "对应排除规则名"}
  ],
  "disclaimer": "本标的池由 LLM 基于公开政策信息推断生成，不构成投资建议。需人工复核后使用。"
}
```

仅输出 JSON，不要额外解释。""")


def _render_prompt(
    sector: str,
    display_name: str,
    z0_plus_breakdown: dict[str, Any],
    selected_concepts: list[dict[str, Any]],
) -> str:
    """渲染 User Prompt。"""
    bd = z0_plus_breakdown or {}
    return _ECOSYSTEM_PROMPT_TPL.render(
        sector_display_name=display_name,
        policy_momentum=bd.get("policy_momentum", 0),
        commercial_trajectory=bd.get("commercial_trajectory", 0),
        capital_gravity=bd.get("capital_gravity", 0),
        implementation_quality=bd.get("implementation_quality", 0),
        z0_plus_score=bd.get("z0_plus_score", 0),
        growth_stage=bd.get("growth_stage", "unknown"),
        profit_pool=bd.get("profit_pool", "competitive"),
        valuation_tier=bd.get("valuation_tier", "tech_growth"),
        institutional_flow=bd.get("institutional_flow", "general"),
        policy_phase=bd.get("policy_phase", "maturation"),
        imp_strength=bd.get("imp_strength", "moderate"),
        policy_acceleration=bd.get("policy_acceleration", 1.0),
        regime_change_count=bd.get("regime_change_count", 0),
        selected_concepts=selected_concepts,
    )


def _fix_truncated_json(text: str) -> str | None:
    """修复被截断的 JSON（LLM max_tokens 不足导致输出不完整）。

    策略：
    1. 优先找最后一个 } 或 ] 作为安全截断点
    2. 若无，找最后一个 : 并补 null
    3. 若无，找最后一个完整的 " 并补 null
    4. 统计并补全缺失的 } 和 ]
    """
    # 统计括号差
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')
    total_open = open_braces + open_brackets
    if total_open > 30:
        return None
    if total_open <= 0:
        # 完整 JSON 或 0 层嵌套(极少)，直接返回
        return text

    # 方案 A：最后一个 } 或 ] 处截断
    last_brace = text.rfind('}')
    last_bracket = text.rfind(']')
    if last_brace >= 0 or last_bracket >= 0:
        cut = max(last_brace, last_bracket) + 1
        truncated = text[:cut]
        return _close_json(truncated)

    # 方案 B：最后被截断的键值对 — 找最后一个 : 并补 null
    last_colon = text.rfind(':')
    if last_colon >= 0:
        truncated = text[:last_colon + 1] + 'null'
        return _close_json(truncated)

    # 方案 C：找最后一个完整的字符串（引号对），补为 null 值
    last_quote = -1
    in_string = False
    for i in range(len(text) - 1, -1, -1):
        if text[i] == '"' and (i == 0 or text[i-1] != '\\'):
            in_string = not in_string
            if not in_string:
                last_quote = i
                break

    if last_quote >= 0:
        truncated = text[:last_quote + 1] + ':null'
        return _close_json(truncated)

    return None


def _close_json(truncated: str) -> str:
    """按栈追踪开闭顺序补全 JSON 括号（正确嵌套）。"""
    # 用栈追踪 { 和 [ 展开顺序，然后按逆序闭合
    stack: list[str] = []
    i = 0
    in_string = False
    while i < len(truncated):
        ch = truncated[i]
        if ch == '"' and (i == 0 or truncated[i-1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch == '}':
                # pop matching {
                for j in range(len(stack) - 1, -1, -1):
                    if stack[j] == '}':
                        stack.pop(j)
                        break
            elif ch == ']':
                # pop matching [
                for j in range(len(stack) - 1, -1, -1):
                    if stack[j] == ']':
                        stack.pop(j)
                        break
        i += 1

    # 逆序闭合
    closing = ''.join(reversed(stack))
    return truncated + closing


def _parse_json_output(raw: str) -> dict[str, Any]:
    """从 LLM 输出中提取 JSON（v2.0 · 强鲁棒解析）。"""
    text = raw.strip()

    # 1. 去除 markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    # 2. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. 尝试从 text 中提取最外层 {...} 块
    brace_depth = 0
    start = -1
    candidates = []
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and start >= 0:
                candidates.append(text[start:i + 1])
                start = -1

    # 4. 尝试每个候选块
    _candidate_count = len(candidates)
    for candidate in candidates:
        candidate = candidate.strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e:
            # 尝试修复常见 JSON 问题
            try:
                # 修复 trailing commas
                fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                parsed = json.loads(fixed)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    # 5. 全部失败，尝试截断修复：补全不完整的括号和引号
    _fixed = _fix_truncated_json(text)
    if _fixed and _fixed != text:
        try:
            parsed = json.loads(_fixed)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 6. 最后手段：用 raw_decode 定位错误，跳过问题字符后重试
    try:
        _decoder = json.JSONDecoder()
        parsed, _end = _decoder.raw_decode(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError as e:
        # 尝试跳过错误字符 (e.pos) 后的内容重新拼接
        _err_pos = e.pos
        if _err_pos > 0:
            # 在错误位置附近找一个安全的断点（前一个 } 或 , 后）
            _safe = max(text.rfind('}', 0, _err_pos), text.rfind('"', 0, _err_pos))
            if _safe > 0:
                _trimmed = text[:_safe + 1]
                # 用 _close_json 补全
                _fixed2 = _close_json(_trimmed)
                try:
                    parsed = json.loads(_fixed2)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass

    raise json.JSONDecodeError(
        f"无法从 LLM 输出中提取有效 JSON。输出预览: {text[:500]}",
        text,
        0,
    )


# ── 白名单节点 ID 集合（用于服务端校验） ──
_VALID_NODE_IDS = {nid for nid, _, _ in _BOM_WHITELIST_NODES}


def _validate_output(parsed: dict[str, Any], valid_node_ids: Optional[set[str]] = None) -> str | None:
    """服务端校验 LLM 输出，返回错误信息字符串或 None（通过）。

    注意：此函数仍为严格版（一个标的缺分即拒），infer_ecosystem_stock_pool 已改用 _clean_output() 做宽松过滤。
    """
    if valid_node_ids is None:
        valid_node_ids = _VALID_NODE_IDS
    bom_nodes = parsed.get("bom_nodes") or []
    if not bom_nodes:
        return "输出中 bom_nodes 为空"

    for node in bom_nodes:
        nid = node.get("node_id", "")
        if nid not in valid_node_ids:
            return f"节点 {nid} 不在白名单中"
        stocks = node.get("stocks") or []
        for st in stocks:
            sd = st.get("scoring_detail") or {}
            for factor in ("moat", "growth", "profit", "localize"):
                fv = sd.get(factor) or {}
                if not isinstance(fv.get("score"), (int, float)):
                    return f"{st.get('symbol')} 缺少 {factor}.score"
                ev = fv.get("evidence") or []
                if len(ev) < 2:
                    return f"{st.get('symbol')} 的 {factor}.evidence 不足 2 条"
            if not isinstance(sd.get("composite"), (int, float)):
                return f"{st.get('symbol')} 缺少 composite"
            ec = st.get("exclusion_check") or {}
            for key in ("st", "investigation", "goodwill_ratio_ok", "audit_clean", "passed"):
                if key not in ec:
                    return f"{st.get('symbol')} 缺少 exclusion_check.{key}"

    return None


def _clean_output(parsed: dict[str, Any], valid_node_ids: set[str]) -> tuple[list[dict], list[str]]:
    """宽松过滤：剔除不合格的标的 + 节点，返回 (cleaned_bom_nodes, warnings)。

    不因个别标的缺分而拒绝整个 LLM 输出。
    """
    bom_nodes = parsed.get("bom_nodes") or []
    if not bom_nodes:
        return [], ["输出中 bom_nodes 为空"]

    cleaned: list[dict] = []
    warnings: list[str] = []
    total_dropped_stocks = 0
    total_dropped_nodes = 0

    for node in bom_nodes:
        nid = node.get("node_id", "")
        if nid not in valid_node_ids:
            total_dropped_nodes += 1
            continue
        stocks = node.get("stocks") or []
        kept_stocks = []
        for st in stocks:
            symbol = st.get("symbol") or st.get("symbol_name", "?")
            sd = st.get("scoring_detail") or {}
            drop = False
            for factor in ("moat", "growth", "profit", "localize"):
                fv = sd.get(factor) or {}
                if not isinstance(fv.get("score"), (int, float)):
                    warnings.append(f"{symbol} 缺少 {factor}.score · 已剔除")
                    drop = True
                    break
            if drop:
                total_dropped_stocks += 1
                continue
            # 宽松：composite 缺填默认值
            if not isinstance(sd.get("composite"), (int, float)):
                scores = [sd.get(f, {}).get("score", 0) for f in ("moat", "growth", "profit", "localize")]
                sd["composite"] = round(sum(s for s in scores if isinstance(s, (int, float))) / max(len(scores), 1), 1)
            # 宽松：exclusion_check 缺填默认通过
            ec = st.get("exclusion_check") or {}
            for key in ("st", "investigation", "goodwill_ratio_ok", "audit_clean", "passed"):
                if key not in ec:
                    ec[key] = True if key != "st" else None
            st["exclusion_check"] = ec
            kept_stocks.append(st)

        if not kept_stocks:
            total_dropped_nodes += 1
            continue
        node["stocks"] = kept_stocks
        cleaned.append(node)

    if total_dropped_stocks:
        warnings.append(f"共剔除 {total_dropped_stocks} 个不合格标的（缺因子评分）")
    if total_dropped_nodes:
        warnings.append(f"共剔除 {total_dropped_nodes} 个无效节点")

    return cleaned, warnings


def infer_ecosystem_stock_pool(
    *,
    sector: str,
    display_name: str,
    z0_plus_breakdown: dict[str, Any],
    selected_concepts: list[dict[str, Any]],
    bom_nodes: Optional[list[tuple[str, str, str]]] = None,
    temperature: float = 0.2,
    max_tokens: int = 32000,
) -> dict[str, Any]:
    """同步调用 LLM 推断产业生态位 + BOM 节点标的池（v3.0 · 动态 BOM · 5 因子 + 证据链）。

    Args:
        bom_nodes: 用户选定的 BOM 节点列表 [(node_id, name, tier), ...]；
                   为 None 时使用默认 _BOM_WHITELIST_NODES。
    Returns:
        {status, sector, bom_nodes, ecosystem_topology, investment_thesis,
         suggested_additions, excluded_stocks, disclaimer}
    """
    from apps.common.ai_dispatcher import AIDispatcher

    # 确定使用的 BOM 列表 + 构建 system prompt
    effective_bom = bom_nodes if bom_nodes else _BOM_WHITELIST_NODES
    system_prompt = _build_system_prompt(effective_bom)
    valid_node_ids = {nid for nid, _, _ in effective_bom}

    user_prompt = _render_prompt(
        sector=sector,
        display_name=display_name,
        z0_plus_breakdown=z0_plus_breakdown,
        selected_concepts=selected_concepts,
    )

    import time as _time
    _t0 = _time.monotonic()
    dispatcher = AIDispatcher.default()
    try:
        logger.info(f"[ecosystem] LLM 调用开始 | sector={sector} | bom_nodes={len(effective_bom)} | concepts={len(selected_concepts)} | max_tokens={max_tokens}")
        result = dispatcher.call(
            scene="genesis_ecosystem",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            model_override="deepseek-v4-pro",
        )
        _elapsed = _time.monotonic() - _t0
        logger.info(f"[ecosystem] LLM 调用完成 | elapsed={_elapsed:.1f}s | len={len(result.text) if hasattr(result, 'text') else 'n/a'}")
    except Exception as exc:
        logger.exception("LLM 生态位推断调用失败")
        return {
            "status": "error",
            "error": str(exc),
            "disclaimer": "LLM 调用失败，请稍后重试或启用降级路由。",
        }

    content = result.text if hasattr(result, "text") else str(result)
    if not content:
        return {
            "status": "error",
            "error": "LLM 返回空内容",
            "disclaimer": "LLM 返回空内容，请检查 quota 或重试。",
        }
    _content_len = len(content)
    _finish_reason = getattr(result, "finish_reason", "n/a") if hasattr(result, "finish_reason") else "unknown"
    logger.info(f"[ecosystem] LLM 输出: len={_content_len} finish_reason={_finish_reason} max_tokens={max_tokens} first_200={content[:200]!r} last_200={content[-200:]!r}")

    try:
        parsed = _parse_json_output(content)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"LLM JSON 解析失败: {exc} | finish_reason={_finish_reason} content_len={_content_len} first_500={content[:500]!r} last_200={content[-200:]!r}")
        return {
            "status": "error",
            "error": f"JSON 解析失败: {exc}",
            "raw_preview": content[:500],
            "disclaimer": "LLM 输出格式异常，请联系架构师优化 Prompt。",
        }

    # ── 真实性校验：拒绝 mock 降级 ──
    if parsed.get("_dispatcher_mock"):
        logger.warning("LLM 生态位推断返回 mock 降级 · 拒绝落库")
        return {
            "status": "error",
            "error": "AI 服务配额已耗尽（返回 mock），请联系管理员充值或切换路由。",
            "raw_preview": content[:500],
            "disclaimer": "当前 AI 服务配额已耗尽。",
        }

    # ── 服务端输出校验（宽松：过滤不合格标的，不拒绝整个结果） ──
    cleaned_bom, warnings = _clean_output(parsed, valid_node_ids=valid_node_ids)
    if warnings:
        logger.warning(f"LLM 输出校验警告: {warnings[:3]}")
    if not cleaned_bom:
        return {
            "status": "error",
            "error": f"LLM 输出校验失败（无有效节点）: {'; '.join(warnings[:2])}",
            "raw_preview": content[:500],
            "disclaimer": "LLM 输出不符合 Schema 要求，请重试或优化 Prompt。",
        }

    # ── 转换输出格式（抽取 bom_nodes → 后端统一结构） ──
    out_bom_nodes = cleaned_bom

    return {
        "status": "ok",
        "sector": display_name,
        "bom_nodes": out_bom_nodes,
        "ecosystem_topology": parsed.get("ecosystem_topology", {}),
        "investment_thesis": parsed.get("investment_thesis", ""),
        "suggested_additions": parsed.get("suggested_additions", []),
        "excluded_stocks": parsed.get("excluded_stocks", []),
        "disclaimer": parsed.get(
            "disclaimer", "本标的池由 LLM 基于公开政策信息推断生成，不构成投资建议。需人工复核后使用。"
        ),
        "warnings": warnings if warnings else None,
    }


def generate_bom_nodes_for_sector(
    *,
    sector: str,
    display_name: str,
    concept_names: list[str],
    temperature: float = 0.3,
    max_tokens: int = 8000,
) -> dict[str, Any]:
    """调用 LLM 为指定赛道动态生成 BOM 产业链节点清单（v4.0 · 可勾选 · 强化提示词）。

    Returns:
        {status, bom_nodes: [{node_id, name, tier, rationale, score}],
         top_recommendations: [node_id, ...],
         industry_summary: str}
    """
    from apps.common.ai_dispatcher import AIDispatcher

    concept_list_str = "\n".join(f"- {c}" for c in concept_names) if concept_names else "暂无特定概念"

    user_prompt = f"""请全面分解以下赛道的产业链 BOM 节点。

## 赛道信息
- 赛道 ID（sector）：{sector}
- 赛道展示名（display_name）：{display_name}
- 关联 A 股概念板块：
{concept_list_str}

## 分解要求
1. 必须从上游（原材料/设备/IP→代工）→ 中游（核心器件/系统集成）→ 下游（产品/应用/服务）→ 服务配套（运维/调度/安全/数据）**四个层次全面覆盖**
2. 每个层次至少 2 个节点，全部节点 23-28 个
3. tier 至少 3 个\"核心\"、4 个\"重要\"
4. 每个节点的 rationale 需结合真实产业现状说明
5. layer 字段：AI/半导体/数字科技赛道根据五层蛋糕标注 L1~L5，其余赛道 null

## ⚠️ 最重要规则：纯 JSON 输出
你的回答必须**以 `{{` 开头、以 `}}` 结尾**的完整 JSON 对象，不能在 JSON 前后有任何文字（包括思考过程、分析描述、问候语、markdown 代码标记）。

✅ 正确输出示例：
{{"bom_nodes": [{{"node_id":"chip","name":"AI芯片","tier":"核心","layer":"L2","rationale":"...","score":90}}], "top_recommendations":["chip"], "industry_summary":"该赛道..."}}

❌ 错误输出示例（会被拒绝）：
"好的，让我先思考一下..." 或 "```json..." 或 "以下是分解结果：..."

请直接输出 JSON。"""

    dispatcher = AIDispatcher.default()
    try:
        result = dispatcher.call(
            scene="genesis_ecosystem",
            messages=[
                {"role": "system", "content": _BOM_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            model_override="deepseek-v4-pro",
        )
    except Exception as exc:
        logger.exception("LLM BOM 生成调用失败")
        return {"status": "error", "error": str(exc)}

    content = result.text if hasattr(result, "text") else str(result)
    if not content:
        return {"status": "error", "error": "LLM 返回空内容"}

    # 尝试解析 + 自动重试（最多 1 次纠正）
    parsed = None
    parse_error = None
    for attempt in range(2):
        if attempt > 0:
            # 重试：发送纠正提示
            correction_prompt = (
                f"你之前的输出不是有效的 JSON。以下是你的原始输出（仅用于参考）：\n\n{content[:1500]}\n\n"
                f"请重新生成，**必须只输出纯 JSON 对象**，以 {{{{ 开头、以 }}}} 结尾，不要任何解释性文字。"
            )
            logger.warning(f"BOM 生成 JSON 解析失败，正在重试（尝试 #{attempt + 1}）")
            try:
                result = dispatcher.call(
                    scene="genesis_ecosystem",
                    messages=[
                        {"role": "system", "content": _BOM_GENERATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": content[:2000]},
                        {"role": "user", "content": correction_prompt},
                    ],
                    temperature=temperature + 0.1,
                    max_tokens=max_tokens,
                    model_override="deepseek-v4-pro",
                )
            except Exception as exc:
                return {"status": "error", "error": f"重试调用失败: {exc}"}
            content = result.text if hasattr(result, "text") else str(result)
            if not content:
                return {"status": "error", "error": "重试返回空内容"}

        try:
            parsed = _parse_json_output(content)
        except (json.JSONDecodeError, ValueError) as exc:
            parse_error = str(exc)
            logger.warning(f"BOM 生成 JSON 解析失败（attempt#{attempt + 1}）: {exc}")
            parsed = None
            continue
        else:
            break  # 解析成功，跳出重试循环

    if parsed is None:
        return {
            "status": "error",
            "error": f"JSON 解析失败（重试后仍失败）: {parse_error}",
            "raw_preview": content[:500],
        }

    # 真实性校验
    if parsed.get("_dispatcher_mock"):
        logger.warning("BOM 生成返回 mock 降级")
        return {"status": "error", "error": "AI 服务配额已耗尽（返回 mock），请联系管理员充值。"}

    # 校验基础结构
    bom_nodes = parsed.get("bom_nodes") or []
    if not bom_nodes:
        return {"status": "error", "error": "LLM 未生成有效的 bom_nodes", "raw_preview": content[:500]}

    # 归一化每个节点的 tier
    valid_tiers = {"核心", "重要", "配套"}
    for n in bom_nodes:
        if n.get("tier") not in valid_tiers:
            n["tier"] = "配套"

    return {
        "status": "ok",
        "bom_nodes": bom_nodes,
        "top_recommendations": parsed.get("top_recommendations", []),
        "industry_summary": parsed.get("industry_summary", ""),
    }


__all__ = [
    "infer_ecosystem_stock_pool",
    "generate_bom_nodes_for_sector",
    "start_ecosystem_inference",
    "get_inference_task",
    "cancel_inference_task",
    "_build_system_prompt",
    "_build_bom_prompt",
    "_BOM_WHITELIST_NODES",
    "_VALID_NODE_IDS",
]


async def cancel_inference_task(task_id: str) -> bool:
    """取消正在执行的后台推断任务。"""
    async with _TASK_LOCK:
        if task_id not in _TASKS:
            return False
        _TASKS.pop(task_id, None)
        return True


async def _run_inference_task(task_id: str, **kwargs: Any) -> None:
    """
    后台执行 LLM 推断，结果写入 _TASKS[task_id]。
    使用 asyncio.to_thread() 放到独立线程运行，避免阻塞 uvicorn 事件循环。
    """
    try:
        result = await asyncio.to_thread(infer_ecosystem_stock_pool, **kwargs)
    except Exception as exc:
        logger.exception(f"后台生态位推断失败 task={task_id}")
        result = {"status": "error", "error": str(exc)}
    async with _TASK_LOCK:
        if task_id not in _TASKS:
            return
        _TASKS[task_id] = {"status": "done", "result": result}
    await asyncio.sleep(_TASK_TTL_SECONDS)
    async with _TASK_LOCK:
        _TASKS.pop(task_id, None)


async def start_ecosystem_inference(**kwargs: Any) -> str:
    """启动后台生态位推断任务，返回 task_id。"""
    task_id = uuid.uuid4().hex[:12]
    async with _TASK_LOCK:
        _TASKS[task_id] = {"status": "processing"}
    asyncio.create_task(_run_inference_task(task_id, **kwargs))
    return task_id


async def get_inference_task(task_id: str) -> dict[str, Any] | None:
    """查询任务状态。返回 None 表示 task_id 不存在或已过期。"""
    async with _TASK_LOCK:
        return _TASKS.get(task_id)
