# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping, log_evaluation
from sklearn.metrics import roc_auc_score

from models.model_io import save_bundle, load_bundle

DEFAULT_PATH = "output/model_updown.joblib"   # 与 predict.add_ai_score 默认路径一致


def _params(**kw):
    p = dict(
        n_estimators=2000, learning_rate=0.03, num_leaves=31, max_depth=6,
        min_child_samples=100, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.8, reg_lambda=1.0, random_state=42, n_jobs=-1, verbose=-1,
    )
    p.update(kw)
    return p


def time_split(X, y, dates, valid_frac=0.2, gap_days=10):
    """按日期切分（而非按行），并留 gap 防止标签窗口重叠造成泄漏。"""
    dates = pd.to_datetime(pd.Series(np.asarray(dates)))
    cut = dates.quantile(1 - valid_frac)
    tr = (dates < cut - pd.Timedelta(days=gap_days)).to_numpy()
    va = (dates >= cut).to_numpy()
    return X[tr], y[tr], X[va], y[va]


def train_model(X, y, dates=None, valid_frac=0.2, **params):
    """
    X: DataFrame（保留列名，用于存 feature_cols）；y: 0/1。
    传入 dates 时按时间切分并用验证集早停；未传则按行序（要求 X 已按时间排序）。
    返回已拟合模型；验证 AUC 存在 model.valid_auc_。
    """
    X = X.reset_index(drop=True)
    y = pd.Series(np.asarray(y)).reset_index(drop=True)
    if dates is not None:
        Xtr, ytr, Xva, yva = time_split(X, y, dates, valid_frac)
    else:
        n = int(len(X) * (1 - valid_frac))
        Xtr, ytr, Xva, yva = X.iloc[:n], y.iloc[:n], X.iloc[n:], y.iloc[n:]

    model = LGBMClassifier(**_params(**params))
    model.fit(Xtr, ytr, eval_set=[(Xva, yva)], eval_metric="auc",
              callbacks=[early_stopping(100, verbose=False), log_evaluation(0)])
    model.valid_auc_ = roc_auc_score(yva, model.predict_proba(Xva)[:, 1])
    print(f"[train] best_iter={model.best_iteration_}  valid AUC={model.valid_auc_:.4f}")
    return model


def walk_forward_auc(X, y, dates, n_splits=5, **params):
    """滚动前向验证：每折只用过去训练、预测未来，返回各折 AUC。"""
    d = pd.to_datetime(pd.Series(np.asarray(dates))).reset_index(drop=True)
    X = X.reset_index(drop=True); y = pd.Series(np.asarray(y)).reset_index(drop=True)
    edges = d.quantile(np.linspace(0.4, 1.0, n_splits + 1)).tolist()
    aucs = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        tr, te = d < lo - pd.Timedelta(days=10), (d >= lo) & (d <= hi)
        if te.sum() == 0 or y[te].nunique() < 2:
            continue
        m = LGBMClassifier(**_params(n_estimators=300, **params)).fit(X[tr], y[tr])
        aucs.append(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))
    return aucs


def save(model, path=DEFAULT_PATH, feature_cols=None):
    cols = feature_cols or list(getattr(model, "feature_name_", []))
    save_bundle(model, cols, path, objective="binary",
                meta={"valid_auc": getattr(model, "valid_auc_", None)})


def load(path=DEFAULT_PATH):
    return load_bundle(path)["model"]
