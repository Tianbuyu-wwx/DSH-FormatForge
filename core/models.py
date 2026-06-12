"""
数据模型定义
AI 数据转换器 - 通用数据转换模型
"""
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


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
    DOC = "doc"       # Word 文档
    TXT = "txt"
    CSV = "csv"
    XLS = "xls"       # Excel 表格
    UNKNOWN = "unknown"


# ==================== 通用响应模型 ====================

class BaseResponse(BaseModel):
    """通用响应格式"""
    code: int = Field(default=200, description="状态码")
    msg: str = Field(default="操作成功", description="状态描述")
    data: Optional[Dict[str, Any]] = Field(default=None, description="业务数据")
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
    position: Optional[Dict[str, int]] = None
    metadata: Optional[Dict[str, Any]] = None


class PageContent(BaseModel):
    """页面内容"""
    pageNumber: int
    elements: List[ExtractedElement]
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
    pages: List[PageContent]
    structure: Optional[Dict[str, Any]] = None
    createdAt: datetime
    status: TaskStatus
    filePath: Optional[str] = None
    imagePaths: Optional[List[str]] = None


# ==================== 转换请求/响应模块 ====================

class ConvertRequest(BaseModel):
    """数据转换请求"""
    parseId: str = Field(description="文件解析任务ID")
    conversionType: ConversionType = Field(default=ConversionType.AUTO, description="转换类型")
    outputFormat: OutputFormat = Field(default=OutputFormat.JSON, description="输出格式")
    customPrompt: Optional[str] = Field(default=None, description="自定义转换指令")
    enc: str = Field(description="签名信息")


class ConvertUploadRequest(BaseModel):
    """上传并转换请求（简化版）"""
    fileType: Literal["ppt", "pdf", "image", "doc", "txt", "csv", "xls", "unknown"] = Field(description="文件类型")
    conversionType: ConversionType = Field(default=ConversionType.AUTO, description="转换类型")
    outputFormat: OutputFormat = Field(default=OutputFormat.JSON, description="输出格式")
    customPrompt: Optional[str] = Field(default=None, description="自定义转换指令")


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
    structuredData: Optional[Dict[str, Any]] = Field(default=None, description="结构化数据")
    confidence: float = Field(default=0.0, description="转换置信度 0.0-1.0")
    processingLogs: List[ProcessingLog]
    createdAt: datetime


class ConvertResponseData(BaseModel):
    """转换响应数据"""
    resultId: str
    fileInfo: FileInfo
    conversionType: ConversionType
    outputFormat: OutputFormat
    preview: str = Field(description="转换结果预览")
    confidence: float
    resultUrl: Optional[str] = None
    exportUrl: Optional[str] = None


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
    structuredData: Optional[Dict[str, Any]]
    confidence: float
    processingLogs: List[ProcessingLog]
    totalProcessingTime: Optional[int] = Field(default=None, description="总处理时间（秒）")


# ==================== 内部数据结构 ====================

class ConversionStrategyInfo(BaseModel):
    """转换策略信息"""
    strategyId: str
    strategyName: str
    description: str
    supportedTypes: List[FileType]
    confidence: float


class StrategyScore(BaseModel):
    """策略评分"""
    strategyId: str
    score: float
    reason: str
