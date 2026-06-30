# apps/industry_graph/backend/services/graph_seed.py
"""种子数据导入服务 — 锂电池产业链（15+ 节点、12+ 条边）"""

import logging
from ..engine.neo4j_client import run_cypher

logger = logging.getLogger(__name__)

SEED_DATA = [
    # ===== 清除旧数据 =====
    ("MATCH (n) DETACH DELETE n", {}),
    # ===== 一级产业 =====
    ("CREATE (:Sector {id:'new_energy', name:'新能源', cn_name:'新能源', description:'涵盖锂电/光伏/风电/储能'})", {}),
    # ===== 二级产业 =====
    ("CREATE (:SubSector {id:'lithium_chain', name:'锂电产业链', cn_name:'锂电产业链', parent_sector:'新能源'})", {}),
    # ===== 上游：锂矿/碳酸锂/六氟磷酸锂 =====
    ("CREATE (:IndustryNode {id:'lithium_ore', name:'锂辉石', cn_name:'锂辉石', sub_sector:'锂电', node_type:'raw_material', gross_margin:0.55, profit_elasticity:1.2, policy_sensitivity:'medium', moat_strength:7, market_concentration:0.80, domestic_self_sufficiency:0.40, typical_inventory_days:15, typical_contract_length_months:3, key_companies:['002460','002466','000762'], cost_structure:apoc.convert.toJson({material_pct:0.10, energy_pct:0.30, labor_pct:0.20, other_pct:0.40})})", {}),
    ("CREATE (:IndustryNode {id:'lithium_carbonate', name:'碳酸锂', cn_name:'碳酸锂', sub_sector:'锂电', node_type:'raw_material', gross_margin:0.35, profit_elasticity:0.8, policy_sensitivity:'high', moat_strength:6, market_concentration:0.55, domestic_self_sufficiency:0.65, typical_inventory_days:20, typical_contract_length_months:1, key_companies:['002460','002466','000792'], cost_structure:apoc.convert.toJson({material_pct:0.45, energy_pct:0.15, labor_pct:0.15, depreciation_pct:0.15, other_pct:0.10})})", {}),
    ("CREATE (:IndustryNode {id:'lipf6', name:'六氟磷酸锂', cn_name:'六氟磷酸锂(电解液原料)', sub_sector:'锂电', node_type:'raw_material', gross_margin:0.28, profit_elasticity:0.9, policy_sensitivity:'low', moat_strength:5, market_concentration:0.45, domestic_self_sufficiency:0.90, typical_inventory_days:15, typical_contract_length_months:1, key_companies:['002407','002709'], cost_structure:apoc.convert.toJson({material_pct:0.50, energy_pct:0.15, labor_pct:0.15, other_pct:0.20})})", {}),
    # ===== 中游：正极/负极/电解液/隔膜 =====
    ("CREATE (:IndustryNode {id:'cathode_material', name:'正极材料', cn_name:'正极材料', sub_sector:'锂电', node_type:'component', gross_margin:0.18, profit_elasticity:1.5, policy_sensitivity:'medium', moat_strength:5, market_concentration:0.40, domestic_self_sufficiency:0.85, typical_inventory_days:25, typical_contract_length_months:3, key_companies:['300750','300073','300769'], cost_structure:apoc.convert.toJson({material_pct:0.55, energy_pct:0.10, labor_pct:0.15, depreciation_pct:0.10, other_pct:0.10})})", {}),
    ("CREATE (:IndustryNode {id:'anode_material', name:'负极材料', cn_name:'负极材料', sub_sector:'锂电', node_type:'component', gross_margin:0.25, profit_elasticity:0.7, policy_sensitivity:'low', moat_strength:6, market_concentration:0.50, domestic_self_sufficiency:0.90, typical_inventory_days:30, typical_contract_length_months:3, key_companies:['603659','600884','300035'], cost_structure:apoc.convert.toJson({material_pct:0.30, energy_pct:0.20, labor_pct:0.20, other_pct:0.30})})", {}),
    ("CREATE (:IndustryNode {id:'electrolyte', name:'电解液', cn_name:'电解液', sub_sector:'锂电', node_type:'component', gross_margin:0.22, profit_elasticity:0.8, policy_sensitivity:'low', moat_strength:4, market_concentration:0.55, domestic_self_sufficiency:0.95, typical_inventory_days:20, typical_contract_length_months:1, key_companies:['002709','002407','300037'], cost_structure:apoc.convert.toJson({material_pct:0.60, energy_pct:0.10, labor_pct:0.10, other_pct:0.20})})", {}),
    ("CREATE (:IndustryNode {id:'separator', name:'隔膜', cn_name:'隔膜', sub_sector:'锂电', node_type:'component', gross_margin:0.40, profit_elasticity:0.4, policy_sensitivity:'low', moat_strength:7, market_concentration:0.65, domestic_self_sufficiency:0.85, typical_inventory_days:20, typical_contract_length_months:6, key_companies:['300568','002812'], cost_structure:apoc.convert.toJson({material_pct:0.20, energy_pct:0.15, depreciation_pct:0.35, labor_pct:0.15, other_pct:0.15})})", {}),
    # ===== 中游组装：电芯 =====
    ("CREATE (:IndustryNode {id:'battery_cell', name:'锂电池电芯', cn_name:'锂电池电芯', sub_sector:'锂电', node_type:'assembly', gross_margin:0.20, profit_elasticity:1.0, policy_sensitivity:'medium', moat_strength:6, market_concentration:0.60, domestic_self_sufficiency:0.90, typical_inventory_days:30, typical_contract_length_months:6, key_companies:['300750','002074','300014'], cost_structure:apoc.convert.toJson({material_pct:0.60, energy_pct:0.10, labor_pct:0.10, depreciation_pct:0.10, other_pct:0.10})})", {}),
    # ===== 下游：动力电池/储能/消费电子 =====
    ("CREATE (:IndustryNode {id:'power_battery', name:'动力电池包', cn_name:'动力电池包', sub_sector:'锂电', node_type:'end_product', gross_margin:0.18, profit_elasticity:0.9, policy_sensitivity:'high', moat_strength:7, market_concentration:0.70, domestic_self_sufficiency:0.95, typical_inventory_days:25, typical_contract_length_months:12, key_companies:['300750','002074'], cost_structure:apoc.convert.toJson({material_pct:0.55, energy_pct:0.10, labor_pct:0.10, r_d_pct:0.15, other_pct:0.10})})", {}),
    ("CREATE (:IndustryNode {id:'ev_manufacturer', name:'新能源整车', cn_name:'新能源整车', sub_sector:'锂电', node_type:'end_product', gross_margin:0.15, profit_elasticity:0.6, policy_sensitivity:'high', moat_strength:5, market_concentration:0.50, domestic_self_sufficiency:0.95, typical_inventory_days:30, typical_contract_length_months:12, key_companies:['002594','600104','000625','09868','01211'], cost_structure:apoc.convert.toJson({material_pct:0.40, energy_pct:0.05, labor_pct:0.15, r_d_pct:0.20, other_pct:0.20})})", {}),
    ("CREATE (:IndustryNode {id:'energy_storage', name:'储能系统', cn_name:'储能系统', sub_sector:'锂电', node_type:'end_product', gross_margin:0.22, profit_elasticity:0.7, policy_sensitivity:'high', moat_strength:4, market_concentration:0.30, domestic_self_sufficiency:0.90, typical_inventory_days:45, typical_contract_length_months:6, key_companies:['300750','300274','002121'], cost_structure:apoc.convert.toJson({material_pct:0.50, energy_pct:0.05, labor_pct:0.10, r_d_pct:0.20, other_pct:0.15})})", {}),
    # ===== 关系边 =====
    # 锂辉石 → 碳酸锂
    ("MATCH (a:IndustryNode {id:'lithium_ore'}), (b:IndustryNode {id:'lithium_carbonate'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.80, cost_ratio:0.40, substitute_difficulty:7, pricing_power:'upstream', lead_time_days:14, is_critical:true, contract_type:'quarterly'}]->(b)", {}),
    # 碳酸锂 → 正极材料
    ("MATCH (a:IndustryNode {id:'lithium_carbonate'}), (b:IndustryNode {id:'cathode_material'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.45, cost_ratio:0.55, substitute_difficulty:6, pricing_power:'upstream', lead_time_days:10, is_critical:true, contract_type:'quarterly'}]->(b)", {}),
    # 碳酸锂 → 电解液
    ("MATCH (a:IndustryNode {id:'lithium_carbonate'}), (b:IndustryNode {id:'electrolyte'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.15, cost_ratio:0.40, substitute_difficulty:5, pricing_power:'upstream', lead_time_days:7, is_critical:false, contract_type:'spot'}]->(b)", {}),
    # 六氟磷酸锂 → 电解液
    ("MATCH (a:IndustryNode {id:'lipf6'}), (b:IndustryNode {id:'electrolyte'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.60, cost_ratio:0.50, substitute_difficulty:8, pricing_power:'upstream', lead_time_days:10, is_critical:true, contract_type:'quarterly'}]->(b)", {}),
    # 正极材料 → 电芯
    ("MATCH (a:IndustryNode {id:'cathode_material'}), (b:IndustryNode {id:'battery_cell'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.40, cost_ratio:0.35, substitute_difficulty:5, pricing_power:'balanced', lead_time_days:14, is_critical:true, contract_type:'annual'}]->(b)", {}),
    # 负极材料 → 电芯
    ("MATCH (a:IndustryNode {id:'anode_material'}), (b:IndustryNode {id:'battery_cell'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.20, cost_ratio:0.12, substitute_difficulty:4, pricing_power:'balanced', lead_time_days:14, is_critical:false, contract_type:'annual'}]->(b)", {}),
    # 电解液 → 电芯
    ("MATCH (a:IndustryNode {id:'electrolyte'}), (b:IndustryNode {id:'battery_cell'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.15, cost_ratio:0.15, substitute_difficulty:6, pricing_power:'upstream', lead_time_days:10, is_critical:true, contract_type:'quarterly'}]->(b)", {}),
    # 隔膜 → 电芯
    ("MATCH (a:IndustryNode {id:'separator'}), (b:IndustryNode {id:'battery_cell'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.10, cost_ratio:0.08, substitute_difficulty:7, pricing_power:'upstream', lead_time_days:14, is_critical:false, contract_type:'annual'}]->(b)", {}),
    # 电芯 → 动力电池
    ("MATCH (a:IndustryNode {id:'battery_cell'}), (b:IndustryNode {id:'power_battery'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.70, cost_ratio:0.55, substitute_difficulty:6, pricing_power:'balanced', lead_time_days:21, is_critical:true, contract_type:'annual'}]->(b)", {}),
    # 电芯 → 储能
    ("MATCH (a:IndustryNode {id:'battery_cell'}), (b:IndustryNode {id:'energy_storage'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.30, cost_ratio:0.50, substitute_difficulty:5, pricing_power:'balanced', lead_time_days:21, is_critical:true, contract_type:'annual'}]->(b)", {}),
    # 动力电池 → 新能源整车
    ("MATCH (a:IndustryNode {id:'power_battery'}), (b:IndustryNode {id:'ev_manufacturer'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.35, cost_ratio:0.35, substitute_difficulty:4, pricing_power:'balanced', lead_time_days:14, is_critical:true, contract_type:'annual'}]->(b)", {}),
    # 动力电池 → 储能
    ("MATCH (a:IndustryNode {id:'power_battery'}), (b:IndustryNode {id:'energy_storage'}) CREATE (a)-[:SUPPLIES {supply_ratio:0.20, cost_ratio:0.30, substitute_difficulty:3, pricing_power:'balanced', lead_time_days:14, is_critical:false, contract_type:'annual'}]->(b)", {}),
]

async def seed_graph() -> dict:
    """导入种子数据到 Neo4j"""
    logger.info("开始导入锂电池产业链种子数据...")
    success = 0
    failed = 0

    for query, params in SEED_DATA:
        try:
            await run_cypher(query, params)
            success += 1
        except Exception as e:
            logger.warning(f"种子数据导入失败 [{query[:50]}...]: {e}")
            failed += 1

    logger.info(f"种子数据导入完成: 成功 {success}, 失败 {failed}")
    return {"success": success, "failed": failed}
