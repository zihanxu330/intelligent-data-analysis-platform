# -*- coding: utf-8 -*-
"""验证 argv 里股票代码是否丢失前导零"""
import sys
import argparse

print("raw sys.argv:", sys.argv)

p = argparse.ArgumentParser()
p.add_argument("--symbols", type=str, default=None)
args = p.parse_args()
print("args.symbols:", repr(args.symbols))
if args.symbols:
    symbols = [s.strip() for s in args.symbols.split(",")]
    print("parsed symbols:", symbols)
