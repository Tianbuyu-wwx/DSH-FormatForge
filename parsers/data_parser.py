"""
数据文件解析器
支持解析 JSON、YAML、XML 等结构化数据格式
提取键值对、层级结构和表格数据
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

from parsers import BaseParser
from core.models import PageContent, ExtractedElement

logger = logging.getLogger("parsers.data")

# 可选依赖
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.warning("PyYAML 库未安装，YAML 解析功能不可用")

try:
    from xml.etree import ElementTree as ET
    XML_AVAILABLE = True
except ImportError:
    XML_AVAILABLE = False
    logger.warning("xml.etree 不可用，XML 解析功能受限")


class DataParser(BaseParser):
    """结构化数据文件解析器（JSON/YAML/XML）"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".json", ".yaml", ".yml", ".xml"]

    @property
    def supported_magic(self) -> List[bytes]:
        return [
            b"{",           # JSON 对象
            b"[",           # JSON 数组
            b"<?xml",       # XML 声明
            b"<!DOCTYPE",   # XML DOCTYPE
        ]

    def parse(self, file_path: Path) -> List[PageContent]:
        """解析数据文件"""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        if ext == '.json':
            return self._parse_json(file_path)
        elif ext in ('.yaml', '.yml'):
            return self._parse_yaml(file_path)
        elif ext == '.xml':
            return self._parse_xml(file_path)
        else:
            # 尝试自动检测格式
            return self._parse_auto(file_path)

    def _parse_json(self, file_path: Path) -> List[PageContent]:
        """解析 JSON 文件"""
        logger.info("开始解析 JSON: %s", file_path)

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败: %s", e)
            raise ValueError(f"JSON 解析失败: {e}")
        except Exception as e:
            logger.error("无法读取 JSON 文件: %s", e)
            raise ValueError(f"无法读取 JSON 文件: {e}")

        elements = []
        raw_lines = []

        # 格式化 JSON 内容
        formatted = json.dumps(data, ensure_ascii=False, indent=2)
        raw_lines.append(formatted)

        # 提取结构化数据
        if isinstance(data, dict):
            elements.extend(self._extract_dict_elements(data, "root"))
        elif isinstance(data, list):
            elements.extend(self._extract_list_elements(data, "root"))

        # 添加整体 JSON 元素
        elements.insert(0, ExtractedElement(
            elementId="elem_1_json",
            elementType="code",
            content=formatted,
            metadata={
                "format": "json",
                "type": type(data).__name__,
                "top_keys": list(data.keys())[:10] if isinstance(data, dict) else None,
                "item_count": len(data) if isinstance(data, list) else None
            }
        ))

        logger.info("JSON 解析完成: %d 个元素", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=False,
            hasTable=isinstance(data, list) and len(data) > 0
        )]

    def _parse_yaml(self, file_path: Path) -> List[PageContent]:
        """解析 YAML 文件"""
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML 库未安装，无法解析 YAML 文件")

        logger.info("开始解析 YAML: %s", file_path)

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error("YAML 解析失败: %s", e)
            raise ValueError(f"YAML 解析失败: {e}")
        except Exception as e:
            logger.error("无法读取 YAML 文件: %s", e)
            raise ValueError(f"无法读取 YAML 文件: {e}")

        elements = []
        raw_lines = []

        # 格式化 YAML 内容
        formatted = yaml.dump(data, allow_unicode=True, default_flow_style=False)
        raw_lines.append(formatted)

        # 提取结构化数据
        if isinstance(data, dict):
            elements.extend(self._extract_dict_elements(data, "root"))
        elif isinstance(data, list):
            elements.extend(self._extract_list_elements(data, "root"))

        elements.insert(0, ExtractedElement(
            elementId="elem_1_yaml",
            elementType="code",
            content=formatted,
            metadata={
                "format": "yaml",
                "type": type(data).__name__ if data is not None else "null"
            }
        ))

        logger.info("YAML 解析完成: %d 个元素", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=False,
            hasTable=isinstance(data, list) and len(data) > 0
        )]

    def _parse_xml(self, file_path: Path) -> List[PageContent]:
        """解析 XML 文件"""
        logger.info("开始解析 XML: %s", file_path)

        try:
            tree = ET.parse(str(file_path))
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error("XML 解析失败: %s", e)
            raise ValueError(f"XML 解析失败: {e}")
        except Exception as e:
            logger.error("无法读取 XML 文件: %s", e)
            raise ValueError(f"无法读取 XML 文件: {e}")

        elements = []
        raw_lines = []

        # 格式化 XML 内容
        formatted = ET.tostring(root, encoding='unicode')
        raw_lines.append(formatted)

        # 提取 XML 结构
        elements.extend(self._extract_xml_elements(root))

        elements.insert(0, ExtractedElement(
            elementId="elem_1_xml",
            elementType="code",
            content=formatted,
            metadata={
                "format": "xml",
                "root_tag": root.tag,
                "root_attribs": dict(root.attrib)
            }
        ))

        logger.info("XML 解析完成: %d 个元素", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=False,
            hasTable=False
        )]

    def _parse_auto(self, file_path: Path) -> List[PageContent]:
        """自动检测格式并解析"""
        try:
            return self._parse_json(file_path)
        except:
            pass

        if YAML_AVAILABLE:
            try:
                return self._parse_yaml(file_path)
            except:
                pass

        try:
            return self._parse_xml(file_path)
        except:
            pass

        raise ValueError(f"无法自动检测文件格式: {file_path}")

    def _extract_dict_elements(self, data: dict, prefix: str) -> List[ExtractedElement]:
        """从字典提取元素"""
        elements = []
        for idx, (key, value) in enumerate(data.items()):
            elem_id = f"elem_1_{prefix}_{idx}"
            if isinstance(value, (dict, list)):
                content = f"{key}: [{type(value).__name__}]"
                elem_type = "table" if isinstance(value, list) else "heading"
            else:
                content = f"{key}: {value}"
                elem_type = "text"

            elements.append(ExtractedElement(
                elementId=elem_id,
                elementType=elem_type,
                content=content,
                metadata={
                    "key": key,
                    "value_type": type(value).__name__,
                    "value": value if not isinstance(value, (dict, list)) else None
                }
            ))

            # 递归提取嵌套结构
            if isinstance(value, dict):
                elements.extend(self._extract_dict_elements(value, f"{prefix}_{key}"))
            elif isinstance(value, list):
                elements.extend(self._extract_list_elements(value, f"{prefix}_{key}"))

        return elements

    def _extract_list_elements(self, data: list, prefix: str) -> List[ExtractedElement]:
        """从列表提取元素"""
        elements = []
        for idx, item in enumerate(data[:50]):  # 限制数量避免过大
            elem_id = f"elem_1_{prefix}_item{idx}"
            if isinstance(item, dict):
                # 将字典格式化为表格行
                row_text = " | ".join(f"{k}={v}" for k, v in item.items())
                elements.append(ExtractedElement(
                    elementId=elem_id,
                    elementType="table_row",
                    content=row_text,
                    metadata={"index": idx, "item": item}
                ))
            else:
                elements.append(ExtractedElement(
                    elementId=elem_id,
                    elementType="list",
                    content=str(item),
                    metadata={"index": idx}
                ))

        return elements

    def _extract_xml_elements(self, element: "ET.Element", depth: int = 0) -> List[ExtractedElement]:
        """从 XML 元素提取结构"""
        elements = []

        # 元素标签和属性
        tag_info = f"<{element.tag}>"
        if element.attrib:
            tag_info += f" attribs={dict(element.attrib)}"

        elements.append(ExtractedElement(
            elementId=f"elem_1_xml_{element.tag}_{depth}",
            elementType="heading",
            content=tag_info,
            metadata={
                "tag": element.tag,
                "attribs": dict(element.attrib),
                "depth": depth
            }
        ))

        # 文本内容
        if element.text and element.text.strip():
            elements.append(ExtractedElement(
                elementId=f"elem_1_xml_text_{depth}",
                elementType="text",
                content=element.text.strip(),
                metadata={"depth": depth}
            ))

        # 递归子元素
        for child in element:
            elements.extend(self._extract_xml_elements(child, depth + 1))

        return elements
