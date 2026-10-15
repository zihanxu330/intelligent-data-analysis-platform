import os
import pandas as pd
from factors.feature_engine import add_price_action_features

def train():
    print('V5 AI训练入口')
    print('请接入iTick历史K线后生成训练集')
    os.makedirs('models',exist_ok=True)

if __name__=='__main__':
    train()
