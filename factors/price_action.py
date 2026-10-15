import numpy as np

def add_price_action(df):
    df=df.copy()
    rng=(df.high-df.low).replace(0,np.nan)
    body=(df.close-df.open).abs()
    df['body_ratio']=body/rng
    df['upper_shadow']=(df.high-df[['open','close']].max(axis=1))/rng
    df['lower_shadow']=(df[['open','close']].min(axis=1)-df.low)/rng
    df['bull_bar']=(df.close>df.open).astype(int)
    df['bear_bar']=(df.close<df.open).astype(int)
    df['inside_bar']=((df.high<df.high.shift(1))&(df.low>df.low.shift(1))).astype(int)
    df['outside_bar']=((df.high>df.high.shift(1))&(df.low<df.low.shift(1))).astype(int)
    df['higher_low']=(df.low>df.low.shift(1)).astype(int)
    df['lower_high']=(df.high<df.high.shift(1)).astype(int)
    # Brooks风格：二次入场/突破失败近似
    df['high2']=(df.higher_low.rolling(3).sum()>=2).astype(int)
    df['low2']=(df.lower_high.rolling(3).sum()>=2).astype(int)
    df['failed_breakout_up']=((df.high>df.high.rolling(10).max().shift(1))&(df.close<df.open)).astype(int)
    df['failed_breakout_down']=((df.low<df.low.rolling(10).min().shift(1))&(df.close>df.open)).astype(int)
    return df
