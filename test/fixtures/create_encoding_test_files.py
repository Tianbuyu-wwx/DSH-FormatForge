"""
构造各种编码和乱码的 TXT 测试文件
用于验证编码自动检测功能
"""
import os
from pathlib import Path


def create_test_files(output_dir: Path):
    """创建所有编码测试文件"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. UTF-8 标准编码（对照组）
    utf8_text = """UTF-8 编码测试文件
这是标准 UTF-8 编码的中文内容。
包含常见字符：你好世界，123，ABC，！@#￥%
特殊符号：→ ← ↑ ↓ ✓ × ÷ ± ∞ ≈ ≠ ≤ ≥
引号："中文引号"、'英文单引号'
日期：2024年1月15日
"""
    (output_dir / "utf8_normal.txt").write_text(utf8_text, encoding='utf-8')
    print(f"[OK] UTF-8 标准编码: {output_dir / 'utf8_normal.txt'}")

    # 2. UTF-8 with BOM
    utf8_bom_text = "UTF-8 BOM 编码测试\n这是带 BOM 头的 UTF-8 文件。\n中文内容：你好世界"
    (output_dir / "utf8_bom.txt").write_bytes(b'\xef\xbb\xbf' + utf8_bom_text.encode('utf-8'))
    print(f"[OK] UTF-8 BOM 编码: {output_dir / 'utf8_bom.txt'}")

    # 3. GBK 编码
    gbk_text = """GBK 编码测试文件
这是 GBK 编码的中文内容。
包含简体字：中华人民共和国，北京市，上海市
混合内容：Hello World，12345，！@#￥%
特殊地名：乌鲁木齐、呼和浩特、齐齐哈尔
人名：张三、李四、王五、赵六
"""
    (output_dir / "gbk_chinese.txt").write_text(gbk_text, encoding='gbk')
    print(f"[OK] GBK 编码: {output_dir / 'gbk_chinese.txt'}")

    # 4. GB2312 编码（GBK 子集）
    gb2312_text = """GB2312 编码测试文件
这是 GB2312 编码的中文内容。
常用汉字：天地玄黄宇宙洪荒日月盈昃辰宿列张
数字和字母：1234567890，ABCDEFG
标点符号：，。！？；：""''（）【】《》
"""
    (output_dir / "gb2312_chinese.txt").write_text(gb2312_text, encoding='gb2312')
    print(f"[OK] GB2312 编码: {output_dir / 'gb2312_chinese.txt'}")

    # 5. Big5 编码（繁体中文）
    big5_text = """Big5 編碼測試檔案
這是 Big5 編碼的繁體中文內容。
臺灣地名：臺北市、高雄市、臺中市、花蓮縣
香港地名：中西區、灣仔區、油尖旺區
常用詞：電腦、軟體、程式、資料庫、網際網路
"""
    (output_dir / "big5_traditional.txt").write_text(big5_text, encoding='big5')
    print(f"[OK] Big5 编码: {output_dir / 'big5_traditional.txt'}")

    # 6. GBK 编码 + 模拟乱码（混入无法解码的字节）
    gbk_base = "这是一份包含乱码的 GBK 文件。\n正常中文内容在这里。\n"
    gbk_bytes = gbk_base.encode('gbk')
    # 插入一些乱码字节（模拟传输损坏）
    corrupted = gbk_bytes[:30] + b'\xff\xfe\x80\x81' + gbk_bytes[30:]
    (output_dir / "gbk_corrupted.txt").write_bytes(corrupted)
    print(f"[OK] GBK 乱码混合: {output_dir / 'gbk_corrupted.txt'}")

    # 7. UTF-8 编码 + 控制字符乱码
    utf8_with_garbage = """正常 UTF-8 内容开头
这里有一些控制字符：\x00\x01\x02\x03\x04\x05
更多文本内容继续
特殊乱码：\x7f\x80\x81\x82\x83
结尾正常内容
"""
    (output_dir / "utf8_control_chars.txt").write_text(utf8_with_garbage, encoding='utf-8')
    print(f"[OK] UTF-8 控制字符乱码: {output_dir / 'utf8_control_chars.txt'}")

    # 8. 混合编码文件（前半 UTF-8，后半 GBK）
    mixed_content = "前半部分是 UTF-8 编码。\n".encode('utf-8') + "后半部分是 GBK 编码。\n".encode('gbk')
    (output_dir / "mixed_encoding.txt").write_bytes(mixed_content)
    print(f"[OK] 混合编码: {output_dir / 'mixed_encoding.txt'}")

    # 9. 纯英文 ASCII 文件
    ascii_text = """ASCII Encoding Test File
This is a pure ASCII text file.
No Chinese characters, only English letters and numbers.
Special chars: !@#$%^&*()_+-=[]{}|;':",./<>?
Numbers: 1234567890
Hex: 0x1A 0xFF 0x00
"""
    (output_dir / "ascii_pure.txt").write_text(ascii_text, encoding='ascii')
    print(f"[OK] 纯 ASCII: {output_dir / 'ascii_pure.txt'}")

    # 10. GBK 编码的长文本（用于测试大文件流式读取）
    long_lines = []
    for i in range(50):
        long_lines.append(f"第{i+1}行：这是 GBK 编码的长文本测试内容，包含中文汉字和数字123。")
    gbk_long = "\n\n".join(long_lines)
    (output_dir / "gbk_long_text.txt").write_text(gbk_long, encoding='gbk')
    print(f"[OK] GBK 长文本: {output_dir / 'gbk_long_text.txt'}")

    # 11. UTF-8 编码的 Markdown 格式
    md_content = """# Markdown 标题测试

## 二级标题

这是正文段落，包含**粗体**和*斜体*。

- 列表项 1
- 列表项 2
- 列表项 3

1. 有序列表 1
2. 有序列表 2

> 引用块内容

```python
# 代码块
print("Hello World")
```

| 表头1 | 表头2 |
|-------|-------|
| 内容1 | 内容2 |
"""
    (output_dir / "utf8_markdown.md").write_text(md_content, encoding='utf-8')
    print(f"[OK] UTF-8 Markdown: {output_dir / 'utf8_markdown.md'}")

    # 12. GBK 编码的日志格式
    log_content = """2024-01-15 10:30:00 [INFO] 系统启动成功
2024-01-15 10:30:05 [INFO] 连接数据库：localhost:3306
2024-01-15 10:30:10 [WARN] 检测到内存使用率达到 85%
2024-01-15 10:30:15 [ERROR] 无法连接到远程服务器：超时
2024-01-15 10:30:20 [INFO] 重试连接...
2024-01-15 10:30:25 [INFO] 连接成功
2024-01-15 10:30:30 [DEBUG] 缓存清理完成，释放 128MB
"""
    (output_dir / "gbk_log_file.log").write_text(log_content, encoding='gbk')
    print(f"[OK] GBK 日志格式: {output_dir / 'gbk_log_file.log'}")

    print(f"\n所有测试文件已创建到: {output_dir}")
    print(f"共创建 12 个测试文件")


if __name__ == '__main__':
    fixtures_dir = Path(__file__).parent
    create_test_files(fixtures_dir)
