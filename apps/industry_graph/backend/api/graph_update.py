# apps/industry_graph/backend/api/graph_update.py
"""图谱更新 API"""

from fastapi import APIRouter, HTTPException
from ..engine import neo4j_client

router = APIRouter(prefix="/api/graph/update", tags=["graph"])


@router.post("/node", summary="创建或更新节点")
async def upsert_node(node_data: dict):
    """创建或更新产业图谱节点"""
    query = """
    MERGE (n {id: $id})
    SET n += $props
    SET n.updated_at = timestamp()
    RETURN n
    """
    try:
        records = await neo4j_client.run_cypher(
            query, {"id": node_data["id"], "props": node_data}
        )
        return {"status": "ok", "node": dict(records[0].get("n", {}))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edge", summary="创建关系边")
async def create_edge(edge_data: dict):
    """创建产业图谱关系边"""
    query = """
    MATCH (a {id: $from_id}), (b {id: $to_id})
    MERGE (a)-[r:""" + edge_data.get("type", "SUPPLIES") + """]->(b)
    SET r += $props
    RETURN type(r) as type, properties(r) as props
    """
    try:
        records = await neo4j_client.run_cypher(
            query,
            {
                "from_id": edge_data["from_id"],
                "to_id": edge_data["to_id"],
                "props": edge_data.get("props", {}),
            },
        )
        return {"status": "ok", "edge": dict(records[0]) if records else {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
