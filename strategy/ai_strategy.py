from factors.price_action import add_price_action
from factors.market_cycle import add_market_cycle

class BrooksAIStrategy:
    """Al Brooks Price Action简化AI策略
    状态: SPIKE -> CHANNEL -> RANGE -> BREAKOUT
    核心: Always-In方向 + High2/Low2 + Failed Breakout
    """
    def __init__(self,*args,**kwargs):
        self.position=0

    def generate_signal(self,df,i):
        if i<70:
            return 'HOLD'
        data=df.iloc[:i+1].copy()
        data=add_price_action(data)
        data=add_market_cycle(data)
        r=data.iloc[-1]
        cycle=r.market_cycle

        # 趋势中的二次入场
        if cycle in ['SPIKE_UP','CHANNEL_UP']:
            if r.bull_bar and r.high2 and r.body_ratio>0.45:
                return 'BUY'
        if cycle in ['SPIKE_DOWN','CHANNEL_DOWN']:
            if r.bear_bar and r.low2 and r.body_ratio>0.45:
                return 'SELL'

        # 最终旗形/突破失败反转
        if r.failed_breakout_up:
            return 'SELL'
        if r.failed_breakout_down:
            return 'BUY'

        return 'HOLD'
