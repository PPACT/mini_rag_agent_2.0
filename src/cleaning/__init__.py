"""清洗层（`2.0-5`）。入口：`src.cleaning.rules`。"""
from src.cleaning.rules import CleanReport, RuleHit, apply_rules, run_text_rules

__all__ = ["CleanReport", "RuleHit", "apply_rules", "run_text_rules"]
