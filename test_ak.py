import requests

_original_init = requests.Session.__init__

def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    })

requests.Session.__init__ = _patched_init

import akshare as ak
import os
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import akshare as ak
import akshare as ak

print("AKShare版本:")
print(ak.__version__)

print("正在获取股票列表...")

df = ak.stock_zh_a_spot_em()

print(df.head())

print("股票数量:")
print(len(df))