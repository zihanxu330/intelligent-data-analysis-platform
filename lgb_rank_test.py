# -*- coding: utf-8 -*-
import numpy as np, pandas as pd
from lightgbm import LGBMRanker
rng = np.random.default_rng(0)
X = pd.DataFrame(rng.normal(size=(60, 5)), columns=[f"f{i}" for i in range(5)])
def try_label(y, name):
    try:
        m = LGBMRanker(n_estimators=5, max_depth=3, verbose=-1)
        m.fit(X, y, group=[20, 20, 20])
        print(f"[OK] {name}: 可训练, predict shape={m.predict(X).shape}")
    except Exception as e:
        print(f"[FAIL] {name}: {str(e)[:90]}")
try_label(np.array([1,2,3,4,5]*12), "rank 1..5")
try_label(np.array([0,1,2,3,4]*12), "rank 0..4")
try_label(np.concatenate([[0]*20,[1]*20,[2]*20]), "level 0/1/2")
