#!/usr/bin/env python3
"""Generate probe_registry YAML from 28_ §2.3–§2.7 spec. [Ref: 28_ §2.13]"""
import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/config/probe_registry"

# T1 engine → (signal_type, t1_pipeline)
ENGINE = {
    "Python": ("hard", "python_hard"),
    "PyMuPDF": ("structured", "pymupdf_structured"),
    "Playwright": ("structured", "playwright_structured"),
    "DeepSeek": ("semantic", "deepsea_semantic"),
    "Python+DeepSeek": ("hybrid", "hybrid_merge"),
}

CADENCE = {
    "日": ("daily", 7),
    "月": ("monthly", 35),
    "季": ("quarterly", 120),
    "半年": ("semi_annual", 200),
    "年": ("annual", 365),
    "动": ("dynamic", 14),
}

# (symbol, prefix, job_financials, job_dynamic, job_extra?)
PROFILES = {
    "300308": ("inn", "l3-inn-financials-quarterly", "l3-inn-dynamic"),
    "300502": ("nev", "l3-nev-financials-quarterly", "l3-nev-dynamic"),
    "300394": ("tf", "l3-tf-financials-quarterly", "l3-tf-dynamic"),
    "688008": ("ran", "l3-ran-financials-quarterly", "l3-ran-dynamic"),
    "002837": ("env", "l3-env-financials-quarterly", "l3-env-dynamic"),
}

# probe_key: (engine, 频次, batch_id, t0_source_id, update_trigger?, model_tier?, stale_days?)
# batch_id from §2.11.3; defaults derived below

INN = {
    "inn_1.6t_shipment": ("DeepSeek", "月", "inn-dynamic-monthly", "industry_news_supply"),
    "inn_nv_share": ("DeepSeek", "季", "inn-earnings-q", "cninfo_quarterly_pdf"),
    "inn_cpo_milestone": ("DeepSeek", "动", "inn-dynamic-daily", "cninfo_announcement_feed"),
    "inn_eml_laser_stock": ("DeepSeek", "月", "inn-supply-monthly", "upstream_eml_report"),
    "inn_gross_margin": ("Python", "季", "inn-earnings-q", "tushare_fina_indicator"),
    "inn_contract_liab": ("Python", "季", "inn-earnings-q", "tushare_balance_sheet"),
    "inn_raw_material": ("PyMuPDF", "季", "inn-earnings-q", "cninfo_quarterly_pdf"),
    "inn_tw_competitor": ("Playwright", "月", "inn-twse-monthly", "twse_peer_monthly_html"),
    "inn_yield_rate": ("DeepSeek", "动", "inn-dynamic-daily", "cninfo_announcement_feed"),
    "inn_inter_receivable": ("Python", "季", "inn-earnings-q", "tushare_fina_indicator"),
    "inn_cfo_ratio": ("Python", "季", "inn-earnings-q", "tushare_cashflow"),
    "inn_overseas_rev": ("PyMuPDF", "半年", "inn-earnings-semi", "cninfo_semi_annual_pdf"),
    "inn_rd_intensity": ("Python", "季", "inn-earnings-q", "tushare_fina_indicator"),
    "inn_mgmt_stock": ("Python+DeepSeek", "日", "inn-governance-daily", "cninfo_governance_announcement"),
    "inn_insider_sell": ("Python+DeepSeek", "日", "inn-governance-daily", "cninfo_governance_announcement"),
    "r_inn_entity_list": ("DeepSeek", "动", "inn-risk-dynamic", "bis_entity_list_feed"),
    "r_inn_cpo_delay": ("DeepSeek", "动", "inn-risk-dynamic", "customer_whitepaper_feed"),
    "r_inn_inventory_bad": ("PyMuPDF", "半年", "inn-earnings-semi", "cninfo_semi_annual_pdf"),
    "r_inn_ar_default": ("PyMuPDF", "半年", "inn-earnings-semi", "cninfo_semi_annual_pdf"),
    "r_inn_eml_cut": ("DeepSeek", "动", "inn-risk-dynamic", "upstream_eml_report"),
    "r_inn_insider_dump": ("Python+DeepSeek", "动", "inn-governance-dynamic", "cninfo_insider_announcement"),
}

NEV = {
    "nev_net_margin": ("Python", "季", "nev-earnings-q", "tushare_fina_indicator"),
    "nev_meta_share": ("DeepSeek", "动", "nev-dynamic-daily", "cninfo_announcement_feed"),
    "nev_thailand_cap": ("DeepSeek", "动", "nev-dynamic-daily", "cninfo_announcement_feed"),
    "nev_lpo_progress": ("DeepSeek", "动", "nev-dynamic-daily", "cninfo_announcement_feed"),
    "nev_gross_premium": ("Python", "季", "nev-earnings-q", "tushare_fina_indicator"),
    "nev_inventory_days": ("Python", "季", "nev-earnings-q", "tushare_fina_indicator"),
    "nev_contract_liab": ("Python", "季", "nev-earnings-q", "tushare_balance_sheet"),
    "nev_silicon_photon": ("DeepSeek", "动", "nev-dynamic-daily", "ofc_test_feedback"),
    "nev_cw_laser_cost": ("DeepSeek", "月", "nev-supply-monthly", "upstream_cw_laser_price"),
    "nev_fin_expense": ("Python", "季", "nev-earnings-q", "tushare_income"),
    "nev_top5_concen": ("PyMuPDF", "年", "nev-earnings-annual", "cninfo_annual_pdf"),
    "nev_sales_growth": ("Python", "季", "nev-earnings-q", "tushare_fina_indicator"),
    "nev_free_cash_flow": ("Python", "季", "nev-earnings-q", "tushare_cashflow"),
    "nev_fixed_asset": ("PyMuPDF", "季", "nev-earnings-q", "cninfo_quarterly_pdf"),
    "nev_insider_sell": ("Python+DeepSeek", "日", "nev-governance-daily", "cninfo_governance_announcement"),
    "r_nev_meta_delay": ("DeepSeek", "动", "nev-risk-dynamic", "meta_infrastructure_feed"),
    "r_nev_thai_tariff": ("DeepSeek", "动", "nev-risk-dynamic", "policy_news_feed"),
    "r_nev_lpo_fail": ("DeepSeek", "动", "nev-risk-dynamic", "oif_procurement_feed"),
    "r_nev_yield_crash": ("DeepSeek", "月", "nev-risk-monthly", "customer_complaint_feed"),
    "r_nev_talent_loss": ("DeepSeek", "动", "nev-risk-dynamic", "cninfo_announcement_feed"),
    "r_nev_patent_sue": ("Playwright", "动", "nev-risk-dynamic", "itc_337_announcement"),
}

TF = {
    "tf_engine_shipment": ("DeepSeek", "月", "tf-dynamic-monthly", "downstream_procurement_feed"),
    "tf_awg_fiber_ratio": ("DeepSeek", "季", "tf-dynamic-q", "industry_survey_feed"),
    "tf_gross_margin": ("Python", "季", "tf-earnings-q", "tushare_fina_indicator"),
    "tf_barrel_effect": ("DeepSeek", "月", "tf-dynamic-monthly", "customs_export_feed"),
    "tf_jiangxi_expansion": ("DeepSeek", "动", "tf-dynamic-daily", "cninfo_announcement_feed"),
    "tf_rd_capitalized": ("PyMuPDF", "季", "tf-earnings-q", "cninfo_quarterly_pdf"),
    "tf_contract_liab": ("Python", "季", "tf-earnings-q", "tushare_balance_sheet"),
    "tf_roic_premium": ("Python", "季", "tf-earnings-q", "tushare_fina_indicator"),
    "tf_mellanox_order": ("DeepSeek", "月", "tf-dynamic-monthly", "customs_import_feed"),
    "tf_inventory_write": ("PyMuPDF", "半年", "tf-earnings-semi", "cninfo_semi_annual_pdf"),
    "tf_capacity_util": ("DeepSeek", "月", "tf-dynamic-monthly", "production_utilization_feed"),
    "tf_employee_bonus": ("PyMuPDF", "年", "tf-earnings-annual", "cninfo_annual_pdf"),
    "tf_tax_credit": ("DeepSeek", "动", "tf-dynamic-daily", "tax_bureau_feed"),
    "tf_glass_lens_yield": ("DeepSeek", "月", "tf-dynamic-monthly", "quality_inspection_feed"),
    "tf_co_op_rnd": ("DeepSeek", "动", "tf-dynamic-daily", "oif_standard_feed"),
    "r_tf_downstream_inhouse": ("DeepSeek", "动", "tf-risk-dynamic", "cninfo_announcement_feed"),
    "r_tf_engine_stagnate": ("DeepSeek", "季", "tf-earnings-q", "cninfo_quarterly_pdf"),
    "r_tf_jiangxi_stop": ("DeepSeek", "动", "tf-risk-dynamic", "cninfo_announcement_feed"),
    "r_tf_mellanox_cut": ("DeepSeek", "季", "tf-risk-q", "customs_export_feed"),
    "r_tf_asset_impair": ("PyMuPDF", "年", "tf-earnings-annual", "cninfo_annual_pdf"),
    "r_tf_inventory_pile": ("PyMuPDF", "季", "tf-earnings-q", "cninfo_quarterly_pdf"),
    "r_tf_overseas_block": ("DeepSeek", "动", "tf-risk-dynamic", "cninfo_announcement_feed"),
}

RAN = {
    "ran_ddr5_rcon_ship": ("DeepSeek", "月", "ran-dynamic-monthly", "memory_shipment_feed"),
    "ran_cxl_mxc_node": ("DeepSeek", "动", "ran-dynamic-daily", "cninfo_announcement_feed"),
    "ran_pcie_retimer": ("DeepSeek", "动", "ran-dynamic-daily", "cninfo_announcement_feed"),
    "ran_gross_margin": ("Python", "季", "ran-earnings-q", "tushare_fina_indicator"),
    "ran_contract_liab": ("Python", "季", "ran-earnings-q", "tushare_balance_sheet"),
    "ran_inventory_turn": ("Python", "季", "ran-earnings-q", "tushare_fina_indicator"),
    "ran_jintide_server": ("Playwright", "动", "ran-bid-dynamic", "gov_procurement_bid"),
    "ran_rd_expense": ("Python", "季", "ran-earnings-q", "tushare_income"),
    "ran_aic_chip_test": ("DeepSeek", "动", "ran-dynamic-daily", "cninfo_announcement_feed"),
    "ran_cfo_health": ("Python", "季", "ran-earnings-q", "tushare_cashflow"),
    "ran_serdes_ip": ("DeepSeek", "动", "ran-dynamic-daily", "patent_bureau_feed"),
    "ran_rambus_patent": ("DeepSeek", "动", "ran-risk-dynamic", "patent_litigation_feed"),
    "ran_headcount_all": ("PyMuPDF", "年", "ran-earnings-annual", "cninfo_annual_pdf"),
    "ran_intel_platform": ("DeepSeek", "季", "ran-dynamic-q", "platform_roadmap_feed"),
    "ran_tsmc_wafer": ("DeepSeek", "月", "ran-supply-monthly", "tsmc_wafer_schedule"),
    "r_ran_rambus_share": ("DeepSeek", "季", "ran-risk-q", "rambus_earnings_feed"),
    "r_ran_tapeout_fail": ("DeepSeek", "半年", "ran-risk-semi", "rd_disclosure_feed"),
    "r_ran_jintide_zero": ("Playwright", "季", "ran-bid-q", "gov_procurement_bid"),
    "r_ran_rd_capital_bad": ("PyMuPDF", "年", "ran-earnings-annual", "cninfo_annual_pdf"),
}

ENV = {
    "env_liquid_win_rate": ("Playwright", "月", "env-bid-monthly", "chinabidding_liquid_cooling"),
    "env_oem_certs": ("Playwright", "动", "env-dynamic-daily", "oem_whitepaper_feed"),
    "env_al_cu_idx": ("Python", "日", "env-metal-daily", "shfe_cu_al_futures"),
    "env_coolant_ratio": ("Python+DeepSeek", "季", "env-earnings-q", "cninfo_quarterly_pdf"),
    "env_margin_pass": ("Python", "季", "env-earnings-q", "tushare_fina_indicator"),
    "env_cdu_share": ("DeepSeek", "年", "env-dynamic-annual", "ccid_idc_survey"),
    "env_ess_growth": ("PyMuPDF", "季", "env-earnings-q", "cninfo_quarterly_pdf"),
    "env_b2b_aging": ("PyMuPDF", "季", "env-earnings-q", "cninfo_quarterly_pdf"),
    "env_cfo_to_net": ("Python", "季", "env-earnings-q", "tushare_cashflow"),
    "env_warranty": ("PyMuPDF", "季", "env-earnings-q", "cninfo_quarterly_pdf"),
    "env_inv_structure": ("PyMuPDF", "季", "env-earnings-q", "cninfo_quarterly_pdf"),
    "env_immersion_rd": ("DeepSeek", "动", "env-dynamic-daily", "cninfo_announcement_feed"),
    "env_client_top5": ("PyMuPDF", "季", "env-earnings-q", "cninfo_quarterly_pdf"),
    "env_goodwill_imp": ("Python", "季", "env-earnings-q", "tushare_balance_sheet"),
}

SPECS = {
    "300308": INN,
    "300502": NEV,
    "300394": TF,
    "688008": RAN,
    "002837": ENV,
}

JOB_FOR_BATCH = {
    "inn-earnings-q": "l3-inn-financials-quarterly",
    "inn-earnings-semi": "l3-inn-financials-quarterly",
    "inn-dynamic-daily": "l3-inn-dynamic",
    "inn-dynamic-monthly": "l3-inn-dynamic",
    "inn-supply-monthly": "l3-inn-dynamic",
    "inn-twse-monthly": "l3-inn-dynamic",
    "inn-governance-daily": "l3-inn-dynamic",
    "inn-governance-dynamic": "l3-inn-dynamic",
    "inn-risk-dynamic": "l3-inn-dynamic",
    "nev-earnings-q": "l3-nev-financials-quarterly",
    "nev-earnings-annual": "l3-nev-financials-quarterly",
    "nev-dynamic-daily": "l3-nev-dynamic",
    "nev-supply-monthly": "l3-nev-dynamic",
    "nev-governance-daily": "l3-nev-dynamic",
    "nev-risk-dynamic": "l3-nev-dynamic",
    "nev-risk-monthly": "l3-nev-dynamic",
    "tf-earnings-q": "l3-tf-financials-quarterly",
    "tf-earnings-semi": "l3-tf-financials-quarterly",
    "tf-earnings-annual": "l3-tf-financials-quarterly",
    "tf-dynamic-daily": "l3-tf-dynamic",
    "tf-dynamic-monthly": "l3-tf-dynamic",
    "tf-dynamic-q": "l3-tf-dynamic",
    "tf-risk-dynamic": "l3-tf-dynamic",
    "tf-risk-q": "l3-tf-dynamic",
    "ran-earnings-q": "l3-ran-financials-quarterly",
    "ran-earnings-annual": "l3-ran-financials-quarterly",
    "ran-dynamic-daily": "l3-ran-dynamic",
    "ran-dynamic-monthly": "l3-ran-dynamic",
    "ran-dynamic-q": "l3-ran-dynamic",
    "ran-supply-monthly": "l3-ran-dynamic",
    "ran-bid-dynamic": "l3-ran-dynamic",
    "ran-bid-q": "l3-ran-dynamic",
    "ran-risk-dynamic": "l3-ran-dynamic",
    "ran-risk-q": "l3-ran-dynamic",
    "ran-risk-semi": "l3-ran-dynamic",
    "env-earnings-q": "l3-env-financials-quarterly",
    "env-bid-monthly": "l3-env-bid-monthly",
    "env-metal-daily": "l3-env-metal-daily",
    "env-dynamic-daily": "l3-env-dynamic",
    "env-dynamic-annual": "l3-env-dynamic",
}


def trigger_for(sig: str, cadence: str, batch: str) -> str:
    if sig in ("semantic", "hybrid") and cadence == "dynamic":
        return "event_driven"
    if sig == "semantic" and "dynamic" in batch:
        return "event_driven"
    if sig in ("semantic", "hybrid") and "earnings" in batch:
        return "event_driven"
    if sig in ("semantic", "hybrid") and batch.endswith("-risk-dynamic"):
        return "event_driven"
    if cadence == "daily" and "metal" in batch:
        return "cron"
    return "cron"


def cache_group_for(batch: str, t0: str, sig: str) -> str:
    if sig in ("semantic", "hybrid") and "risk" not in batch:
        if "dynamic" in batch or "earnings" in batch:
            return batch
    if sig == "semantic" and "risk" in batch:
        return batch
    if t0.startswith("tushare"):
        return t0
    if "cninfo" in t0:
        return batch if "earnings" in batch or "semi" in batch or "annual" in batch else t0
    return batch if "dynamic" in batch else t0


def build_probe(key: str, spec: tuple) -> dict:
    engine, freq, batch, t0 = spec[:4]
    sig, pipeline = ENGINE[engine]
    cadence, stale = CADENCE[freq]
    ut = trigger_for(sig, cadence, batch)
    job = JOB_FOR_BATCH.get(batch, "l3-unknown")
    if batch == "env-metal-daily":
        job = "l3-env-metal-daily"
    elif batch == "env-bid-monthly":
        job = "l3-env-bid-monthly"

    entry = {
        "signal_type": sig,
        "t1_pipeline": pipeline,
        "update_trigger": ut,
        "batch_id": batch,
        "cache_group": cache_group_for(batch, t0, sig),
        "job_id": job,
        "t0_source_id": t0,
        "cadence": cadence,
        "stale_days": stale,
    }
    if sig in ("semantic", "hybrid"):
        entry["model_tier"] = "pro_required" if key.startswith("r_") and "risk" in batch else "flash"
    return entry


JL4 = yaml.safe_load((OUT / "601138.yaml").read_text())["jl4_probes"]
JL4_BATCH = yaml.safe_load((OUT / "601138.yaml").read_text())["batch_groups"]
# keep only jl4 batches from 601138
JL4_BATCH = {k: v for k, v in JL4_BATCH.items() if k.startswith("jl4")}


def build_batch_groups(l3):
    groups = {}
    for key, p in l3.items():
        bid = p["batch_id"]
        cg = p["cache_group"]
        gkey = cg
        if gkey not in groups:
            cache_kind = "deepsea_context" if p["t1_pipeline"] in ("deepsea_semantic", "hybrid_merge") else (
                "tushare_api" if "tushare" in p["t0_source_id"] else "structured_parse"
            )
            groups[gkey] = {
                "update_trigger": p["update_trigger"],
                "job_id": p["job_id"],
                "cache_kind": cache_kind,
                "probe_keys": [],
            }
            if p.get("model_tier") == "pro_required":
                groups[gkey]["model_tier"] = "pro_required"
            if cache_kind == "tushare_api":
                groups[gkey]["t0_source_id"] = p["t0_source_id"]
        if key not in groups[gkey]["probe_keys"]:
            groups[gkey]["probe_keys"].append(key)
    return groups


def main() -> None:
    for symbol, probes in SPECS.items():
        prefix = PROFILES[symbol][0]
        l3 = {k: build_probe(k, v) for k, v in probes.items()}
        batch_groups = build_batch_groups(l3)
        batch_groups.update(copy.deepcopy(JL4_BATCH))

        doc = {
            "registry_version": "1.0",
            "symbol": symbol,
            "profile": symbol,
            "prefix": prefix,
            "l3_probes": l3,
            "jl4_probes": copy.deepcopy(JL4),
            "batch_groups": batch_groups,
        }
        path = OUT / f"{symbol}.yaml"
        header = (
            f"# Probe 实现注册表 · {symbol}\n"
            f"# [Ref: 28_ §2.13] — Cursor/CI 实现路由的机器真相源\n"
            f"# update_trigger: event_driven | cron | intraday\n"
            f"# t1_pipeline: python_hard | pymupdf_structured | playwright_structured | deepsea_semantic | hybrid_merge\n\n"
        )
        path.write_text(header + yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False))
        print(f"Wrote {path} l3={len(l3)} batches={len(batch_groups)}")


if __name__ == "__main__":
    main()
