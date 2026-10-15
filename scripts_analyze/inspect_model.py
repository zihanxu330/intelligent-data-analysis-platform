# -*- coding: utf-8 -*-
"""读取模型元信息"""
import joblib

b = joblib.load("output/model_updown.joblib")
print("keys:", list(b.keys()))
print("horizon:", b.get("horizon"))
print("trained_on_symbols:", b.get("trained_on_symbols"))
print("feature_cols:", b.get("feature_cols"))
m = b["model"]
print("model type:", type(m).__name__)
print("n_classes:", getattr(m, "n_classes_", None))
