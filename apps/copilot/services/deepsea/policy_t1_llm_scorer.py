"""Z0-M2 政策 T1 Phase B1 · 逐篇 LLM 语义评分。

每篇政策文档独立调用 LLM，输出结构化 JSON（含 doc_metadata）。
无 fallback：LLM 不可用或输出格式错误直接抛异常。

[Ref: 36_ §4/§5.0/§10 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是一位专业的投研政策分析助手。你的任务是阅读**单篇**政策全文，提取文中提到的所有产业/行业/领域名称，
并判断政策对它们的影响。同时评估政策的「实施工具包」——即政策配套了哪些实质性的执行手段。

## ⚠️ 赛道命名铁律（最高优先级）

**赛道名称必须100%来自文档原文中的官方术语，禁止任何形式的翻译、归类、合并或创造。**

反例（禁止）：
- 文档写「交通运输公共数据资源开发利用」 → ❌ 输出「数字经济」/「AI算力」
- 文档写「口岸进境免税店」 → ❌ 输出「消费内需」
- 文档写「数据中心」/「算力基础设施」 → ❌ 输出「AI算力」
- 文档写「新能源汽车产业」 → ❌ 输出「新能源」
- 文档写「新一代人工智能产业」 → ❌ 输出「AI算力」

正例（正确）：
- 文档写「数据中心」 → ✅ 输出「数据中心」
- 文档写「算力基础设施」 → ✅ 输出「算力基础设施」
- 文档写「新能源汽车产业」 → ✅ 输出「新能源汽车产业」
- 文档写「交通运输公共数据资源开发利用」 → ✅ 输出「交通运输数据资源开发」或「交通运输信息化」
- 文档写「口岸进境免税店」 → ✅ 输出「口岸免税消费」

**原则**：sector_name 是一个能从 evidence_quotes 原文句子中直接定位到的官方术语短语。

## ⚠️ 赛道 vs 公司/机构 强制区分

sector_name 必须是产业、行业、经济领域名称，**禁止**使用以下作为 sector_name：
- 公司/企业名称（如「南极电商」「宁德时代」「华为」）
- 金融机构类型（如「中介机构」「保荐机构」「会计师事务所」）
- 金融产品名称（如「可转债」「绿色债」——这些是产品，不是赛道）
- 个人或职位名称

反例（禁止）：
- 文档提及「对南极电商纳入重点监控」 → ❌ sector_name 不能是「南极电商」
- 文档提及「压实中介机构责任」 → ❌ sector_name 不能是「中介机构」
- 文档提及「首发企业现场检查」 → ❌ sector_name 不能是「首发企业」

正确处理：
- 如果文档内容确实不涉及任何产业/行业，则 sectors 数组为空
- 只提取文中的产业/经济领域概念（如「新能源汽车产业」「算力基础设施」「碳交易市场」）

## 其他规则

2. 一条文档可能涉及多个赛道，每个赛道独立判断方向和影响强度

3. 每条 evidence_quotes 必须是原文中完整的句子（至少 1 条），从这些句子中可以直接找到 sector_name

4. 如果同一赛道既有正面又有负面表述，选择影响更大的那个方向，在 reasoning 中说明

5. 如果没有赛道受影响，sectors 数组为空

6. doc_metadata.impl_status 须基于全文内容判断，不要仅看标题

7. **高价值政策识别**：如果该政策属于以下任意一种，必须在根级设置 `high_value_flag: true`：
   - 国家级专项规划（十四五、十五五、国务院令、国发、中办/国办发文）
   - 文中明确指出**具体产业/行业/领域/区域为"重点扶持""优先发展""国家战略"**级别
   - 文中直接点名**具体公司/标的**或明确划定了产业规模的量化目标
   - 不是"顺带提及"或"鼓励探索"，而是有**实质性措施**（财政拨款、税收减免、土地审批、专项基金等）
   大部分政策文档应设为 `high_value_flag: false`

## 候选赛道列表（必须从下方选一作为 canonical_sector）

| 序号 | 规范赛道 | 含义 | 可接受原文术语示例 |
|------|---------|------|--------------------|
| 1 | AI算力 | 人工智能、算力基础设施、芯片半导体 | 算力基础设施、人工智能产业、数据中心、智算中心、大模型训练、集成电路 |
| 2 | 新能源 | 光伏、储能、风电、氢能、新能源汽车 | 新能源汽车产业、光伏组件产业、储能、充电基础设施、绿色电力 |
| 3 | 低空经济 | 无人机、eVTOL、通用航空 | 低空基础设施、无人驾驶航空器、通用航空产业 |
| 4 | 数字经济 | 数据要素、工业互联网、5G、物联网 | 数字中国、数据要素市场、数字化转型、工业物联网 |
| 5 | 医药创新 | 创新药、生物医药、医疗器械 | 医药创新、中医药服务贸易、药品零售 |
| 6 | 消费内需 | 消费电子、跨境电商、以旧换新 | 丝路电商、消费升级、电子商务 |
| 7 | 环保节能 | 碳中和、绿色转型、环保治理 | 污水处理、节能降碳、绿色低碳产业 |
| 8 | 基建交通 | 基础设施、铁路、水利 | 城市更新、高速铁路、机场群、国家高速公路网 |
| 9 | 金融国资 | 国资改革、资本市场改革 | 新三板、海南自由贸易港 |
| 10 | 军工国防 | 国防军工、军民融合 | — |
| 11 | 农业粮食 | 粮食安全、种业、乡村振兴 | 智慧农业 |
| 12 | 新质生产力 | 新质生产力、未来产业 | 科技型企业孵化器、先进制造业 |
| null | 无匹配 | 不属于以上任何一类的政策内容 | 家政服务、环境科普、旅行服务等非投资领域 |

**选择 canonical_sector 的原则**：优先匹配产业链归属，而非表面关键词。例如：
- 「光伏组件综合利用产业」→ canonical_sector: "新能源"（光伏属于新能源产业链）
- 「万兆光网」→ canonical_sector: "AI算力"（光网是算力基础设施的一部分）
- 「智慧农业」→ canonical_sector: "农业粮食"

## 输出格式（必须严格 JSON）
{
  "sectors": [
    {
      "sector_name": "文档原文中的官方产业/行业/领域术语",
      "canonical_sector": "候选赛道列表中的规范赛道名（AI算力/新能源/低空经济/数字经济/医药创新/消费内需/环保节能/基建交通/金融国资/军工国防/农业粮食/新质生产力 之一），无匹配则为 null",
      "direction": "strong_tailwind|weak_tailwind|neutral|weak_headwind|strong_headwind",
      "impact_score": 0-100,
      "evidence_quotes": ["原文引用的句子（至少1条）"],
      "reasoning": "判断依据，包括为什么选这个 canonical_sector",
      "implementation_toolkit": {
        "fiscal_support": 0-10,
        "talent_programs": 0-10,
        "land_infra": 0-10,
        "regulatory_fast_track": 0-10,
        "standards_legislation": 0-10,
        "quantitative_targets": 0-10
      },
      "implementation_strength": "comprehensive|targeted|moderate|light|symbolic",
      "revenue_transmission_type": "direct_cash|market_creation|government_procurement|cost_reduction|standards_enabler|political_rhetoric",
      "narrative_catalyst_type": "national_strategy_tech|new_industry_birth|modernization_leap|consumption_lifestyle|regulator_fix|basic_necessity_security|political_slogan",
      "policy_phase": "initiation|acceleration|maturation|phase_out",
      "policy_regime_change_flag": true|false
    }
  ],
  "overall_assessment": "一句话总体判断",
  "high_value_flag": false,
  "doc_metadata": {
    "impl_status": "已发布_待执行|已执行_进行中|已执行_完成|征求意见稿|废止_替代|状态未知",
    "impl_status_reasoning": "推断依据"
  },
  "selected_concepts": "概念名1,概念名2" // ★ v5.0 新增：从下方「概念板选项」中选出的相关概念名，逗号分隔；若都不相关则为 "NONE"
}

## 实施工具包评分标准（implementation_toolkit · 0-10）

评分原则：0=完全没有，10=该维度有非常明确、具体的实质性措施。

| 维度 | 含义 | 评分参考 |
|------|------|---------|
| fiscal_support | 财政支持：专项拨款、补贴、税收减免、专项基金 | 有具体金额+拨款路径=8-10；有框架无金额=4-7；仅提到=1-3 |
| talent_programs | 人才政策：人才引进计划、培训补贴、激励机制 | 有具体人才专项计划名称=8-10；有人才表述无计划=4-7；仅提到=1-3 |
| land_infra | 土地/基建：用地保障、基础设施专项投入 | 有用地指标/基建项目清单=8-10；有表述无具体项目=4-7；仅提到=1-3 |
| regulatory_fast_track | 审批简化：绿色通道、试点授权、负面清单豁免 | 有具体审批时限/豁免清单=8-10；有简化表述=4-7；无提及=0-3 |
| standards_legislation | 标准/立法：行业标准制定、专项立法 | 有标准编号/立法计划=8-10；有标准制定表述=4-7；无提及=0-3 |
| quantitative_targets | 量化目标：明确的KPI指标、产业规模、时间节点 | 有具体数字+时间节点=8-10；有数字无时间=4-7；仅有方向性描述=1-3 |

## implementation_strength 分类

| 分类 | 含义 | 触发条件 |
|------|------|---------|
| comprehensive | 全面覆盖：财政+人才+基建+体系化配套 | toolkit总分≥40 且 ≥4个维度≥8 |
| targeted | 精准施策：2-3个关键维度有实质性投入 | toolkit总分≥25 且 有维度≥8 |
| moderate | 中度支撑：有具体措施但力度一般 | toolkit总分≥15 |
| light | 轻度支撑：有提及但缺乏执行细节 | toolkit总分≥5 |
| symbolic | 象征性：几乎没有实质性配套措施 | toolkit总分<5 |

## ★ revenue_transmission_type（政策→上市公司收入的传导路径）

对于每个赛道，判断该政策主要通过什么路径影响上市公司的实际收入。
这是用来区分「政府喊口号」和「政府给真金白银」的核心维度。

| 分类 | 含义 | 文档特征 | 示例 |
|------|------|----------|------|
| direct_cash | 直接资金流入：补贴、税收减免、退税、专项拨款 | 含具体金额、拨款路径、补贴标准 | 「对新能源汽车免征购置税」「给予XX产业每年100亿专项补贴」 |
| market_creation | 创造新市场：政策直接打开一个全新的市场需求 | 含新牌照、新准入、新试点、新交易品种 | 「开放低空商业运营」「设立数据交易所」 |
| government_procurement | 政府采购：政府作为直接买家 | 含采购目录、采购比例要求 | 「政府机关新增车辆中新能源占比不低于30%」 |
| cost_reduction | 降成本：降低行业运营成本 | 含降费、减负、简化审批 | 「降低企业用电成本」「精简审批流程」 |
| standards_enabler | 标准赋能：通过制定标准打开市场 | 含行业标准、技术规范、互认协议 | 「发布XX行业技术标准」 |
| political_rhetoric | 政治表态：无具体商业转化路径 | 仅有鼓励、支持、号召，无任何具体措施 | 「大力支持XX产业发展」「推动XX高质量发展」 |

## ★ narrative_catalyst_type（政策创造的股市叙事类型）

A股是情绪驱动市场。同样的政策力度，不同叙事类型吸引的资金量天差地别。
从文档内容判断该政策能讲出多大的股市故事。

| 分类 | 含义 | 文档特征 | 示例 |
|------|------|----------|------|
| national_strategy_tech | 国家战略+技术突破 | 「卡脖子」「自主可控」「国家重大科技专项」 | AI芯片、量子计算 |
| new_industry_birth | 全新产业诞生 | 「首次开放」「试点推行」「新兴产业」 | 低空经济、人形机器人 |
| modernization_leap | 产业现代化跨越 | 「数字化转型」「智能化升级」「高质量发展」 | 工业互联网、智能制造 |
| consumption_lifestyle | 消费与生活方式 | 「消费升级」「品质生活」「以旧换新」 | 消费电子、新零售 |
| regulator_fix | 监管修复 | 「整改」「规范」「出清」 | 平台经济整改 |
| basic_necessity_security | 基础民生与安全 | 「保障」「底线」「安全」 | 粮食安全、能源保供 |
| political_slogan | 政治口号：无产业细节 | 仅有方向性表述，无具体领域 | 「发展新质生产力」泛泛表述 |

## ★ policy_phase（该赛道当前处于政策生命周期的哪个阶段）

| 阶段 | 文档特征 | 示例 |
|------|----------|------|
| initiation | 首次提及、试点、规划制定、征求意见 | 「首次提出XX概念」「启动XX试点」 |
| acceleration | 政策密集出台、多部委协同、力度加大 | 近期连续发布多份文件、配套措施陆续跟进 |
| maturation | 常态化管理、微调、总结回顾 | 政策框架完整、以执行和监督为主 |
| phase_out | 补贴退坡、限制新增、出清 | 「逐步退出」「补贴终止」「产能控制」 |

## ★ policy_regime_change_flag（是否构成政策拐点）

判断该文件是否标志着该赛道政策方向出现了质的变化。
**TRUE** 的条件（满足**任一**即可）：
- 国务院/中央文件首次将某方向纳入国家战略
- 政策方向从「限制/规范」转为「鼓励/支持」
- 文件级别从部委级上升到国务院级
- 文件中包含「前所未有」「历史性」「重大」等表述且有实质性配套

## 文档实施状态定义
状态             | 含义
已发布_待执行     | 政策已正式发布（含"印发""发布""通知"等），但尚未到执行日期或刚发布不久
已执行_进行中     | 政策正在执行中，正文含进度汇报、阶段成果、继续推进等表述
已执行_完成       | 政策目标已完成、总结、收官、回顾
征求意见稿       | 尚未正式实施，仍在公开征求意见阶段（标题或正文含"征求意见"且未正式发布）
废止_替代         | 已被新政策废止或替代，不再生效（正文含"废止""同时废止""替代"）
状态未知         | 无法从文本中判断

## 影响方向定义
方向               | 含义
strong_tailwind   | 强利好：明确扶持、补贴、财政支持、立法保障、国家规划
weak_tailwind     | 弱利好：提及鼓励发展、方向性认可、研究探索
neutral           | 中性：无直接关联或平衡表述
weak_headwind     | 弱利空：规范管理、提高准入门槛、窗口指导
strong_headwind   | 强利空：限制、禁止、淘汰、惩罚性措施、征收

## 影响强度评分（0-100）
范围       | 含义
----------|------
81-100    | 重大影响：政策直接针对该赛道，且有实质性措施
61-80     | 显著影响：政策明确涉及该赛道，有具体条款
41-60     | 中等影响：政策部分涉及
21-40     | 轻度影响：间接涉及或顺带提及
0-20      | 可忽略：几乎无关联
"""

_KEYWORDS_CFG = (
    Path(__file__).resolve().parents[4]
    / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
)

ALLOWED_DIRECTIONS: set[str] = {
    "strong_tailwind", "weak_tailwind", "neutral",
    "weak_headwind", "strong_headwind",
}

ALLOWED_IMPL_STATUS: set[str] = {
    "已发布_待执行", "已执行_进行中", "已执行_完成",
    "征求意见稿", "废止_替代", "状态未知",
}


def _load_keywords() -> dict[str, Any]:
    if not _KEYWORDS_CFG.is_file():
        return {
            "sector_prompt_descriptions": {},
            "sector_aliases": {},
        }
    with _KEYWORDS_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_allowed_sectors() -> list[str]:
    cfg = _load_keywords()
    aliases = cfg.get("sector_aliases") or {}
    return list(aliases.keys())


def _get_sector_descriptions() -> dict[str, str]:
    cfg = _load_keywords()
    return cfg.get("sector_prompt_descriptions") or {}


def _estimate_tokens(text: str) -> int:
    """中文 token 近似估算。"""
    return int(len(text) * 0.28) + 1


def _truncate_middle(text: str, max_chars: int) -> str:
    """保留首尾，截断中间。"""
    if len(text) <= max_chars:
        return text
    head_end = int(max_chars * 0.6)
    tail_start = max_chars - head_end
    return text[:head_end] + "\n...（中间截断）...\n" + text[-tail_start:]


def assemble_context(
    title: str,
    summary: str,
    full_text: str | None,
    *,
    full_text_budget: int = 6000,
) -> str:
    """组装单篇政策全文上下文。"""
    text = title or ""
    if summary and summary != title:
        text = f"{title}\n\n摘要：{summary}"
    if full_text:
        truncated = _truncate_middle(full_text, full_text_budget)
        text = f"{text}\n\n正文：\n{truncated}"
    return text


def _build_concept_options_all() -> str:
    """v5.0: 从 YAML 读取全部 canonical_sectors 的 child_concepts，拼接为 LLM 选择列表。
    
    往返链路：LLM 输出 concept name → B2 阶段反向查找所属 canonical_sector。
    """
    cfg_path = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
    seen = set()
    options: list[str] = []
    try:
        with cfg_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        for sector_key, sector_cfg in (cfg.get("canonical_sectors") or {}).items():
            for cc in sector_cfg.get("child_concepts") or []:
                name = str(cc.get("name", "")).strip()
                code = str(cc.get("code", "")).strip()
                if name and name not in seen:
                    seen.add(name)
                    options.append(f"{name}({code})" if code else name)
    except Exception:
        pass
    return ", ".join(options)


def build_prompt(context: str, concept_options: str = "") -> str:
    """构建用户 Prompt — 无预设赛道列表，让 LLM 从文档中提取官方原名。
    
    v5.0: 注入 A股概念板选项，LLM 直接从中多选。
    """
    concept_section = ""
    if concept_options:
        concept_section = f"""## A股概念板选项（v5.0 · 先读）

本系统覆盖以下A股投资概念板。分析政策时请判断与哪些概念**直接相关**，选出0~N个，输出原始概念名，逗号分隔。都不相关输出 NONE。

[{concept_options}]

**选择原则**：具有实质性影响；宁缺毋滥。

---

"""

    return f"""{concept_section}## 政策全文
{context}

请输出 JSON（必须含 sectors、overall_assessment、high_value_flag、selected_concepts、doc_metadata 五字段）。
selected_concepts 必须输出：从上方概念板选项中选中的名称（逗号分隔），都不相关则输出 "NONE"。"""


def parse_llm_json(raw: str) -> dict[str, Any]:
    """解析并校验 LLM 返回的 JSON（含 doc_metadata）。"""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    data = json.loads(clean)

    if not isinstance(data, dict):
        raise ValueError(f"LLM 输出不是 JSON 对象: {type(data).__name__}")
    sectors = data.get("sectors")
    if not isinstance(sectors, list):
        raise ValueError("LLM 输出缺少 sectors 数组")

    allowed = set(_get_allowed_sectors())
    validated = []
    for item in sectors:
        if not isinstance(item, dict):
            continue
        sector = str(item.get("sector_name") or "").strip()
        if not sector:
            continue
        # 轻量归一化：去括号内冗余、去首尾标点
        sector = re.sub(r"[「」《》]", "", sector).strip()
        # 规范赛道名（LLM 归集）
        canonical = str(item.get("canonical_sector") or "").strip()
        if not canonical or canonical.lower() == "null":
            canonical = None
        direction = str(item.get("direction") or "neutral")
        if direction not in ALLOWED_DIRECTIONS:
            direction = "neutral"
        score = float(item.get("impact_score") or 0)
        score = max(0.0, min(100.0, score))
        quotes = item.get("evidence_quotes") or []
        if not isinstance(quotes, list):
            quotes = [str(quotes)] if quotes else []
        quotes = [str(q).strip() for q in quotes if q]
        reasoning = str(item.get("reasoning") or "无推理过程").strip()

        # 解析实施工具包（v5.1 新增）
        toolkit_raw = item.get("implementation_toolkit") or {}
        toolkit = {
            "fiscal_support": max(0, min(10, int(toolkit_raw.get("fiscal_support", 0) or 0))),
            "talent_programs": max(0, min(10, int(toolkit_raw.get("talent_programs", 0) or 0))),
            "land_infra": max(0, min(10, int(toolkit_raw.get("land_infra", 0) or 0))),
            "regulatory_fast_track": max(0, min(10, int(toolkit_raw.get("regulatory_fast_track", 0) or 0))),
            "standards_legislation": max(0, min(10, int(toolkit_raw.get("standards_legislation", 0) or 0))),
            "quantitative_targets": max(0, min(10, int(toolkit_raw.get("quantitative_targets", 0) or 0))),
        }
        impl_strength_raw = str(item.get("implementation_strength") or "symbolic")
        ALLOWED_IMPL_STRENGTH = {"comprehensive", "targeted", "moderate", "light", "symbolic"}
        impl_strength = impl_strength_raw if impl_strength_raw in ALLOWED_IMPL_STRENGTH else "symbolic"

        validated.append({
            "sector_name": sector,
            "canonical_sector": canonical,
            "direction": direction,
            "impact_score": round(score, 1),
            "evidence_quotes": quotes,
            "reasoning": reasoning,
            "implementation_toolkit": toolkit,
            "implementation_strength": impl_strength,
        })

    # 解析 doc_metadata
    meta = data.get("doc_metadata") or {}
    impl_status = str(meta.get("impl_status") or "状态未知")
    if impl_status not in ALLOWED_IMPL_STATUS:
        impl_status = "状态未知"
    impl_reasoning = str(meta.get("impl_status_reasoning") or "无法推断")

    return {
        "sectors": validated,
        "overall_assessment": str(data.get("overall_assessment") or ""),
        "high_value_flag": bool(data.get("high_value_flag")),
        "selected_concepts": str(data.get("selected_concepts") or ""),  # v5.0: LLM 直出概念
        "doc_metadata": {
            "impl_status": impl_status,
            "impl_status_reasoning": impl_reasoning,
        },
    }


async def score_policy_document(
    doc: dict[str, Any],
    *,
    model: str = "deepseek-chat",
    temperature: float = 0.1,
) -> dict[str, Any]:
    """单篇政策文档 LLM 语义评分。失败抛异常（无 fallback）。
    
    v5.0: LLM 输出 selected_concepts 字段（从 YAML child_concepts 选项中选择）。
    """
    from apps.common.ai_dispatcher import AIDispatcher

    context = assemble_context(
        title=str(doc.get("title") or ""),
        summary=str(doc.get("summary") or ""),
        full_text=str(doc.get("full_text") or None) or None,
    )
    concept_options = _build_concept_options_all()
    prompt = build_prompt(context, concept_options=concept_options)

    dispatcher = AIDispatcher.default()
    result = dispatcher.call(
        scene="scorer_policy",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=4000,
        model_override=model,
        force_route="deepseek",
    )

    raw = result.text or ""
    parsed = parse_llm_json(raw)
    token_used = result.tokens_in + result.tokens_out

    # v5.0: 提取 LLM 直出的概念选择
    selected_concepts_raw = _parse_selected_concepts(parsed.get("selected_concepts") or "")

    return {
        "doc_id": str(doc.get("doc_id") or ""),
        "sectors": parsed["sectors"],
        "overall_assessment": parsed["overall_assessment"],
        "high_value_flag": parsed.get("high_value_flag", False),
        "doc_metadata": parsed.get("doc_metadata") or {
            "impl_status": "状态未知",
            "impl_status_reasoning": "LLM 未输出",
        },
        "selected_concepts": selected_concepts_raw,  # v5.0
        "t1_source": f"llm:{model}",
        "llm_confidence": _estimate_confidence(parsed),
        "token_used": token_used,
    }


def _parse_selected_concepts(raw: str) -> list[str]:
    """v5.0: 解析 LLM 输出的 selected_concepts 字段（逗号分隔的概念名列表）。
    
    LLM 输出格式：'人工智能(302035),东数西算(算力)(308828)' 
    → 转换为 ['人工智能', '东数西算(算力)'] （去除末尾 (code) 仅当格式匹配时）
    """
    import re
    if not raw or raw.strip().upper() == "NONE":
        return []
    names: list[str] = []
    for token in raw.split(","):
        name = token.strip()
        # 去除末尾 (code) 后缀 e.g. 人工智能(302035) → 人工智能
        name = re.sub(r'\(\d+\)$', '', name).strip()
        if name:
            names.append(name)
    return names


def _estimate_confidence(parsed: dict[str, Any]) -> float:
    """基于输出质量估计置信度。"""
    sectors = parsed.get("sectors") or []
    if not sectors:
        return 0.3
    with_evidence = sum(1 for s in sectors if len(s.get("evidence_quotes") or []) >= 2)
    total = len(sectors)
    if total == 0:
        return 0.3
    # 考虑 doc_metadata 的存在也加分
    meta = parsed.get("doc_metadata") or {}
    meta_bonus = 0.05 if meta.get("impl_status") else 0
    evidence_ratio = with_evidence / total
    return round(0.5 + evidence_ratio * 0.4 + meta_bonus, 2)


async def dispatch_b1(
    docs: list[dict[str, Any]],
    *,
    model: str = "deepseek-chat",
    concurrency: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """B1 逐篇并行 LLM 评分（信号量控并发）。返回 (successes, errors)。"""
    import asyncio

    sem = asyncio.Semaphore(concurrency)

    async def _score_one(doc: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            return await score_policy_document(doc, model=model)

    tasks = [_score_one(doc) for doc in docs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for doc, result in zip(docs, results):
        if isinstance(result, Exception):
            errors.append({
                "doc_id": str(doc.get("doc_id") or ""),
                "error": str(result)[:200],
            })
            logger.warning("B1 评分失败 doc_id=%s: %s", doc.get("doc_id"), result)
        else:
            successes.append(result)

    return successes, errors


__all__ = [
    "assemble_context",
    "build_prompt",
    "parse_llm_json",
    "score_policy_document",
    "dispatch_b1",
]
