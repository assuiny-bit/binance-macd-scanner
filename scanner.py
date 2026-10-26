
import json
import urllib.request
from datetime import datetime, timezone

BASE = "https://fapi.binance.com"
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
LEFT = 2
RIGHT = 2
MIN_GAP = 5
MAX_GAP = 60


def get_json(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def ema(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result

    previous = sum(values[:period]) / period
    result[period - 1] = previous
    alpha = 2 / (period + 1)

    for i in range(period, len(values)):
        previous = values[i] * alpha + previous * (1 - alpha)
        result[i] = previous

    return result


def pivots(values, kind):
    found = []
    for i in range(LEFT, len(values) - RIGHT):
        window = values[i - LEFT:i + RIGHT + 1]
        value = values[i]

        if kind == "high" and value == max(window) and window.count(value) == 1:
            found.append(i)
        elif kind == "low" and value == min(window) and window.count(value) == 1:
            found.append(i)

    return found


def scan_symbol(symbol):
    url = (
        f"{BASE}/fapi/v1/klines?symbol={symbol}"
        "&interval=1d&limit=240"
    )
    candles = get_json(url)

    # 僅保留已收盤的日 K
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candles = [c for c in candles if int(c[6]) < now_ms]

    if len(candles) < 60:
        return []

    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    dates = [
        datetime.fromtimestamp(
            int(c[0]) / 1000, timezone.utc
        ).strftime("%Y-%m-%d")
        for c in candles
    ]

    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)
    dif = [
        fast[i] - slow[i]
        if fast[i] is not None and slow[i] is not None
        else None
        for i in range(len(closes))
    ]

    first = next((i for i, v in enumerate(dif) if v is not None), None)
    if first is None:
        return []

    dea_tail = ema(dif[first:], MACD_SIGNAL)
    dea = [None] * first + dea_tail

    results = []

    for kind in ("high", "low"):
        prices = highs if kind == "high" else lows
        price_points = pivots(prices, kind)

        # 將價格轉折配對至附近 DIF 轉折
        dif_values = [v if v is not None else 0.0 for v in dif]
        dif_points = pivots(dif_values, kind)
        pairs = []

        for p in price_points:
            matches = [d for d in dif_points if abs(d - p) <= 2 and dif[d] is not None]
            if matches:
                d = min(matches, key=lambda x: abs(x - p))
                pairs.append((p, d))

        for j in range(len(pairs) - 1, 0, -1):
            p1, d1 = pairs[j - 1]
            p2, d2 = pairs[j]
            gap = p2 - p1

            if not MIN_GAP <= gap <= MAX_GAP:
                continue

            if kind == "high":
                valid = (
                    prices[p2] > prices[p1]
                    and dif[d2] < dif[d1]
                    and dif[d1] > 0
                    and dif[d2] > 0
                )
                signal = "MACD頂背離"
                invalidated = (
                    any(v is not None and v <= 0 for v in dif[p2 + 1:])
                    and any(v is not None and v <= 0 for v in dea[p2 + 1:])
                )
            else:
                valid = (
                    prices[p2] < prices[p1]
                    and dif[d2] > dif[d1]
                    and dif[d1] < 0
                    and dif[d2] < 0
                )
                signal = "MACD底背離"
                invalidated = (
                    any(v is not None and v >= 0 for v in dif[p2 + 1:])
                    and any(v is not None and v >= 0 for v in dea[p2 + 1:])
                )

            if valid and not invalidated:
                results.append({
                    "symbol": symbol,
                    "signal": signal,
                    "date1": dates[p1],
                    "date2": dates[p2],
                    "price1": round(prices[p1], 8),
                    "price2": round(prices[p2], 8),
                    "DIF1": round(dif[d1], 8),
                    "DIF2": round(dif[d2], 8),
                })
                break

    return results


def main():
    print("正在取得幣安 USDT 本位永續合約清單……")
    info = get_json(BASE + "/fapi/v1/exchangeInfo")

    symbols = [
        item["symbol"]
        for item in info["symbols"]
        if item.get("status") == "TRADING"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
    ]

    print("合約數量：", len(symbols))
    results = []
    errors = []

    for index, symbol in enumerate(symbols, 1):
        print(f"[{index}/{len(symbols)}] {symbol}")
        try:
            results.extend(scan_symbol(symbol))
        except Exception as error:
            errors.append((symbol, str(error)))

    print("\n掃描完成時間（UTC）：", datetime.now(timezone.utc).isoformat())
    print("找到的候選訊號數：", len(results))

    for row in results:
        print(
            row["symbol"], row["signal"],
            row["date1"], "→", row["date2"],
            "價格：", row["price1"], "→", row["price2"],
            "DIF：", row["DIF1"], "→", row["DIF2"]
        )

    print("掃描失敗的幣種數：", len(errors))
    for symbol, error in errors[:10]:
        print("錯誤：", symbol, error)


if __name__ == "__main__":
    main()
