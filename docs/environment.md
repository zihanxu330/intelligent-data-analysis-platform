# Reproducible Python environment

## Supported runtime

- Python 3.11.9 (64-bit Windows for the frozen project environment).
- `requirements.txt` pins the direct runtime dependencies.
- `requirements-lock-py311.txt` is a full `pip freeze` snapshot from the
  Python 3.11.9 environment used for this maintenance pass, including
  transitive dependencies.

Install the frozen environment with:

```powershell
python -m pip install -r requirements-lock-py311.txt
```

The KLC decoder's Python import is `py_mini_racer`; its distribution name is
`mini-racer`. Keep the distribution pin in the dependency files even though
the import name differs.

## Validation

Run the offline suite with:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

GitHub Actions runs this suite on Windows and Python 3.11.9. The tests must
not call external quote services or write to `output/quant.db`.

## Scope and provenance

The supported application entrypoints resolve project-relative paths from
`__file__`. Older research scripts may retain absolute paths because their
outputs and execution provenance are historical; they are not bulk-rewritten
as part of this maintenance pass. Review scratch and untracked research files
individually before tracking, moving, or deleting them.

This lock captures the current Python 3.11.9 environment; it does not claim to
reconstruct the historical environment used to train earlier model files.
