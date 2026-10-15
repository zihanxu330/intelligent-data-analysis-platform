import pandas as pd

def add_price_action_features(df):
    df=df.copy()
    r=(df['high']-df['low']).replace(0,1e-9)
    df['body_ratio']=(df['close']-df['open']).abs()/r
    df['upper_shadow']=(df['high']-df[['open','close']].max(axis=1))/r
    df['lower_shadow']=(df['close'].where(df['close']<df['open'],df['open'])-df['low'])/r
    df['bull_bar']=(df['close']>df['open']).astype(int)
    df['bear_bar']=(df['close']<df['open']).astype(int)
    df['inside_bar']=((df['high']<df['high'].shift(1))&(df['low']>df['low'].shift(1))).astype(int)
    df['outside_bar']=((df['high']>df['high'].shift(1))&(df['low']<df['low'].shift(1))).astype(int)
    return df.fillna(0)
