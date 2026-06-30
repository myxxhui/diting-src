# apps/industry_graph/backend/engine/path_finder.py
"""N 度路径遍历引擎 — 从 Neo4j 查询受影响上下游"""

import logging
from .neo4j_client import run_cypher

logger = logging.getLogger(__name__)


async def find_downstream_paths(
    node_id: str, max_depth: int = 3
) -> list[dict]:
    """查找下游受影响路径（SUPPLIES 关系链）

    Args:
        node_id: 触发节点 ID
        max_depth: 最大遍历深度

    Returns:
        路径列表，每条含 path_chain + edge_properties
    """
    query = f"""
    MATCH path = (n {{id: $node_id}})-[r:SUPPLIES*1..{max_depth}]->(m)
    RETURN path,
           [rel IN relationships(path) | {{
               from: startNode(rel).id,
               to: endNode(rel).id,
               supply_ratio: rel.supply_ratio,
               cost_ratio: rel.cost_ratio,
               substitute_difficulty: rel.substitute_difficulty,
               pricing_power: rel.pricing_power,
               lead_time_days: rel.lead_time_days,
               is_critical: rel.is_critical
           }}] AS edges
    ORDER BY length(path)
    LIMIT 20
    """
    records = await run_cypher(query, {"node_id": node_id})

    paths = []
    for record in records:
        path = record.get("path", record.get("p"))
        nodes = [dict(n) for n in path.nodes]
        paths.append({
            "path_chain": [n.get("id", n.get("name", "?")) for n in nodes],
            "nodes": nodes,
            "edges": record.get("edges", []),
            "length": len(nodes) - 1,
        })
    return paths


async def find_upstream_paths(
    node_id: str, max_depth: int = 2
) -> list[dict]:
    """查找上游受影响路径（反向 SUPPLIES）"""
    query = f"""
    MATCH path = (n {{id: $node_id}})<-[r:SUPPLIES*1..{max_depth}]-(m)
    RETURN path,
           [rel IN relationships(path) | {{
               from: endNode(rel).id,
               to: startNode(rel).id,
               supply_ratio: rel.supply_ratio,
               cost_ratio: rel.cost_ratio,
               substitute_difficulty: rel.substitute_difficulty,
               is_critical: rel.is_critical
           }}] AS edges
    ORDER BY length(path)
    LIMIT 10
    """
    records = await run_cypher(query, {"node_id": node_id})
    paths = []
    for record in records:
        path = record.get("path", record.get("p"))
        nodes = [dict(n) for n in path.nodes]
        paths.append({
            "path_chain": [n.get("id", n.get("name", "?")) for n in nodes],
            "nodes": nodes,
            "edges": record.get("edges", []),
            "length": len(nodes) - 1,
        })
    return paths


async def find_node_neighbors(node_id: str, depth: int = 1) -> dict:
    """查找节点邻居（上下游 + 替代品 + 政策影响）"""
    downstream = await find_downstream_paths(node_id, depth)
    upstream = await find_upstream_paths(node_id, depth)
    return {"downstream": downstream, "upstream": upstream}
