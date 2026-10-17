import os, pickle
try:
    import lightgbm as lgb
except Exception:
    lgb=None

class TraderModel:
    def __init__(self,path='models/trader_model.pkl'):
        self.path=path
        self.model=None
    def load(self):
        if os.path.exists(self.path):
            with open(self.path,'rb') as f:self.model=pickle.load(f)
        return self
    def predict_score(self,x):
        if self.model is None:return 0.5
        return float(self.model.predict_proba(x)[0][1])
