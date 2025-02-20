from time import sleep
from random import random
from flask import Blueprint, render_template, request, make_response, jsonify, redirect, url_for
from datetime import datetime
import yfinance as yf
import logging
import sys
import re
import os
import traceback
from flask_login import login_required, current_user
from app.utils.analyzer.stock_analyzer import create_stock_visualization, create_stock_visualization_old
from sqlalchemy import inspect
from app import db
from sqlalchemy import text
from flask import send_file
import pandas as pd
import io
from functools import wraps
from flask import abort
from datetime import datetime, timedelta
from app.utils.data.data_service import DataService, RateLimiter
 
import random  # Make sure this is imported
from time import sleep
from datetime import datetime, timedelta
from sqlalchemy import inspect
import traceback
import threading
import queue
from app.utils.config.analyze_config import ANALYZE_CONFIG
# from flask_login import current_user

# Add this decorator function to check for admin privileges


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Create Blueprint
bp = Blueprint('main', __name__)
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)  # Forbidden access
        return f(*args, **kwargs)
    return decorated_function

def verify_ticker(symbol):
    """Verify ticker with yfinance and get company name"""
    try:
        logger.info(f"Verifying ticker: {symbol}")
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        if info:
            if 'longName' in info:
                return True, info['longName']
            elif 'shortName' in info:
                return True, info['shortName']
            return True, symbol
                
        return False, None
    except Exception as e:
        logger.error(f"Error verifying ticker {symbol}: {str(e)}")
        return False, None


def load_tickers():
    """Load tickers from TypeScript file"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, '..', 'tickers.ts')
        
        logger.debug(f"Current directory: {current_dir}")
        logger.debug(f"Looking for tickers.ts at: {file_path}")
        
        if not os.path.exists(file_path):
            logger.error(f"Tickers file not found at: {file_path}")
            file_path = os.path.join(os.getcwd(), 'tickers.ts')
            logger.debug(f"Trying current directory: {file_path}")
            
            if not os.path.exists(file_path):
                logger.error("Tickers file not found in current directory either")
                return [], {}
        
        logger.info(f"Found tickers.ts at: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            logger.debug(f"Read {len(content)} characters from tickers.ts")
            
        pattern = r'{[^}]*symbol:\s*"([^"]*)",[^}]*name:\s*"([^"]*)"[^}]*}'
        matches = re.finditer(pattern, content)
        
        TICKERS = []
        TICKER_DICT = {}
        
        for match in matches:
            symbol, name = match.groups()
            ticker_obj = {"symbol": symbol, "name": name}
            TICKERS.append(ticker_obj)
            TICKER_DICT[symbol] = name
        
        logger.info(f"Successfully loaded {len(TICKERS)} tickers")
        logger.debug(f"First few tickers: {TICKERS[:3]}")
        
        return TICKERS, TICKER_DICT
        
    except Exception as e:
        logger.error(f"Error loading tickers: {str(e)}")
        logger.error(traceback.format_exc())
        return [], {}

# Load tickers at module level
TICKERS, TICKER_DICT = load_tickers()

@bp.route('/')
def index():
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('index.html', now=datetime.now(), max_date=today)


def normalize_ticker(symbol):
    """Normalize ticker symbols to their proper format."""
    # Common index mappings
    index_mappings = {
        'HSI': '^HSI',     # Hang Seng Index
        'GSPC': '^GSPC',   # S&P 500
        'DJI': '^DJI',     # Dow Jones Industrial Average
        'IXIC': '^IXIC',   # NASDAQ Composite
        'N225': '^N225',   # Nikkei 225
        'FTSE': '^FTSE', 
        'VIX':  '^VIX',  
        'US10Y':  '^TNX',  
        # FTSE 100 Index
    }
    
    # Futures mappings
    futures_mappings = {
        # Metals
        'GOLD': 'GC=F',     # Gold Futures
        'SILVER': 'SI=F',    # Silver Futures
        'COPPER': 'HG=F',    # Copper Futures
        'PLATINUM': 'PL=F',  # Platinum Futures
        'PALLADIUM': 'PA=F', # Palladium Futures
        
        # Energy
        'OIL': 'CL=F',      # Crude Oil Futures
        'BRENT': 'BZ=F',    # Brent Crude Oil Futures
        'NATGAS': 'NG=F',   # Natural Gas Futures
        'HEATOIL': 'HO=F',  # Heating Oil Futures
        'GASOLINE': 'RB=F',  # RBOB Gasoline Futures
        
        # Agriculture
        'CORN': 'ZC=F',     # Corn Futures
        'WHEAT': 'ZW=F',    # Wheat Futures
        'SOYBEAN': 'ZS=F',  # Soybean Futures
        'COFFEE': 'KC=F',   # Coffee Futures
        'SUGAR': 'SB=F',    # Sugar Futures
        'COTTON': 'CT=F',   # Cotton Futures
        'COCOA': 'CC=F',    # Cocoa Futures
        'LUMBER': 'LBS=F',  # Lumber Futures
        'CATTLE': 'LE=F',   # Live Cattle Futures
        'HOGS': 'HE=F',     # Lean Hogs Futures
        
        # Financial
        'ES': 'ES=F',       # E-mini S&P 500 Futures
        'NQ': 'NQ=F',       # E-mini NASDAQ 100 Futures
        'RTY': 'RTY=F',     # E-mini Russell 2000 Futures
        'YM': 'YM=F',       # E-mini Dow Futures
        'VIX': 'VX=F',      # VIX Futures
        
        # Bonds/Rates
        'ZB': 'ZB=F',       # U.S. Treasury Bond Futures
        'ZN': 'ZN=F',       # 10-Year T-Note Futures
        'ZF': 'ZF=F',       # 5-Year T-Note Futures
        'ZT': 'ZT=F',       # 2-Year T-Note Futures
        
        # Currency
        'EURODOLLAR': 'GE=F',  # Euro FX Futures (EU)
        'GBPDOLLAR': '6B=F',   # British Pound Futures (UK)
        'JPYDOLLAR': '6J=F',   # Japanese Yen Futures (Japan)
        'CADDOLLAR': '6C=F',   # Canadian Dollar Futures (Canada)
        'AUDDOLLAR': '6A=F',   # Australian Dollar Futures (Australia)
        'CHFDOLLAR': '6S=F',   # Swiss Franc Futures (Switzerland)
        'CNHDOLLAR': 'CNH=F',  # Offshore Chinese Yuan Futures (China)
        'KRWDOLLAR': 'KRW=F',  # South Korean Won Futures (South Korea)
        'INRDOLLAR': 'INR=F',  # Indian Rupee Futures (India)
        'MXNDOLLAR': '6M=F',   # Mexican Peso Futures (Mexico)
        'BRLdollar': 'BRL=F',  # Brazilian Real Futures (Brazil)
        'SEKDOLLAR': 'SEK=F',  # Swedish Krona Futures (Sweden)
        'NZDDOLLAR': '6N=F',   # New Zealand Dollar Futures (New Zealand)
        'SGDDOLLAR': 'SGD=F',  # Singapore Dollar Futures (Singapore)
        'HKDDOLLAR': 'HKD=F',  # Hong Kong Dollar Futures (Hong Kong)
        'TWDDOLLAR': 'TWD=F',  # Taiwan Dollar Futures (Taiwan)
        'RUBDOLLAR': 'RUB=F',  # Russian Ruble Futures (Russia)
        'TRYDOLLAR': 'TRY=F',  # Turkish Lira Futures (Turkey)
        'PLNDOLLAR': 'PLN=F',  # Polish Zloty Futures (Poland)
        'IDRDOLLAR': 'IDR=F',  # Indonesian Rupiah Futures (Indonesia)
        'ZAEDOLLAR': 'ZAR=F',  # South African Rand Futures (South Africa)
        
        # Alternative search terms for currencies
        'POUND': '6B=F',       # Alternative for GBP
        'GBP': '6B=F',         # Alternative for British Pound
        'YEN': '6J=F',         # Alternative for JPY
        'JPY': '6J=F',         # Alternative for Japanese Yen
        'EURO': 'GE=F',        # Alternative for EUR
        'EUR': 'GE=F',         # Alternative for Euro
        'CAD': '6C=F',         # Alternative for Canadian Dollar
        'AUD': '6A=F',         # Alternative for Australian Dollar
        'CHF': '6S=F',         # Alternative for Swiss Franc
        'CNH': 'CNH=F',        # Alternative for Chinese Yuan
        'YUAN': 'CNH=F',       # Alternative for Chinese Yuan
        'RMB': 'CNH=F',        # Alternative for Chinese Yuan
        'KRW': 'KRW=F',        # Alternative for Korean Won
        'WON': 'KRW=F',        # Alternative for Korean Won
        'INR': 'INR=F',        # Alternative for Indian Rupee
        'RUPEE': 'INR=F',      # Alternative for Indian Rupee
        'MXN': '6M=F',         # Alternative for Mexican Peso
        'PESO': '6M=F',        # Alternative for Mexican Peso
        'BRL': 'BRL=F',        # Alternative for Brazilian Real
        'REAL': 'BRL=F',       # Alternative for Brazilian Real
        'SEK': 'SEK=F',        # Alternative for Swedish Krona
        'KRONA': 'SEK=F',      # Alternative for Swedish Krona
        'NZD': '6N=F',         # Alternative for New Zealand Dollar
        'KIWI': '6N=F',        # Alternative for New Zealand Dollar
        'SGD': 'SGD=F',        # Alternative for Singapore Dollar
        'HKD': 'HKD=F',        # Alternative for Hong Kong Dollar
        'TWD': 'TWD=F',        # Alternative for Taiwan Dollar
        'RUB': 'RUB=F',        # Alternative for Russian Ruble
        'RUBLE': 'RUB=F',      # Alternative for Russian Ruble
        'TRY': 'TRY=F',        # Alternative for Turkish Lira
        'LIRA': 'TRY=F',       # Alternative for Turkish Lira
        'PLN': 'PLN=F',        # Alternative for Polish Zloty
        'ZLOTY': 'PLN=F',      # Alternative for Polish Zloty
        'IDR': 'IDR=F',        # Alternative for Indonesian Rupiah
        'RUPIAH': 'IDR=F',     # Alternative for Indonesian Rupiah
        'ZAR': 'ZAR=F',        # Alternative for South African Rand
        'RAND': 'ZAR=F'        # Alternative for South African Rand
    }
    
    # ETF and asset mappings
    asset_mappings = {
        'NDQ': ['QQQ'],               # NASDAQ-100 ETF
        'SPX': ['SPY'],               # S&P 500 ETF
        'DJX': ['DIA'],               # Dow Jones ETF
        'FTSE': ['ISF.L', '^FTSE'],   # FTSE 100 ETF and Index
        'BTC': ['BTC-USD', 'BTC'],    # Bitcoin price and BTC Trust
        'ETH': ['ETH-USD', 'ETHE'],   # Ethereum and its ETF
        'GOLD': ['GC=F', 'GLD'], 
        'DXY':  ['DX-Y.NYB','US Dollar Index']
    }
    
    # Convert to uppercase for consistent matching
    symbol = symbol.upper()
    clean_symbol = symbol[1:] if symbol.startswith('^') else symbol
    
    # Get all variations for the symbol
    variations = []
    
    # Check futures first (for commodities)
    if clean_symbol in futures_mappings:
        variations.append(futures_mappings[clean_symbol])
    
    # Check if it's a known index
    if clean_symbol in index_mappings:
        variations.append(index_mappings[clean_symbol])
    
    # Check asset mappings for multiple variations
    if clean_symbol in asset_mappings:
        variations.extend(asset_mappings[clean_symbol])
        
    # If no mappings found, return original symbol
    return variations if variations else [symbol]

@bp.route('/search_ticker', methods=['GET'])
def search_ticker():
    query = request.args.get('query', '').upper()
    if not query or len(query) < 1:
        return jsonify([])
    
    try:
        search_results = []
        logger.info(f"Searching for ticker: {query}")
        
        # List of variations to try
        variations = [query]
        
        # Process exchange suffixes first
        exchange_suffix = None
        
        # Shanghai Stock Exchange (.SS)
        if (query.startswith('60') or query.startswith('68') or 
            query.startswith('51') or query.startswith('56') or
            query.startswith('58')) and len(query) == 6:
            exchange_suffix = '.SS'
            
        # Shenzhen Stock Exchange (.SZ)
        elif (query.startswith('00') or query.startswith('30')) and len(query) == 6:
            exchange_suffix = '.SZ'
            
        # Hong Kong Exchange (.HK)
        elif len(query) == 4 and query.isdigit():
            exchange_suffix = '.HK'

        # Check with exchange suffix if applicable
        if exchange_suffix:
            symbol_to_check = f"{query}{exchange_suffix}"
            is_valid, company_name = verify_ticker(symbol_to_check)
            
            if is_valid:
                # If symbol exists in TICKER_DICT, use that name instead
                if symbol_to_check in TICKER_DICT:
                    company_name = TICKER_DICT[symbol_to_check]
                
                if symbol_to_check.upper() != company_name.upper():  # Only add if symbol and name are different
                    search_results.append({
                        'symbol': symbol_to_check,
                        'name': company_name,
                        'source': 'verified',
                        'type': determine_asset_type(symbol_to_check, company_name)
                    })
                    logger.info(f"Found verified stock: {symbol_to_check}")
        
        # If no results from exchange suffix, try normalized variations
        if not search_results:
            normalized_variations = normalize_ticker(query)
            variations.extend([v for v in normalized_variations if v != query])
            
            for variant in variations:
                if variant != f"{query}{exchange_suffix}":  # Skip if already checked with exchange suffix
                    try:
                        is_valid, company_name = verify_ticker(variant)
                        if is_valid:
                            # If symbol exists in TICKER_DICT, use that name instead
                            if variant in TICKER_DICT:
                                company_name = TICKER_DICT[variant]
                                
                            if variant.upper() != company_name.upper():  # Only add if symbol and name are different
                                result = {
                                    'symbol': variant,
                                    'name': company_name,
                                    'source': 'verified',
                                    'type': determine_asset_type(variant, company_name)
                                }
                                search_results.append(result)
                                logger.info(f"Found verified asset: {variant}")
                    except Exception as e:
                        logger.warning(f"Error checking symbol {variant}: {str(e)}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_results = []
        for result in search_results:
            if result['symbol'] not in seen:
                seen.add(result['symbol'])
                unique_results.append(result)
        search_results = unique_results
                
        # Only proceed with local search if no verified stock was found
        if not search_results:
            # Add partial matches from local data
            if len(search_results) < 5:
                partial_matches = []
                for variant in variations:
                    matches = [
                        {'symbol': ticker['symbol'], 
                         'name': ticker['name'], 
                         'source': 'local',
                         'type': determine_asset_type(ticker['symbol'], ticker['name'])}
                        for ticker in TICKERS
                        if (variant in ticker['symbol'].upper() or 
                            variant in ticker['name'].upper()) and 
                            ticker['symbol'] not in seen and
                            ticker['symbol'].upper() != ticker['name'].upper()
                    ]
                    partial_matches.extend(matches)
                
                # Add partial matches up to limit
                for match in partial_matches:
                    if match['symbol'] not in seen:
                        seen.add(match['symbol'])
                        search_results.append(match)
                        if len(search_results) >= 5:
                            break
            
        return jsonify(search_results[:5])
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return jsonify([])

def determine_asset_type(symbol: str, name: str) -> str:
    """Determine the type of asset based on symbol and name."""
    symbol = symbol.upper()
    name = name.upper()
    
    if symbol.endswith('.HK'):
        return 'Hong Kong Stock'
    elif symbol.endswith('.SS'):
        return 'Shanghai Stock'
    elif symbol.endswith('.SZ'):
        return 'Shenzhen Stock'
    elif symbol.startswith('^'):
        return 'Index'
    elif symbol.endswith('=F'):
        return 'Futures'
    elif '-USD' in symbol:
        if symbol[:-4] in ['BTC', 'ETH', 'SOL', 'DOGE', 'XRP', 'ADA', 'DOT']:
            return 'Crypto'
        else:
            return 'Currency'
    elif any(currency in symbol for currency in ['HKD', 'CNH', 'JPY', 'EUR', 'GBP', 'AUD', 'CAD', 'CHF']):
        return 'Currency'
    elif 'ETF' in name:
        return 'ETF'
    elif 'TRUST' in name:
        return 'Trust'
    return None


@bp.route('/quick_analyze', methods=['POST'])
def quick_analyze():
    try:
        ticker_input = request.form.get('ticker', '').split()[0].upper()
        if not ticker_input:
            raise ValueError("Ticker symbol is required")
            
        # Use default values for quick analysis
        fig = create_stock_visualization_old(
            ticker_input,
            end_date=None,  # Use current date
            lookback_days=ANALYZE_CONFIG['lookback_days'],  # Default lookback
            crossover_days=ANALYZE_CONFIG['crossover_days']  # Default crossover
        )
        
        # Create HTML content with navigation buttons
        nav_buttons = [
            {'url': url_for('main.index'), 'text': 'Home', 'class': 'blue-500'},
            {'url': url_for('news.search', symbol=ticker_input), 'text': 'News', 'class': 'green-500'}
        ]
        
        # Generate HTML for navigation buttons
        nav_buttons_html = ''.join([
            f'<a href="{button["url"]}" '
            f'class="px-4 py-2 bg-{button["class"]} text-white rounded-md hover:bg-{button["class"]}/80 '
            f'transition-colors">{button["text"]}</a>'
            for button in nav_buttons
        ])
        
        # Add Tailwind CSS CDN
        tailwind_css = '<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">'
        
        # Get the plotly figure HTML
        plot_html = fig.to_html(
            full_html=True,
            include_plotlyjs=True,
            config={'responsive': True}
        )
        
        # Insert Tailwind CSS and navigation buttons
        html_content = plot_html.replace(
            '</body>',
            f'<div class="fixed top-4 left-4 flex space-x-4" style="margin-bottom: 60px;">{nav_buttons_html}</div></body>'
        ).replace(
            '</head>',
            f'{tailwind_css}</head>'
        )
        
        response = make_response(html_content)
        response.headers['Content-Type'] = 'text/html'
        return response
        
    except Exception as e:
        error_msg = f"Error analyzing {ticker_input}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return f'<div class="text-red-500">Error: {error_msg}</div>', 500

@bp.route('/analyze', methods=['POST'])
@login_required
def analyze():
    try:
        ticker_input = request.form.get('ticker', '').split()[0].upper()
        logger.info(f"Analyzing ticker: {ticker_input}")
        
        if not ticker_input:
            raise ValueError("Ticker symbol is required")
        
        end_date = request.form.get('end_date')
        if end_date:
            try:
                datetime.strptime(end_date, '%Y-%m-%d')
                logger.info(f"Using end date: {end_date}")
            except ValueError:
                raise ValueError("Invalid date format. Please use YYYY-MM-DD format")
        
        lookback_days = int(request.form.get('lookback_days', 365))
        if lookback_days < 30 or lookback_days > 10000:
            raise ValueError("Lookback days must be between 30 and 10000")
        
        crossover_days = int(request.form.get('crossover_days', 365))
        if crossover_days < 30 or crossover_days > 1000:
            raise ValueError("Crossover days must be between 30 and 1000")
        
        fig = create_stock_visualization_old(
            ticker_input,
            end_date=end_date,
            lookback_days=lookback_days,
            crossover_days=crossover_days
        )
        
        # Create HTML content with navigation buttons
        nav_buttons = [
            {'url': url_for('main.index'), 'text': 'Home', 'class': 'blue-500'},
            {'url': url_for('news.search', symbol=ticker_input), 'text': 'News', 'class': 'green-500'}
        ]
        
        # Generate HTML for navigation buttons
        nav_buttons_html = ''.join([
            f'<a href="{button["url"]}" '
            f'class="px-4 py-2 bg-{button["class"]} text-white rounded-md hover:bg-{button["class"]}/80 '
            f'transition-colors">{button["text"]}</a>'
            for button in nav_buttons
        ])
        
        # Add Tailwind CSS CDN
        tailwind_css = '<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">'
        
        # Get the plotly figure HTML
        plot_html = fig.to_html(
            full_html=True,
            include_plotlyjs=True,
            config={'responsive': True}
        )
        
        # Insert Tailwind CSS and navigation buttons
        html_content = plot_html.replace(
            '</body>',
            f'<div class="fixed top-4 left-4 flex space-x-4" style="margin-bottom: 60px;">{nav_buttons_html}</div></body>'
        ).replace(
            '</head>',
            f'{tailwind_css}</head>'
        )
        
        response = make_response(html_content)
        response.headers['Content-Type'] = 'text/html'
        return response
        
    except Exception as e:
        error_msg = f"Error analyzing {ticker_input}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return f'<div class="text-red-500">Error: {error_msg}</div>', 500

@bp.route('/tables')
@admin_required
def tables():
    """Show database tables in document tree structure"""
    try:
        logger.info('Accessing database tables view')
        
        # Get all tables from database
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        logger.info(f'Found {len(tables)} tables in database')
        
        # Organize tables by type
        historical_tables = []
        financial_tables = []
        other_tables = []
        
        for table in tables:
            try:
                table_info = {
                    'name': table
                }
                
                if table.startswith('his_'):
                    ticker = table.replace('his_', '').upper()
                    historical_tables.append({
                        **table_info,
                        'ticker': ticker,
                        'type': 'Historical Data'
                    })
                    
                elif table.startswith('roic_'):
                    ticker = table.replace('roic_', '').upper()
                    financial_tables.append({
                        **table_info,
                        'ticker': ticker,
                        'type': 'Financial Data'
                    })
                    
                else:
                    other_tables.append({
                        **table_info,
                        'type': 'Other'
                    })
                    
            except Exception as table_error:
                logger.error(f"Error processing table {table}: {str(table_error)}")
                continue

        return render_template(
            'tables.html',
            historical_tables=historical_tables,
            financial_tables=financial_tables,
            other_tables=other_tables
        )
        
    except Exception as e:
        error_msg = f"Error fetching database tables: {str(e)}"
        logger.error(f"{error_msg}")
        return render_template('tables.html', error=error_msg)

@bp.route('/delete_table/<table_name>', methods=['POST'])
@admin_required
def delete_table(table_name):
    """Delete a table from database"""
    try:
        logger.info(f'Attempting to delete table: {table_name}')
        
        # Check if table exists
        inspector = inspect(db.engine)
        if table_name not in inspector.get_table_names():
            logger.error(f'Table {table_name} not found')
            return jsonify({'success': False, 'error': 'Table not found'}), 404

        # Use backticks to properly escape table name
        query = text(f'DROP TABLE `{table_name}`')
        db.session.execute(query)
        db.session.commit()
        
        logger.info(f'Successfully deleted table: {table_name}')
        return jsonify({'success': True, 'message': f'Table {table_name} deleted successfully'})
        
    except Exception as e:
        error_msg = f"Error deleting table {table_name}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': error_msg}), 500

@bp.route('/table-content/<table_name>')
@admin_required
def show_table_content(table_name):
    """Show the content of a specific table with sorting and pagination"""
    try:
        # Get sort parameters from URL
        sort_column = request.args.get('sort', 'Date')  # Default sort by Date
        sort_direction = request.args.get('direction', 'desc')  # Default descending
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)  # 50 items per page

        # Calculate offset
        offset = (page - 1) * per_page

        # Count total rows
        count_query = text(f'SELECT COUNT(*) FROM `{table_name}`')
        total_rows = db.session.execute(count_query).scalar()
        total_pages = (total_rows + per_page - 1) // per_page

        # Get all column names
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        
        # If sort column not in columns, use first column
        if sort_column not in columns and columns:
            sort_column = columns[0]

        # Build query with sorting and pagination
        query = text(f'''
            SELECT * FROM `{table_name}`
            ORDER BY `{sort_column}` {sort_direction}
            LIMIT :limit OFFSET :offset
        ''')
        
        # Execute query and fetch results
        result = db.session.execute(query, {'limit': per_page, 'offset': offset})
        
        # Convert results to list of dictionaries
        data = []
        for row in result:
            row_dict = {}
            for idx, col in enumerate(columns):
                row_dict[col] = row[idx]
            data.append(row_dict)
        
        return render_template(
            'table_content.html',
            table_name=table_name,
            columns=columns,
            data=data,
            current_page=page,
            total_pages=total_pages,
            per_page=per_page,
            sort_column=sort_column,
            sort_direction=sort_direction,
            total_rows=total_rows
        )
        
    except Exception as e:
        error_msg = f"Error fetching content for table {table_name}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return render_template('table_content.html', error=error_msg)


@bp.route('/export/<table_name>/<format>')
@admin_required
def export_table(table_name, format):
    """Export table data in CSV or Excel format"""
    try:
        # Get all data from table
        query = text(f'SELECT * FROM `{table_name}`')
        result = db.session.execute(query)
        
        # Get column names
        columns = result.keys()
        
        # Convert to DataFrame
        df = pd.DataFrame([dict(row) for row in result], columns=columns)
        
        # Create buffer for file
        buffer = io.BytesIO()
        
        if format == 'csv':
            # Export as CSV
            df.to_csv(buffer, index=False)
            buffer.seek(0)
            return send_file(
                buffer,
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'{table_name}.csv'
            )
            
        elif format == 'excel':
            # Export as Excel
            df.to_excel(buffer, index=False)
            buffer.seek(0)
            return send_file(
                buffer,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=f'{table_name}.xlsx'
            )
        
        else:
            return jsonify({'error': 'Unsupported format'}), 400
            
    except Exception as e:
        error_msg = f"Error exporting table {table_name}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({'error': error_msg}), 500


@bp.route('/delete_all_historical', methods=['POST'])
@admin_required
def delete_all_historical():
    """Delete all historical data tables"""
    try:
        logger.info('Attempting to delete all historical data tables')
        
        # Get all tables from database
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        # Filter for historical tables
        historical_tables = [table for table in tables if table.startswith('his_')]
        
        if not historical_tables:
            return jsonify({
                'success': False, 
                'error': 'No historical tables found'
            }), 404
        
        # Delete each historical table
        deleted_count = 0
        errors = []
        
        for table in historical_tables:
            try:
                query = text(f'DROP TABLE `{table}`')
                db.session.execute(query)
                deleted_count += 1
            except Exception as table_error:
                error_msg = f"Error deleting table {table}: {str(table_error)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Commit the transaction
        db.session.commit()
        
        # Prepare response message
        if deleted_count == len(historical_tables):
            message = f'Successfully deleted all {deleted_count} historical tables'
            logger.info(message)
            return jsonify({
                'success': True,
                'message': message
            })
        else:
            message = f'Partially completed: Deleted {deleted_count} out of {len(historical_tables)} tables'
            if errors:
                message += f'. Errors: {"; ".join(errors)}'
            logger.warning(message)
            return jsonify({
                'success': True,
                'message': message
            })
            
    except Exception as e:
        error_msg = f"Error deleting historical tables: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500

    
@bp.route('/delete_all_financial', methods=['POST'])
@admin_required
def delete_all_financial():
    """Delete all financial data tables"""
    try:
        logger.info('Attempting to delete all financial data tables')
        
        # Get all tables from database
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        # Filter for financial tables
        financial_tables = [table for table in tables if table.startswith('roic_')]
        
        if not financial_tables:
            return jsonify({
                'success': False, 
                'error': 'No financial tables found'
            }), 404
        
        # Delete each financial table
        deleted_count = 0
        errors = []
        
        for table in financial_tables:
            try:
                query = text(f'DROP TABLE `{table}`')
                db.session.execute(query)
                deleted_count += 1
            except Exception as table_error:
                error_msg = f"Error deleting table {table}: {str(table_error)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Commit the transaction
        db.session.commit()
        
        # Prepare response message
        if deleted_count == len(financial_tables):
            message = f'Successfully deleted all {deleted_count} financial tables'
            logger.info(message)
            return jsonify({
                'success': True,
                'message': message
            })
        else:
            message = f'Partially completed: Deleted {deleted_count} out of {len(financial_tables)} tables'
            if errors:
                message += f'. Errors: {"; ".join(errors)}'
            logger.warning(message)
            return jsonify({
                'success': True,
                'message': message
            })
            
    except Exception as e:
        error_msg = f"Error deleting financial tables: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500


from flask import Response
import json
import queue
import threading

# Create a queue for progress updates
# Add/update these routes in routes.py

# Create a queue for progress updates
# progress_queue = queue.Queue()

# def send_progress_update(current, total, message=None):
#     """Helper function to send progress updates"""
#     progress_queue.put({
#         'current': current,
#         'total': total,
#         'message': message
#     })
#     logger.debug(f'Progress update queued: {current}/{total} - {message}')  # Debug log

# @bp.route('/create_progress')
# def progress():
#     """SSE endpoint for progress updates"""
#     def generate():
#         while True:
#             try:
#                 # Get progress update from queue with timeout
#                 progress_data = progress_queue.get(timeout=60)
#                 logger.debug(f'Sending progress update: {progress_data}')  # Debug log
#                 yield f"data: {json.dumps(progress_data)}\n\n"
#             except queue.Empty:
#                 logger.debug('Progress queue timeout')  # Debug log
#                 break
#             except Exception as e:
#                 logger.error(f'Error in progress generator: {str(e)}')
#                 break
                
#     return Response(generate(), mimetype='text/event-stream')

@bp.route('/create_all_historical', methods=['POST'])
@admin_required
def create_all_historical():
    """Create historical data tables for tickers that don't exist in database"""
    try:
        logger.info('Attempting to create missing historical data tables')
        
        # Load tickers
        try:
            tickers, _ = load_tickers()
            logger.info(f'Successfully loaded {len(tickers)} tickers')
        except Exception as e:
            logger.error(f'Error loading tickers: {str(e)}')
            return jsonify({
                'success': False,
                'error': f'Failed to load tickers: {str(e)}'
            }), 500

        if not tickers:
            logger.error('No tickers found in tickers.ts')
            return jsonify({
                'success': False,
                'error': 'No tickers found in tickers.ts'
            }), 404
            
        # Get DataService instance
        try:
            from app.utils.data.data_service import DataService
            data_service = DataService()
        except Exception as e:
            logger.error(f'Error initializing DataService: {str(e)}')
            return jsonify({
                'success': False,
                'error': f'Failed to initialize data service: {str(e)}'
            }), 500
            
        # Get list of existing tables
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        # Filter out tickers that already have tables
        missing_tickers = []
        for ticker_obj in tickers:
            ticker = ticker_obj['symbol']
            cleaned_ticker = data_service.clean_ticker_for_table_name(ticker)
            table_name = f"his_{cleaned_ticker}"
            if table_name not in existing_tables:
                missing_tickers.append(ticker_obj)
                
        logger.info(f'Found {len(missing_tickers)} missing historical tables to create')
        
        if not missing_tickers:
            return jsonify({
                'success': True,
                'message': 'All historical tables already exist'
            })
            
        # Get date range for historical data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365*10)
            
        # Process missing tickers
        def process_tickers():
            created_count = 0
            errors = []
            skipped = []
            total = len(missing_tickers)
            rate_limiter = RateLimiter(calls_per_second=2)

            for i, ticker_obj in enumerate(missing_tickers, 1):
                try:
                    
                    ticker = ticker_obj['symbol']
                    send_progress_update(i, total, f'Processing {ticker}...')
                    
                    # Add rate limiting
                    rate_limiter.wait()
                    
                    # Skip certain types of symbols
                    if any(x in ticker for x in ['^', '/', '\\']):
                        skipped.append(f"{ticker} (invalid symbol)")
                        logger.info(f'Skipping invalid symbol: {ticker}')
                        continue
                        
                    success = data_service.store_historical_data_with_retry(
                        ticker,
                        start_date=start_date.strftime('%Y-%m-%d'),
                        end_date=end_date.strftime('%Y-%m-%d')
                    )
                    
                    if success:
                        created_count += 1
                        send_progress_update(i, total, f'Created table for {ticker}')
                    else:
                        errors.append(f"Failed to create table for {ticker}")
                        send_progress_update(i, total, f'Failed to create table for {ticker}')
                        
                except Exception as ticker_error:
                    error_msg = f"Error processing {ticker}: {str(ticker_error)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    send_progress_update(i, total, error_msg)
                    # Add a small delay after errors
                    sleep(2)

                # Add a small random delay between requests
                sleep(random.uniform(0.1, 0.3))
            
            # Send final summary
            summary = []
            if created_count > 0:
                summary.append(f'Successfully created {created_count} missing tables')
            if errors:
                summary.append(f'Encountered {len(errors)} errors')
            if skipped:
                summary.append(f'Skipped {len(skipped)} invalid symbols')
            
            send_progress_update(total, total, '. '.join(summary))
        
        # Start processing in background thread
        thread = threading.Thread(target=process_tickers)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Started creating missing tables'
        })
            
    except Exception as e:
        error_msg = f"Error in create_all_historical: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# First ensure these imports are at the top of routes.py
import json
import queue
import gc
import threading
from datetime import datetime
from time import sleep
import traceback
from flask import jsonify, Response
from sqlalchemy import inspect

# Progress queue for SSE updates
progress_queue = queue.Queue()

def send_progress_update(current, total, message=None):
    """Helper function to send progress updates"""
    progress_queue.put({
        'current': current,
        'total': total,
        'message': message
    })
    logger.debug(f'Progress update: {current}/{total} - {message}')

@bp.route('/create_all_financial', methods=['POST'])
@admin_required
def create_all_financial():
    """Create financial data tables for tickers that don't exist in database"""
    try:
        logger.info('Attempting to create missing financial data tables')
        
        # Load tickers
        try:
            tickers, _ = load_tickers()
            logger.info(f'Successfully loaded {len(tickers)} tickers')
        except Exception as e:
            logger.error(f'Error loading tickers: {str(e)}')
            return jsonify({
                'success': False,
                'error': f'Failed to load tickers: {str(e)}'
            }), 500

        if not tickers:
            logger.error('No tickers found in tickers.ts')
            return jsonify({
                'success': False,
                'error': 'No tickers found in tickers.ts'
            }), 404
            
        # Initialize DataService
        try:
            from app.utils.data.data_service import DataService
            data_service = DataService()
        except Exception as e:
            logger.error(f'Error initializing DataService: {str(e)}')
            return jsonify({
                'success': False,
                'error': f'Failed to initialize data service: {str(e)}'
            }), 500
            
        # Get list of existing tables
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        # Filter out non-US stocks and tickers that already have tables
        missing_tickers = []
        for ticker_obj in tickers:
            ticker = ticker_obj['symbol']
            cleaned_ticker = data_service.clean_ticker_for_table_name(ticker)
            table_name = f"roic_{cleaned_ticker}"
            if table_name not in existing_tables:
                    missing_tickers.append(ticker_obj)
                    
        logger.info(f'Found {len(missing_tickers)} missing financial tables to create')
        
        if not missing_tickers:
            return jsonify({
                'success': True,
                'message': 'All financial tables already exist'
            })

        # In create_all_financial() route, update the process_tickers function:

        def process_tickers():
            created_count = 0
            errors = []
            total = len(missing_tickers)
            current = 0
            
            end_year = str(datetime.now().year)
            start_year = str(int(end_year) - 10)
            
            # Configuration for batching
            BATCH_SIZE = 10  # Increased from 5 to 10
            BATCH_DELAY = 30  # Reduced from 60 to 30 seconds
            ERROR_DELAY = 10  # Reduced from 30 to 10 seconds
            
            # Process tickers in batches
            for i in range(0, total, BATCH_SIZE):
                batch = missing_tickers[i:i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
                
                msg = f"Processing batch {batch_num} of {total_batches}..."
                logger.info(msg)
                send_progress_update(current, total, msg)
                
                for ticker_obj in batch:
                    try:
                        current += 1
                        ticker = ticker_obj['symbol']
                        
                        msg = f'Processing {ticker} ({current}/{total})...'
                        logger.info(msg)
                        send_progress_update(current, total, msg)
                        
                        success = data_service.store_financial_data(
                            ticker,
                            start_year=start_year,
                            end_year=end_year
                        )
                        
                        if success:
                            created_count += 1
                            msg = f'✓ Created financial table for {ticker}'
                        else:
                            msg = f'✗ Failed to create table for {ticker}'
                            errors.append(ticker)
                            
                        logger.info(msg)
                        send_progress_update(current, total, msg)
                        
                        # Short delay between tickers
                        sleep(1)  # Reduced from 2 seconds
                        
                    except Exception as e:
                        error_msg = f"Error processing {ticker}: {str(e)}"
                        logger.error(error_msg)
                        errors.append(ticker)
                        send_progress_update(current, total, f'✗ {error_msg}')
                        sleep(ERROR_DELAY)
                
                # After each batch
                if batch_num < total_batches:
                    msg = f'Completed batch {batch_num}. Pausing for {BATCH_DELAY} seconds...'
                    logger.info(msg)
                    send_progress_update(current, total, msg)
                    sleep(BATCH_DELAY)
            
            # Final summary
            final_msg = []
            if created_count > 0:
                final_msg.append(f'✓ Created {created_count} tables')
            if errors:
                final_msg.append(f'✗ Failed: {len(errors)} tables')
            
            send_progress_update(total, total, ' | '.join(final_msg))
                
        # Start processing in background thread
        thread = threading.Thread(target=process_tickers)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Started creating missing tables'
        })
            
    except Exception as e:
        error_msg = f"Error in create_all_financial: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/create_progress')
def progress():
    """SSE endpoint for progress updates"""
    def generate():
        while True:
            try:
                # Get progress update from queue with timeout
                progress_data = progress_queue.get(timeout=60)
                logger.debug(f'Sending progress update: {progress_data}')
                yield f"data: {json.dumps(progress_data)}\n\n"
            except queue.Empty:
                logger.debug('Progress queue timeout')
                break
            except Exception as e:
                logger.error(f'Error in progress generator: {str(e)}')
                break
                
    return Response(generate(), mimetype='text/event-stream')



# app/routes.py

# app/routes.py