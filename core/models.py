"""
数据模型定义
AI 数据转换器 - 通用数据转换模型
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseCode(int, Enum):
    """响应状态码"""

    SUCCESS = 200
    PARAM_ERROR = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    TIMEOUT = 408
    SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503


class TaskStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ==================== 响应消息常量 ====================


class ResponseMsg:
    """统一响应消息常量"""

    # 成功
    SUCCESS = "操作成功"
    QUERY_SUCCESS = "查询成功"
    FILE_PARSE_SUCCESS = "文件解析成功"
    CONVERT_SUCCESS = "转换成功"
    AI_DISCOVER_SUCCESS = "AI能力发现成功"
    UPLOAD_SUCCESS = "上传成功"

    # 参数错误
    PARAM_ERROR_TEMPLATE = "参数错误: {}"
    UNSUPPORTED_FILE_TYPE = "不支持的文件类型: {}"
    FILE_TOO_LARGE = "文件大小超过限制"
    MISSING_REQUIRED_FIELD = "缺少必填参数"

    # 未找到
    CONVERT_TASK_NOT_FOUND = "转换任务不存在"
    PARSE_TASK_NOT_FOUND = "解析任务不存在"
    RESULT_NOT_FOUND = "转换结果不存在"

    # 服务器错误
    SERVER_ERROR_TEMPLATE = "服务器内部错误: {}"
    PARSE_FAILED = "解析失败"
    CONVERT_FAILED = "转换失败"
    CONVERT_FAILED_TEMPLATE = "转换失败: {}"
    PARSE_FAILED_TEMPLATE = "文件解析失败: {}"
    PROCESS_FAILED_TEMPLATE = "处理失败: {}"
    AI_DISCOVER_FAILED_TEMPLATE = "AI能力发现失败: {}"
    URL_DOMAIN_BLOCKED = "不允许访问的 URL 域名"


class ConversionType(str, Enum):
    """转换类型"""

    AUTO = "auto"
    TEXT = "text"
    STRUCTURED = "structured"
    IMAGE_DESC = "image_desc"
    TABLE = "table"
    OCR = "ocr"
    ENCODING = "encoding"


class OutputFormat(str, Enum):
    """输出格式"""

    AUTO = "auto"
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"


class FileType(str, Enum):
    """文件类型"""

    PPT = "ppt"
    PDF = "pdf"
    IMAGE = "image"
    DOC = "doc"  # Word 文档
    TXT = "txt"
    CSV = "csv"
    XLS = "xls"  # Excel 表格
    UNKNOWN = "unknown"


# ==================== 通用响应模型 ====================


class BaseResponse(BaseModel):
    """通用响应格式"""

    code: int = Field(default=200, description="状态码")
    msg: str = Field(default="操作成功", description="状态描述")
    data: dict[str, Any] | None = Field(default=None, description="业务数据")
    requestId: str = Field(description="请求唯一标识")


# ==================== 文件解析模块 ====================


class FileInfo(BaseModel):
    """文件信息"""

    fileName: str
    fileSize: int
    pageCount: int
    fileType: FileType = FileType.UNKNOWN


class ExtractedElement(BaseModel):
    """提取的元素"""

    elementId: str
    elementType: str = Field(description="元素类型: text, image, table, chart, heading, etc.")
    content: str
    position: dict[str, int] | None = None
    metadata: dict[str, Any] | None = None


class PageContent(BaseModel):
    """页面内容"""

    pageNumber: int
    elements: list[ExtractedElement]
    rawText: str
    hasImage: bool = False
    hasTable: bool = False


class ParsedFile(BaseModel):
    """解析后的文件数据"""

    parseId: str
    fileName: str
    fileSize: int
    pageCount: int
    fileType: FileType
    pages: list[PageContent]
    structure: dict[str, Any] | None = None
    createdAt: datetime
    status: TaskStatus
    filePath: str | None = None
    imagePaths: list[str] | None = None


# ==================== v2.2.0 ParsedDocument 中间文档 ====================


class DocBlock(BaseModel):
    """统一文档块（v2.2.0 引入，借鉴 DoclingDocument Element）

    表达任何文档元素（text / table / image / heading / code / formula）。
    与 ExtractedElement 的区别：DocBlock 用 type discriminator
    表达语义类型，并直接携带 paged 坐标（bbox）信息。
    """

    blockId: str
    type: str = Field(description="block 类型: text / heading / list / table / image / code / formula")
    text: str = Field(default="", description="块内纯文本（table 也可序列化为 markdown）")
    level: int = Field(default=0, description="heading/list 层级；其他类型忽略")
    bbox: dict[str, float] | None = Field(default=None, description="{x1, y1, x2, y2, page}")
    metadata: dict[str, Any] | None = None

    # Table-specific（仅当 type='table'）
    tableData: dict[str, Any] | None = Field(default=None, description="{'rows': [[...]], 'columns': [...]}")

    # Image-specific
    imagePath: str | None = None
    ocrText: str | None = None


class DocSection(BaseModel):
    """文档章节（v2.2.0 借鉴 DoclingDocument sections）"""

    sectionId: str
    title: str
    level: int = Field(default=1, description="层级 1/2/3，对应 heading")
    blocks: list[DocBlock] = Field(default_factory=list)
    children: list["DocSection"] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """v2.2.0 统一中间文档（双轨过渡期：与 ParsedFile 并存）

    设计目标（借鉴 DoclingDocument）：
    - 表达 text / tables / pictures / sections / furniture（header/footer）
    - 携带 layout 信息（bbox）
    - 携带 provenance（来源页、解析器）

    与现有 ParsedFile 的关系：
    - ParsedDocument 是规范化后的"内容视图"，与具体解析器解耦
    - ParsedFile 保留作为"解析原始结果"，可被 ParsedDocument.from_parsed_file() 转换
    - 上层策略（ConversionStrategy）应优先消费 ParsedDocument
    """

    documentId: str
    fileName: str
    fileType: str = Field(description="解析器报告的格式，如 'pdf' / 'docx' / 'xlsx'")
    pages: list[PageContent] = Field(default_factory=list, description="兼容旧接口的页面列表")
    blocks: list[DocBlock] = Field(default_factory=list, description="扁平块列表")
    sections: list[DocSection] = Field(default_factory=list, description="层级化章节")
    furniture: dict[str, list[DocBlock]] = Field(
        default_factory=dict, description="{'header': [...], 'footer': [...], 'caption': [...]}"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="解析器 provenance、页数、token 估算")
    createdAt: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_parsed_file(cls, parsed: "ParsedFile", document_id: str | None = None) -> "ParsedDocument":
        """从旧 ParsedFile 构造 ParsedDocument（向上兼容）

        转换规则：
        - 每个 page 的 ExtractedElement 变成 DocBlock
        - type 字段从 elementType 拷贝
        - blocks 扁平列表保留所有块
        - sections 暂留空（需后续章节识别步骤）
        - furniture 从 page 0/末尾提取 header/footer（TODO）
        """
        blocks: list[DocBlock] = []
        for page in parsed.pages:
            for elem in page.elements:
                # bbox 字段：{page: int, ...其他坐标}
                bbox: dict[str, float] = {"page": float(page.pageNumber)}
                if elem.position:
                    for k, v in elem.position.items():
                        bbox[k] = float(v)
                blocks.append(
                    DocBlock(
                        blockId=elem.elementId,
                        type=elem.elementType,
                        text=elem.content,
                        level=getattr(elem, "level", 0) or 0,
                        bbox=bbox,
                        metadata=elem.metadata,
                    )
                )
        return cls(
            documentId=document_id or parsed.parseId,
            fileName=parsed.fileName,
            fileType=parsed.fileType.value if hasattr(parsed.fileType, "value") else str(parsed.fileType),
            pages=parsed.pages,
            blocks=blocks,
            sections=[],
            metadata={
                "fileSize": parsed.fileSize,
                "pageCount": parsed.pageCount,
                "sourceParser": "from_parsed_file",
                "originalParseId": parsed.parseId,
            },
        )

    def all_text(self) -> str:
        """导出所有 block 的纯文本，按 page 顺序拼接"""
        chunks: list[str] = []
        for block in self.blocks:
            if block.text:
                if block.bbox and "page" in block.bbox:
                    chunks.append(f"[page={block.bbox['page']}] {block.text}")
                else:
                    chunks.append(block.text)
        return "\n\n".join(chunks)


DocSection.model_rebuild()  # 前向引用


# ==================== 转换请求/响应模块 ====================


class ConvertRequest(BaseModel):
    """数据转换请求"""

    parseId: str = Field(description="文件解析任务ID")
    conversionType: ConversionType = Field(default=ConversionType.AUTO, description="转换类型")
    outputFormat: OutputFormat = Field(default=OutputFormat.JSON, description="输出格式")
    customPrompt: str | None = Field(default=None, description="自定义转换指令")
    enc: str = Field(description="签名信息")


class ConvertUploadRequest(BaseModel):
    """上传并转换请求（简化版）"""

    fileType: Literal["ppt", "pdf", "image", "doc", "txt", "csv", "xls", "unknown"] = Field(description="文件类型")
    conversionType: ConversionType = Field(default=ConversionType.AUTO, description="转换类型")
    outputFormat: OutputFormat = Field(default=OutputFormat.JSON, description="输出格式")
    customPrompt: str | None = Field(default=None, description="自定义转换指令")


class ProcessingLog(BaseModel):
    """处理日志条目"""

    timestamp: datetime
    level: str = Field(description="日志级别: info, warning, error")
    message: str
    step: str = Field(description="处理步骤")


class ConvertResultData(BaseModel):
    """转换结果数据"""

    resultId: str
    parseId: str
    fileInfo: FileInfo
    conversionType: ConversionType
    outputFormat: OutputFormat
    extractedContent: str = Field(description="提取的原始内容摘要")
    convertedContent: str = Field(description="AI转换后的内容")
    structuredData: dict[str, Any] | None = Field(default=None, description="结构化数据")
    confidence: float = Field(default=0.0, description="转换置信度 0.0-1.0")
    enhance: dict[str, Any] | None = Field(
        default=None, description="会话模型增强提示（image_only/low_confidence/table_sparse）"
    )
    processingLogs: list[ProcessingLog]
    createdAt: datetime


class ConvertResponseData(BaseModel):
    """转换响应数据"""

    resultId: str
    fileInfo: FileInfo
    conversionType: ConversionType
    outputFormat: OutputFormat
    preview: str = Field(description="转换结果预览")
    confidence: float
    resultUrl: str | None = None
    exportUrl: str | None = None


class GetResultRequest(BaseModel):
    """获取转换结果请求"""

    resultId: str = Field(description="结果ID")
    enc: str = Field(description="签名信息")


class GetResultResponseData(BaseModel):
    """获取转换结果响应数据"""

    resultId: str
    fileInfo: FileInfo
    conversionType: ConversionType
    outputFormat: OutputFormat
    extractedContent: str
    convertedContent: str
    structuredData: dict[str, Any] | None
    confidence: float
    processingLogs: list[ProcessingLog]
    totalProcessingTime: int | None = Field(default=None, description="总处理时间（秒）")


# ==================== 内部数据结构 ====================


class ConversionStrategyInfo(BaseModel):
    """转换策略信息"""

    strategyId: str
    strategyName: str
    description: str
    supportedTypes: list[FileType]
    confidence: float


class StrategyScore(BaseModel):
    """策略评分"""

    strategyId: str
    score: float
    reason: str
