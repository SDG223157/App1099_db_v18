import re

def normalize_ticker(symbol: str, purpose: str = 'analyze') -> str:
    """Convert between TradingView and Yahoo Finance symbols
    Args:
        symbol: The symbol to convert
        purpose: Either 'analyze' (convert to Yahoo) or 'search' (convert to TradingView)
    """
    # Handle Yahoo Finance indices to TradingView format
    if symbol.startswith('^') and purpose == 'search':
        yahoo_to_tv = {
            '^GSPC': 'SP:SPX',    # S&P 500
            '^DJI': 'DJ:DJI',     # Dow Jones
            '^IXIC': 'NASDAQ:IXIC',    # NASDAQ 100
            '^HSI': 'TVC:HSI',     # Hang Seng
            '^N225': 'TSE:NI225',  # Nikkei 225
            '^FTSE': 'LSE:UKX',    # FTSE 100
            '^GDAXI': 'XETR:DAX'  # DAX 40
        }
        return yahoo_to_tv.get(symbol, symbol)

    # Handle TradingView indices to Yahoo Finance format
    if symbol.startswith('TVC:') and purpose == 'analyze':
        tv_to_yahoo = {
            'TVC:HSI': '^HSI',     # Hang Seng Index
            'TVC:SSEC': '^SSEC',   # Shanghai Composite
            'TVC:SZSC': '^SZSC',   # Shenzhen Component
            'TVC:NDX': '^NDX',     # Nasdaq 100
            'TVC:SPX': '^GSPC',    # S&P 500
            'TVC:DJI': '^DJI'      # Dow Jones Industrial Average
        }
        return tv_to_yahoo.get(symbol, symbol.replace('TVC:', '^'))

    # Handle stock symbols based on purpose
    if purpose == 'search':
        # Convert Yahoo to TradingView format
        if symbol == 'BRK-A':  # Only handle hyphen format for Yahoo
            return 'NYSE:BRK.A'
        if re.match(r'^\d{4}\.HK$', symbol):
            return f"HKEX:{int(symbol.replace('.HK', ''))}"
        elif re.search(r'\.SS$', symbol):
            return f"SSE:{symbol.replace('.SS', '')}"
        elif re.search(r'\.SZ$', symbol):
            return f"SZSE:{symbol.replace('.SZ', '')}"
    else:  # purpose == 'analyze'
        # Convert TradingView to Yahoo format
        if ':' in symbol:
            exchange, ticker = symbol.split(':')
            if exchange == 'NYSE' and ticker == 'BRK.A':
                return 'BRK-A'  # Use hyphen notation for Yahoo Finance
            if exchange == 'HKEX':
                return f"{int(ticker):04d}.HK"
            elif exchange == 'SSE':
                return f"{ticker}.SS"
            elif exchange == 'SZSE':
                return f"{ticker}.SZ"
            return ticker

    return symbol 