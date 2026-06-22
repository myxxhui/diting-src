"""AI 产业生态 5-10 年战略样板 seed。

[Ref: 30_ §附录 A]
"""
from __future__ import annotations

AI_ECOSYSTEM_SEED: dict = {
    "name": "AI 产业生态 5-10 年战略",
    "horizon_start": 2026,
    "horizon_end": 2036,
    "color_token": "indigo",
    "is_template": True,
    "qualitative_md": (
        "战略定性：Beta 利润尾声 · Alpha 硬核技术爆发前夜，"
        "向全栈国产替代、算力精算、B 端私有化、具身智能四波次演进。"
    ),
    "barbell_config_json": {
        "periods": [
            {"label": "2026-2028", "hardware": 70, "software": 30, "cash": 0},
            {"label": "2028-2031", "hardware": 30, "software": 50, "cash": 20},
            {"label": "2031-2036", "hardware": 0, "software": 60, "cash": 40},
        ],
        "pseudo_tech_traps": [
            "连续两季度研发费用率 < 5% 且资本化率 > 25%",
            "应收账款周转天数连续 3 季度环比拉长 > 20%",
            "CTO/首席科学家流失或大股东高位大宗减持",
        ],
    },
    "phases": [
        {
            "wave_no": 1,
            "name": "第一波 · 硬核硬件基建",
            "start_year": 2026,
            "end_year": 2028,
            "situation_md": (
                "传统堆叠物理 GPU 边际效益递减；1.6T 光模块、全栈液冷、"
                "CXL/Retimer 成为打破通信墙与显存墙的关键。"
            ),
            "playbook_md": (
                "量化锁死合同负债与原材料备货环比，右侧重仓吃满硬件基建主升浪；"
                "2028 年后逐步获利了结。"
            ),
            "cso_barbell_pct_json": {"hardware": 70, "software": 30},
            "symbols": [
                ("601138", "硬件巨头"),
                ("300308", "光模块龙头"),
                ("300502", "光模块龙头"),
                ("688008", "卡脖子新贵"),
            ],
            "probes": [
                "cloud_capex_consensus",
                "nvda_gpu_leadtime",
                "tsmc_cowos_capacity",
                "cxl_adoption_risk",
                "copper_optical_shift",
            ],
        },
        {
            "wave_no": 2,
            "name": "第二波 · 算力精算时代",
            "start_year": 2028,
            "end_year": 2030,
            "situation_md": (
                "万卡/十万卡集群建成，异构 GPU 混部导致空转、丢包、功耗成为全行业痛点；"
                "国产算力芯片生态在政策驱动下全栈替代。"
            ),
            "playbook_md": "非共识期左侧潜伏 AI FinOps 与调度层龙头，等待智算中心强制采购调优软件。",
            "cso_barbell_pct_json": {"hardware": 30, "software": 50, "cash": 20},
            "symbols": [
                ("688316", "算力精算师"),
                ("688229", "算力精算师"),
                ("603496", "算力网络可视化"),
            ],
            "probes": [
                "cloud_capex_consensus",
                "dram_cycle_peak",
                "intel_platform_delay",
            ],
        },
        {
            "wave_no": 3,
            "name": "第三波 · B 端私有化变现",
            "start_year": 2030,
            "end_year": 2032,
            "situation_md": (
                "垂类 AI 辅助工具跨越鸿沟；信创合规与数据要素资产化双重红利，"
                "B 端私有化大模型付费转化率陡峭拐点。"
            ),
            "playbook_md": "关注专项 AI 付费包转化率、私有化复购率与 ARPU 拐点。",
            "cso_barbell_pct_json": {"software": 60, "cash": 40},
            "symbols": [
                ("688111", "办公 AI 领航者"),
                ("002230", "合规与私有化先锋"),
                ("300033", "合规与私有化先锋"),
            ],
            "probes": ["cpi_ppi_spread", "eda_ip_sanction"],
        },
        {
            "wave_no": 4,
            "name": "第四波 · 具身智能与 Multi-Agent",
            "start_year": 2032,
            "end_year": 2036,
            "situation_md": (
                "多智能体与具身智能在工业制造、电网巡检、供应链中成为核心生产力；"
                "2032 年后 Agent 复购率与无人化率过 20% 为生死线。"
            ),
            "playbook_md": "2030 年前保持跟踪；2032 年后标杆工厂无人化率突破再重仓。",
            "cso_barbell_pct_json": {"software": 60, "cash": 40},
            "symbols": [
                ("300378", "工业 Agent 中枢"),
                ("002929", "多体协同 Agent"),
            ],
            "probes": ["tsmc_advanced_restriction", "tfln_disruption"],
        },
    ],
}
