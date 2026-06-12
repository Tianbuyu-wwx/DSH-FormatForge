"""
依赖注入模块
提供应用全局共享的单例实例
"""
from core.config import settings
from core.converter_engine import BatchConverter, DataConverter
from core.file_parser import FileParser

# 全局共享的 DataConverter 实例
data_converter = DataConverter()

# 全局共享的 BatchConverter 实例
batch_converter = BatchConverter()

# 全局共享的 FileParser 实例
file_parser = FileParser(upload_dir=settings.UPLOAD_DIR)
