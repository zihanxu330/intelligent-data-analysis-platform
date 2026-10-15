import joblib
from lightgbm import LGBMClassifier

def train_model(X,y):
    model=LGBMClassifier(n_estimators=500,max_depth=6,learning_rate=0.03)
    model.fit(X,y)
    return model

def save(model,path='output/model_updown_lgbm.joblib'):
    joblib.dump(model,path)

def load(path='output/model_updown_lgbm.joblib'):
    return joblib.load(path)
