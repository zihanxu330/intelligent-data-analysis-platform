# -*- coding: utf-8 -*-
"""统一的模型存取：所有模型都以同一种 bundle(dict) 格式保存，避免各脚本格式不一致。"""
import os
import joblib

_cache = {}


def save_bundle(model, feature_cols, path, objective="binary", meta=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    joblib.dump({
        "model": model,
        "feature_cols": list(feature_cols),
        "objective": objective,          # "binary" 或 "rank"
        "meta": meta or {},
    }, path)


def load_bundle(path, use_cache=True):
    """加载 bundle；兼容旧版直接 dump 的裸模型。按文件修改时间缓存，避免逐股票重复读盘。"""
    mtime = os.path.getmtime(path)
    key = os.path.abspath(path)
    if use_cache and key in _cache and _cache[key][0] == mtime:
        return _cache[key][1]
    obj = joblib.load(path)
    if not (isinstance(obj, dict) and "model" in obj):   # legacy: 裸模型
        obj = {
            "model": obj,
            "feature_cols": list(getattr(obj, "feature_name_", []) or []),
            "objective": "binary",
            "meta": {"legacy": True},
        }
    _cache[key] = (mtime, obj)
    return obj
