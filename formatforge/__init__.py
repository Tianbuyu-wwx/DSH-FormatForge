"""
FormatForge —— 把任意格式锻造成 AI 可读数据（dsh 插件形态核心包）

用法：
    python -m formatforge translate <path> [--format json|markdown|html|text] [--quality]
    python -m formatforge translate --stdin-text
    python -m formatforge formats
    python -m formatforge version

stdout 只输出协议 JSON；全部日志走 stderr。协议见 PLUGIN_PLAN.md §4.3。
"""
