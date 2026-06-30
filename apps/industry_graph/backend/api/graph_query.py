# apps/industry_graph/backend/api/graph_query.py
"""图谱查询 API — CRUD"""

from fastapi import APIRouter, HTTPException
from ..engine import neo4j_client
from ..models.graph_models import GraphResponse

router = APIRouter(prefix="/api/graph/query", tags=["graph"])


@router.get("/full", response_model=GraphResponse, summary="获取完整图谱")
async def get_full_graph(limit: int = 200):
    """获取全量图谱节点和边"""
    nodes_query = f"""
    MATCH (n)
    WHERE n:Sector OR n:SubSector OR n:IndustryNode OR n:Company
    RETURN n LIMIT {limit}
    """
    edges_query = """
    MATCH (a)-[r:SUPPLIES|PRODUCES|BELONGS_TO|AFFECTS|IMPACTS]->(b)
    RETURN a.id as source, b.id as target, type(r) as type,
           r.supply_ratio as supply_ratio, r.cost_ratio as cost_ratio,
           r.is_critical as is_critical
    LIMIT 500
    """
    nodes = await neo4j_client.run_cypher(nodes_query)
    edges = await neo4j_client.run_cypher(edges_query)

    return GraphResponse(
        nodes=[dict(n.get("n", {})) for n in nodes],
        edges=[dict(e) for e in edges],
    )


@router.get("/node/{node_id}", summary="获取节点详情")
async def get_node_detail(node_id: str):
    """获取单个节点及其邻居"""
    query = """
    MATCH (n {id: $node_id})
    OPTIONAL MATCH (n)-[r_out]->(down)
    OPTIONAL MATCH (up)-[r_in]->(n)
    RETURN n,
           collect(DISTINCT {node: down, type: type(r_out), props: properties(r_out)}) as downstream,
           collect(DISTINCT {node: up, type: type(r_in), props: properties(r_in)}) as upstream
    """
    records = await neo4j_client.run_cypher(query, {"node_id": node_id})
    if not records:
        raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")

    record = records[0]
    return {
        "node": dict(record.get("n", {})),
        "downstream": record.get("downstream", []),
        "upstream": record.get("upstream", []),
    }


@router.get("/chain/{node_id}", summary="获取节点所在产业链")
async def get_industry_chain(node_id: str):
    """获取节点所属完整产业链"""

    sector_query = """
    MATCH (n {id: $node_id})
    OPTIONAL MATCH (n)-[:BELONGS_TO*0..2]->(sector:Sector)
    RETURN coalesce(sector.name, '未归类') as sector_name
    """
    sector_records = await neo4j_client.run_cypher(
        sector_query, {"node_id": node_id}
    )
    sector_name = (
        sector_records[0].get("sector_name", "未归类") if sector_records else "未归类"
    )

    chain_query = """
    MATCH (n {id: $node_id})
    OPTIONAL MATCH path_up = (n)<-[:SUPPLIES*1..3]-(up)
    OPTIONAL MATCH path_down = (n)-[:SUPPLIES*1..3]->(down)
    RETURN n, path_up, path_down
    """
    records = await neo4j_client.run_cypher(chain_query, {"node_id": node_id})

    return {
        "node_id": node_id,
        "sector": sector_name,
        "raw": [dict(r) for r in records],
    }


@router.get("/search", summary="搜索节点")
async def search_nodes(q: str = "", node_type: str = ""):
    """按名称模糊搜索节点"""
    query = """
    MATCH (n)
    WHERE (n.name CONTAINS $q OR n.cn_name CONTAINS $q)
    """
    if node_type:
        query += f" AND n:{node_type}"
    query += " RETURN n LIMIT 20"

    records = await neo4j_client.run_cypher(query, {"q": q})
    return {"results": [dict(r.get("n", {})) for r in records]}
