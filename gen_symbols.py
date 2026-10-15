# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.getcwd())
from pipeline import sample_symbols
from data_engine.database import list_symbols
syms = sample_symbols(300)
open("output/symbols_300.txt","w",encoding="utf-8").write("\n".join(syms))
print("symbols_300.txt:", len(syms), "只")
print("本地库共", len(list_symbols()), "只")
