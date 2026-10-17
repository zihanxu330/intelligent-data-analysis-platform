# -*- coding: utf-8 -*-
import os
import numpy as np
import pandas as pd

from models.model_io import load_bundle


class TraderModel:
    """
    读取统一 bundle 的打分器。
    模型缺失/出错时返回 NaN（而不是 0.5），调用方必须把 NaN 当作"AI 不参与判断"，
    这样不会悄悄放行或阻止交易。
    """
    def __init__(self, path="output/model_updown.joblib"):
        self.path = path
        self.model = None
        self.feature_cols = None

    def load(self):
        if os.path.exists(self.path):
            try:
                b = load_bundle(self.path)
                self.model, self.feature_cols = b["model"], b["feature_cols"] or None
            except Exception as e:
                print(f"[TraderModel] 加载失败 {self.path}: {e}")
        return self

    @property
    def ready(self):
        return self.model is not None

    def _to_frame(self, x):
        if isinstance(x, dict):
            x = pd.DataFrame([x])
        elif isinstance(x, pd.Series):
            x = x.to_frame().T
        elif not isinstance(x, pd.DataFrame):
            return pd.DataFrame(np.atleast_2d(x))
        return x[self.feature_cols] if self.feature_cols else x

    def predict_scores(self, x):
        """批量打分，返回 ndarray；缺特征(NaN)的行返回 NaN。"""
        if not self.ready:
            return np.full(len(x) if hasattr(x, "__len__") else 1, np.nan)
        df = self._to_frame(x).replace([np.inf, -np.inf], np.nan)
        out = np.full(len(df), np.nan)
        ok = df.notna().all(axis=1).to_numpy()
        if ok.any():
            out[ok] = self.model.predict_proba(df[ok])[:, 1]
        return out

    def predict_score(self, x):
        return float(self.predict_scores(x)[0])
