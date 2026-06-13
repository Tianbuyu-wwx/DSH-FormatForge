"""
输出模板引擎
提供面向常见 AI 消费场景的预定义输出模板
"""
import re
from typing import Any


def _to_openai_messages(content: str, structured_data: dict | None = None, file_name: str = "") -> dict[str, Any]:
    """转换为 OpenAI Chat API 的 messages 格式"""
    return {
        "messages": [
            {
                "role": "system",
                "content": "以下是从文档中提取的内容，请根据用户后续指令进行处理。",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": content,
                    }
                ],
            },
        ]
    }


def _to_rag_chunks(content: str, structured_data: dict | None = None, file_name: str = "") -> dict[str, Any]:
    """按段落切分为适合向量检索的文档块"""
    chunks = content.split("\n\n")
    result = []
    for i, chunk in enumerate(chunks):
        cleaned = chunk.strip()
        if not cleaned:
            continue
        result.append({
            "chunk_id": i,
            "text": cleaned,
            "metadata": {
                "source": file_name,
                "chunk_index": i,
            },
        })
    return {"chunks": result, "total_chunks": len(result)}


def _to_vector_db(content: str, structured_data: dict | None = None, file_name: str = "") -> dict[str, Any]:
    """生成适合 Milvus/Pinecone/Weaviate 导入的格式"""
    chunks = content.split("\n\n")
    result = []
    for i, chunk in enumerate(chunks):
        cleaned = chunk.strip()
        if not cleaned:
            continue
        result.append({
            "id": f"{file_name or 'doc'}_chunk_{i}",
            "text": cleaned,
            "metadata": {
                "source": file_name,
                "chunk_index": i,
                "chunk_length": len(cleaned),
                "timestamp": None,
                "doc_type": "text",
            },
        })
    return {"vectors": result, "total_vectors": len(result)}


def _to_langchain_doc(content: str, structured_data: dict | None = None, file_name: str = "") -> dict[str, Any]:
    """转换为 LangChain Document 对象格式 (JSON)"""
    return {
        "documents": [
            {
                "page_content": content,
                "metadata": {
                    "source": file_name,
                    "content_length": len(content),
                    "structured_data": structured_data,
                },
            }
        ]
    }


def _to_summary(content: str, structured_data: dict | None = None, file_name: str = "") -> dict[str, Any]:
    """提取文档结构和关键信息摘要"""
    sections = len(re.findall(r"^#+\s", content, re.MULTILINE))
    paragraphs = len([p for p in content.split("\n\n") if p.strip()])
    tables = 0
    if structured_data:
        tables = len(structured_data.get("tables", []))

    return {
        "summary": content[:500],
        "statistics": {
            "total_characters": len(content),
            "total_lines": len(content.split("\n")),
            "sections": sections,
            "paragraphs": paragraphs,
            "tables": tables,
        },
        "source": {"file_name": file_name},
    }


TEMPLATES: dict[str, dict[str, Any]] = {
    "openai_messages": {
        "name": "OpenAI Messages 格式",
        "description": "转换为 OpenAI Chat API 的 messages 格式",
        "icon": "chat",
        "transform": _to_openai_messages,
    },
    "rag_chunks": {
        "name": "RAG 文档切片",
        "description": "按段落/章节切分为适合向量检索的文档块",
        "icon": "document",
        "transform": _to_rag_chunks,
    },
    "vector_db": {
        "name": "向量数据库导入",
        "description": "生成适合 Milvus/Pinecone/Weaviate 导入的格式",
        "icon": "database",
        "transform": _to_vector_db,
    },
    "langchain_doc": {
        "name": "LangChain Document",
        "description": "转换为 LangChain Document 对象格式 (JSON)",
        "icon": "chain",
        "transform": _to_langchain_doc,
    },
    "summary": {
        "name": "智能摘要",
        "description": "提取文档结构和关键信息摘要",
        "icon": "summary",
        "transform": _to_summary,
    },
}


def get_template_list() -> list[dict[str, Any]]:
    """获取模板列表（不含 transform 函数）"""
    return [
        {
            "id": key,
            "name": tmpl["name"],
            "description": tmpl["description"],
            "icon": tmpl["icon"],
        }
        for key, tmpl in TEMPLATES.items()
    ]


def apply_template(
    template_name: str,
    content: str,
    structured_data: dict | None = None,
    file_name: str = "",
) -> dict[str, Any]:
    """
    使用指定模板对内容进行转换

    Args:
        template_name: 模板标识名
        content: 转换后的文本内容
        structured_data: 结构化数据
        file_name: 文件名

    Returns:
        模板转换后的结果

    Raises:
        ValueError: 模板不存在时抛出
    """
    tmpl = TEMPLATES.get(template_name)
    if not tmpl:
        raise ValueError(f"未知的模板: {template_name}，可用模板: {', '.join(TEMPLATES.keys())}")

    transform_fn = tmpl["transform"]
    return transform_fn(content, structured_data, file_name)