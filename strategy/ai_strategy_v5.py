import backtrader as bt

class AIPriceActionStrategy(bt.Strategy):
    params=(('threshold',0.7),)
    def next(self):
        body=self.data.close[0]-self.data.open[0]
        rng=self.data.high[0]-self.data.low[0]
        if rng and body/rng>0.5 and not self.position:
            self.buy(size=1)
        elif self.position and body<0:
            self.close()
