import numpy as np

def add_market_cycle(df):
    df=df.copy()
    if 'ma20' not in df:
        df['ma20']=df['close'].rolling(20).mean()
    if 'ma60' not in df:
        df['ma60']=df['close'].rolling(60).mean()
    if 'mom20' not in df:
        df['mom20']=df['close'].pct_change(20)
    vol=df['volume'] if 'volume' in df else np.ones(len(df))
    df['vol20']=vol.rolling(20).mean()
    df['vol50']=vol.rolling(50).mean()
    df['market_cycle']='RANGE'
    trend_up=(df.ma20>df.ma60)&(df.mom20>0)
    trend_dn=(df.ma20<df.ma60)&(df.mom20<0)
    df.loc[trend_up,'market_cycle']='CHANNEL_UP'
    df.loc[trend_dn,'market_cycle']='CHANNEL_DOWN'
    breakout=(df['vol20']>df['vol50']*1.2)
    df.loc[breakout & trend_up,'market_cycle']='SPIKE_UP'
    df.loc[breakout & trend_dn,'market_cycle']='SPIKE_DOWN'
    return df
