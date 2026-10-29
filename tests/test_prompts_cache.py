"""提示词模板必须缓存 —— 每次请求重读 YAML 会在事件循环里同步阻塞。"""
from __future__ import annotations

from src.config import prompts


def test_templates_are_cached():
    prompts._load.cache_clear()
    prompts.load_templates()
    prompts.load_templates()
    info = prompts._load.cache_info()
    assert info.hits >= 1, f"模板没被复用：{info}"


def test_different_sections_are_cache_misses():
    """反向用例：缓存按 section 区分，⛔ 不能把同一份内容返回给所有调用方。"""
    prompts._load.cache_clear()
    system, _ = prompts.load_templates()
    rewrite_system, _ = prompts.load_rewrite_templates()
    assert system and rewrite_system
    assert system != rewrite_system
    assert prompts._load.cache_info().misses == 2
