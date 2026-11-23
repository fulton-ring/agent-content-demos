import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # 1. Data: daily prices for today's S&P 500 members

        The backtest needs, for every stock, daily open, high, low, close and volume going back
        ten years, plus the dates of stock splits. Yahoo Finance serves all of it for free
        through the `yfinance` library. The list of members comes from a public CSV of the
        current index.

        **Known limits, stated up front:** the list is *today's* members, so companies that were
        dropped from the index (often because they fell) are missing, and daily bars cannot show
        what happened inside a day.
        """
    )
    return (mo,)


@app.cell
def _():
    import io
    import os
    from pathlib import Path

    import pandas as pd
    import requests
    import yfinance as yf

    CACHE = Path(
        os.environ.get("SPIKES_CACHE", Path.home() / ".cache" / "sp500-volume-spike-strategies")
    )
    START = os.environ.get("SPIKES_START", "2016-11-01")
    END = os.environ.get("SPIKES_END", "2026-11-21")
    MEMBERS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    BATCH = 100
    MAX_TRIES = 3
    CACHE.mkdir(parents=True, exist_ok=True)
    return BATCH, CACHE, END, MAX_TRIES, MEMBERS_URL, START, io, pd, requests, yf


@app.cell
def _(MEMBERS_URL, io, pd, requests):
    reply = requests.get(MEMBERS_URL, timeout=30)
    reply.raise_for_status()
    members = pd.read_csv(io.StringIO(reply.text))
    # Yahoo writes share classes with a dash (BRK-B), the member list with a dot.
    symbols = members["Symbol"].str.replace(".", "-", regex=False).tolist() + ["SPY"]
    assert len(symbols) > 400, f"member list looks wrong: {len(symbols)} symbols"
    f"{len(symbols) - 1} members plus SPY as the market benchmark"
    return members, symbols


@app.cell
def _(BATCH, END, MAX_TRIES, START, pd, symbols, yf):
    # Unadjusted prices (auto_adjust=False) with split events. Yahoo already divides old prices
    # by later splits, so the "as traded" price is rebuilt from the split column in notebook 2.
    frames: list[pd.DataFrame] = []
    for _start in range(0, len(symbols), BATCH):
        _batch = symbols[_start : _start + BATCH]
        _raw = pd.DataFrame()
        for _try in range(MAX_TRIES):
            _raw = yf.download(
                _batch,
                start=START,
                end=END,
                interval="1d",
                auto_adjust=False,
                actions=True,
                progress=False,
                threads=True,
            )
            if not _raw.empty:
                break
        assert not _raw.empty, f"Yahoo returned nothing for batch starting at {_start}"
        for _symbol in _batch:
            if _symbol not in _raw["Close"].columns:
                continue
            _one = _raw.xs(_symbol, axis=1, level="Ticker").dropna(subset=["Close"])
            if _one.empty:
                continue
            frames.append(
                pd.DataFrame(
                    {
                        "ticker": _symbol,
                        "date": _one.index,
                        "open": _one["Open"].to_numpy(),
                        "high": _one["High"].to_numpy(),
                        "low": _one["Low"].to_numpy(),
                        "close": _one["Close"].to_numpy(),
                        "volume": _one["Volume"].to_numpy(),
                        "split": _one["Stock Splits"].fillna(0.0).to_numpy(),
                    }
                )
            )
    prices = pd.concat(frames, ignore_index=True)
    return (prices,)


@app.cell
def _(CACHE, members, prices, symbols):
    got = set(prices["ticker"])
    missing = sorted(set(symbols) - got)
    assert len(missing) <= 0.05 * len(symbols), f"too many tickers missing: {missing}"
    prices.to_parquet(CACHE / "prices.parquet", index=False)
    members.to_csv(CACHE / "members.csv", index=False)
    print(
        f"{len(got)} tickers, {len(prices):,} rows, "
        f"{prices['date'].min().date()} to {prices['date'].max().date()}"
    )
    print(f"no data from Yahoo for {len(missing)}: {missing}")
    print(f"splits in the data: {int((prices['split'] > 0).sum())}")
    print(f"saved to {CACHE}")
    return


if __name__ == "__main__":
    app.run()
