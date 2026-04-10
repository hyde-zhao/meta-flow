#!/usr/bin/env python3
"""MCP 知识库查询客户端

为 MFQ 测试用例设计工具提供知识库查询能力。
首版仅定义查询契约，实际 MCP 服务端需后续开发。

用法:
    python scripts/mcp_query_client.py --query "日志中心 应用场景" --type scenario
    python scripts/mcp_query_client.py --query "日志中心 功能点" --type feature
    python scripts/mcp_query_client.py --query "防火墙 部署方案" --type deployment
"""
import argparse
import json
import sys
import os


# --- 查询类型定义 ---
QUERY_TYPES = {
    "scenario": {
        "description": "典型应用场景查询",
        "fields": ["scenario_name", "description", "trigger", "flow", "exceptions"],
    },
    "feature": {
        "description": "特性/功能点信息查询",
        "fields": ["feature_name", "description", "modules", "dependencies"],
    },
    "deployment": {
        "description": "部署方案查询",
        "fields": ["scenario", "topology", "requirements", "constraints"],
    },
    "coupling": {
        "description": "特性间耦合关系查询",
        "fields": ["source_feature", "target_feature", "coupling_type", "description"],
    },
}


class MCPClient:
    """MCP 知识库查询客户端。"""

    def __init__(self, endpoint: str = None, api_key: str = None):
        self.endpoint = endpoint or os.getenv("MCP_ENDPOINT", "")
        self.api_key = api_key or os.getenv("MCP_API_KEY", "")
        self.connected = False

    def connect(self) -> bool:
        """尝试连接 MCP 服务端。"""
        if not self.endpoint:
            print("MCP 服务端未配置（MCP_ENDPOINT 未设置）", file=sys.stderr)
            return False

        # 首版：仅检查配置是否存在
        # 后续版本实现实际的连接握手
        try:
            # TODO: 实现实际的 MCP 连接逻辑
            # import requests
            # resp = requests.get(f"{self.endpoint}/health", timeout=5)
            # self.connected = resp.status_code == 200
            print(f"MCP 服务端配置：{self.endpoint}")
            print("注意：首版 MCP 客户端仅定义查询契约，实际连接待开发")
            self.connected = False
            return False
        except Exception as e:
            print(f"MCP 连接失败：{e}", file=sys.stderr)
            self.connected = False
            return False

    def query(self, query_text: str, query_type: str = "scenario") -> dict:
        """
        执行知识库查询。

        Args:
            query_text: 查询文本
            query_type: 查询类型（scenario/feature/deployment/coupling）

        Returns:
            查询结果字典，包含 hits 和 metadata
        """
        if query_type not in QUERY_TYPES:
            print(f"不支持的查询类型：{query_type}", file=sys.stderr)
            print(f"可用类型：{', '.join(QUERY_TYPES.keys())}", file=sys.stderr)
            return {"hits": [], "source": "error"}

        result = {
            "query": query_text,
            "type": query_type,
            "type_description": QUERY_TYPES[query_type]["description"],
            "expected_fields": QUERY_TYPES[query_type]["fields"],
            "hits": [],
            "source": "none",
            "fallback_suggestion": "web_search",
        }

        if self.connected:
            # TODO: 实际查询逻辑
            # response = requests.post(
            #     f"{self.endpoint}/query",
            #     json={"text": query_text, "type": query_type},
            #     headers={"Authorization": f"Bearer {self.api_key}"},
            # )
            # result["hits"] = response.json().get("results", [])
            # result["source"] = "mcp"
            pass
        else:
            result["source"] = "none"
            result["message"] = "MCP 未连接，建议使用 Web 搜索获取信息"
            result["web_search_keywords"] = _generate_search_keywords(query_text, query_type)

        return result


def _generate_search_keywords(query_text: str, query_type: str) -> list:
    """生成 Web 搜索关键词建议。"""
    base_keywords = [query_text]

    type_prefixes = {
        "scenario": ["华为防火墙", "应用场景", "NGFW"],
        "feature": ["华为防火墙", "功能特性", "技术规格"],
        "deployment": ["华为防火墙", "部署方案", "组网方案"],
        "coupling": ["华为防火墙", "特性依赖", "功能关联"],
    }

    prefixes = type_prefixes.get(query_type, [])
    keywords = []
    for prefix in prefixes:
        keywords.append(f"{prefix} {query_text}")
    keywords.append(f"Huawei firewall {query_text}")

    return keywords


def main():
    parser = argparse.ArgumentParser(description="MCP 知识库查询客户端")
    parser.add_argument("--query", "-q", required=True, help="查询文本")
    parser.add_argument("--type", "-t", default="scenario",
                        choices=list(QUERY_TYPES.keys()),
                        help="查询类型（默认：scenario）")
    parser.add_argument("--endpoint", default=None, help="MCP 服务端地址")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径（JSON）")
    parser.add_argument("--list-types", action="store_true", help="列出支持的查询类型")

    args = parser.parse_args()

    if args.list_types:
        print("支持的查询类型：")
        for k, v in QUERY_TYPES.items():
            print(f"  {k}: {v['description']}")
            print(f"    字段: {', '.join(v['fields'])}")
        return

    client = MCPClient(endpoint=args.endpoint)
    client.connect()
    result = client.query(args.query, args.type)

    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"查询结果已保存到：{args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
