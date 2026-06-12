"""
AI 提示词管理器
负责构建AI转换提示词、解析AI响应、执行AI增强转换
"""
import json
import re
import logging
from typing import Dict, Any, Optional

from core.models import OutputFormat


logger = logging.getLogger("ai_prompt_manager")


class AIPromptManager:
    """
    AI 提示词管理器

    职责：
    1. 构建结构化的AI转换提示词
    2. 解析AI响应（JSON提取、结构化解析）
    3. 执行AI增强转换
    """

    def __init__(self, ai_client: Optional[Any] = None):
        self.ai_client = ai_client
        logger.debug("AIPromptManager 初始化完成, ai_client=%s", "可用" if ai_client else "不可用")

    def build_prompt(
        self,
        file_name: str,
        file_type: str,
        base_content: str,
        output_format: OutputFormat,
        custom_prompt: Optional[str] = None
    ) -> str:
        """构建AI转换提示词"""
        format_instruction = {
            OutputFormat.JSON: "输出有效的JSON格式",
            OutputFormat.MARKDOWN: "输出Markdown格式",
            OutputFormat.TEXT: "输出纯文本格式",
            OutputFormat.HTML: "输出HTML格式"
        }.get(output_format, "输出结构化文本")

        prompt = f"""你是一个数据转换专家。请将以下从 {file_type} 文件中提取的内容转换为AI可理解和处理的标准格式。

## 文件信息
- 文件名: {file_name}
- 文件类型: {file_type}

## 提取的原始内容

```
{base_content[:4000]}
```

{"(内容已截断，仅显示前4000字符)" if len(base_content) > 4000 else ""}

## 转换要求

1. {format_instruction}
2. 保留所有关键信息和数据
3. 对不完整或模糊的内容进行合理推断
4. 识别并标注内容类型（标题、段落、表格、列表等）
5. 保持内容的层级结构

## 输出格式

{"请输出JSON格式，包含 'content' 和 'structured_data' 字段" if output_format == OutputFormat.JSON else "请直接输出转换后的内容"}

{custom_prompt if custom_prompt else ""}

请直接输出转换结果，不要添加额外说明。"""

        return prompt

    def parse_response(self, response_text: str, output_format: OutputFormat) -> Dict[str, Any]:
        """解析AI响应"""
        result = {"content": response_text, "structured_data": None}

        if output_format == OutputFormat.JSON:
            try:
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = response_text.strip()

                parsed = json.loads(json_str)
                result["structured_data"] = parsed
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("JSON解析失败: %s", e)

        return result

    def enhance_convert(
        self,
        parsed_file: Any,
        base_content: str,
        output_format: OutputFormat,
        custom_prompt: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """使用AI增强转换"""
        if not self.ai_client:
            logger.debug("AI客户端不可用，跳过增强转换")
            return None

        prompt = self.build_prompt(
            file_name=parsed_file.fileName,
            file_type=parsed_file.fileType.value,
            base_content=base_content,
            output_format=output_format,
            custom_prompt=custom_prompt
        )

        logger.info("调用AI增强转换: file=%s, prompt_length=%d", parsed_file.fileName, len(prompt))
        response_text = self.ai_client.generate_text(prompt)
        logger.info("AI响应长度: %d 字符", len(response_text))

        return self.parse_response(response_text, output_format)