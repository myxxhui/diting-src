# apps/industry_graph/backend/api/graph_snapshot.py
"""图谱快照 API"""

from fastapi import APIRouter
from ..engine import neo4j_client

router = APIRouter(prefix="/api/graph/snapshot", tags=["graph"])


@router.get("/stats", summary="图谱统计信息")
async def graph_stats():
    """获取当前图谱统计"""
    queries = {
        "total_nodes": "MATCH (n) RETURN count(n) as count",
        "sector_count": "MATCH (n:Sector) RETURN count(n) as count",
        "industry_node_count": "MATCH (n:IndustryNode) RETURN count(n) as count",
        "company_count": "MATCH (n:Company) RETURN count(n) as count",
        "policy_count": "MATCH (n:Policy) RETURN count(n) as count",
        "total_edges": "MATCH ()-[r]->() RETURN count(r) as count",
    }
    stats = {}
    for key, query in queries.items():
        records = await neo4j_client.run_cypher(query)
        stats[key] = records[0]["count"] if records else 0
    return stats
