# app/data/data_service.py

import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from app.utils.config.metrics_config import METRICS_MAP, CAGR_METRICS
from sqlalchemy import create_engine, inspect, text
import os
import logging
import re
from app.utils.visualization.visualization_service import is_stock

from time import sleep
from functools import wraps
import random
import time
import traceback

# Configure logger
logger = logging.getLogger(__name__)

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries:
                        raise
                    sleep_time = (backoff_in_seconds * 2 ** x +
                                random.uniform(0, 1))
                    sleep(sleep_time)
                    x += 1
        return wrapper
    return decorator

class RateLimiter:
    def __init__(self, calls_per_second=2):
        self.calls_per_second = calls_per_second
        self.last_call_time = 0

    def wait(self):
        current_time = time.time()
        time_since_last_call = current_time - self.last_call_time
        time_to_wait = (1.0 / self.calls_per_second) - time_since_last_call
        
        if time_to_wait > 0:
            sleep(time_to_wait)
            
        self.last_call_time = time.time()

class DataService:
    def __init__(self):
        """Initialize DataService with API and database configuration"""
        self.API_KEY = "a365bff224a6419fac064dd52e1f80d9"
        self.BASE_URL = "https://api.roic.ai/v1/rql"
        self.METRICS = METRICS_MAP
        self.CAGR_METRICS = CAGR_METRICS
        
        # Add EODHD configuration
        self.EODHD_API_KEY = os.getenv('EODHD_API_KEY')
        self.EODHD_BASE_URL = "https://eodhd.com/api"
        
        # Database configuration
        self.engine = create_engine(
            f"mysql+pymysql://{os.getenv('MYSQL_USER')}:"
            f"{os.getenv('MYSQL_PASSWORD')}@"
            f"{os.getenv('MYSQL_HOST')}:"
            f"{os.getenv('MYSQL_PORT', '3306')}/"
            f"{os.getenv('MYSQL_DATABASE')}"
        )

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists in database"""
        try:
            inspector = inspect(self.engine)
            return table_name in inspector.get_table_names()
        except Exception as e:
            print(f"Error checking table existence: {e}")
            return False

    def store_dataframe(self, df: pd.DataFrame, table_name: str) -> bool:
        """Store DataFrame in database"""
        try:
            df.to_sql(
                name=table_name,
                con=self.engine,
                index=True,
                if_exists='replace',
                chunksize=10000
            )
            print(f"Successfully stored data in table: {table_name}")
            return True
        except Exception as e:
            print(f"Error storing DataFrame in table {table_name}: {e}")
            return False

    def clean_ticker_for_table_name(self, ticker: str) -> str:
        """
        Clean ticker symbol for use in table name.
        Removes special characters and converts to valid table name format.
        
        Parameters:
        -----------
        ticker : str
            Original ticker symbol
        
        Returns:
        --------
        str
            Cleaned ticker symbol safe for use in table names
        """
        # Replace any non-alphanumeric characters with underscore
        cleaned = ''.join(c if c.isalnum() else '_' for c in ticker)
        # Remove leading/trailing underscores
        cleaned = cleaned.strip('_')
        # Convert to lowercase
        cleaned = cleaned.lower()
        # If the cleaned string is empty, use a default
        if not cleaned:
            cleaned = 'unknown'
        return cleaned
    
    
    
    def get_historical_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data from MySQL database or yfinance.
        Updates database with new data if requested end date is beyond max date.
        
        Parameters:
        -----------
        ticker : str
            Stock ticker symbol
        start_date : str
            Start date in YYYY-MM-DD format
        end_date : str
            End date in YYYY-MM-DD format
        
        Returns:
        --------
        pd.DataFrame
            DataFrame containing historical price data for the requested date range
        """
        cleaned_ticker = self.clean_ticker_for_table_name(ticker)
        table_name = f"his_{cleaned_ticker}"
        
        try:
            # Get the latest trading day (last Friday if weekend)
            latest_trading_day = pd.Timestamp.now()
            while latest_trading_day.weekday() > 4:  # 5 = Saturday, 6 = Sunday
                latest_trading_day -= pd.Timedelta(days=1)
            latest_trading_day = latest_trading_day.strftime('%Y-%m-%d')
            
            # Adjust end_date if it's beyond latest trading day
            end_date = min(pd.to_datetime(end_date), pd.to_datetime(latest_trading_day)).strftime('%Y-%m-%d')
            
            # Check if table exists in database
            if self.table_exists(table_name):
                logging.info(f"Getting historical data for {ticker} from database")
                
                # Get table's date range
                date_range_query = text(f"""
                    SELECT MIN(Date) as min_date, MAX(Date) as max_date 
                    FROM {table_name}
                """)
                date_range = pd.read_sql_query(date_range_query, self.engine)
                
                # Check for None in date_range values
                min_date = date_range['min_date'][0]
                max_date = date_range['max_date'][0]
                
                # If min_date or max_date is None, refresh all data
                if min_date is None or max_date is None:
                    logging.info(f"Database date range is invalid for {ticker}: min_date={min_date}, max_date={max_date}")
                    logging.info("Refreshing data from external source...")
                    success = self.store_historical_data(ticker)
                    if not success:
                        raise ValueError(f"Failed to store data for {ticker}")
                    df = pd.read_sql_table(table_name, self.engine)
                    df.set_index('Date', inplace=True)
                    return df[(df.index >= start_date) & (df.index <= end_date)]
                
                # Convert dates for comparison
                db_start = pd.to_datetime(min_date).strftime('%Y-%m-%d')
                db_end = pd.to_datetime(max_date).strftime('%Y-%m-%d')
                current_date = pd.Timestamp.now().strftime('%Y-%m-%d')
                
                # Calculate default 10-year period
                default_start = (pd.Timestamp.now() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')
                
                # If requested start date is before both database start and default period
                if (start_date < db_start) and (start_date < default_start):
                    logging.info(f"Requested start date {start_date} is before database range and default period")
                    logging.info("Fetching data directly from yfinance...")
                    
                    # Fetch data directly for the requested period
                    ticker_obj = yf.Ticker(ticker)
                    df = ticker_obj.history(start=start_date, end=end_date)
                    if df.empty:
                        raise ValueError(f"No data found for {ticker} in requested date range")
                    df.index = df.index.tz_localize(None)
                    return df

                # If requested start date is before database start but within default period
                if start_date < db_start:
                    logging.info(f"Requested start date {start_date} is before database start date {db_start}")
                    logging.info("Fetching additional historical data from yfinance...")
                    
                    # Fetch additional historical data
                    ticker_obj = yf.Ticker(ticker)
                    new_data = ticker_obj.history(start=start_date, end=db_start)
                    new_data.index = new_data.index.tz_localize(None)
                    
                    # Read existing data
                    existing_data = pd.read_sql_table(table_name, self.engine)
                    existing_data.set_index('Date', inplace=True)
                    
                    # Combine datasets
                    combined_data = pd.concat([new_data, existing_data])
                    combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                    combined_data.sort_index(inplace=True)
                    
                    # Update database
                    success = self.store_dataframe(combined_data, table_name)
                    if not success:
                        raise ValueError(f"Failed to update data for {ticker}")
                    
                    return combined_data[(combined_data.index >= start_date) & (combined_data.index <= end_date)]
                
                # Check if data needs updating (more than 10 days old)
                days_difference = (pd.to_datetime(current_date) - pd.to_datetime(db_end)).days
                if days_difference >= 1:
                    logging.info(f"Data is {days_difference} days old. Updating from yfinance...")
                    
                    # Delete the last 10 days of data
                    cutoff_date = pd.to_datetime(db_end) - pd.Timedelta(days=10)
                    
                    # Read existing data
                    existing_data = pd.read_sql_table(table_name, self.engine)
                    existing_data.set_index('Date', inplace=True)
                    existing_data = existing_data[existing_data.index < cutoff_date]
                    
                    # Fetch new data
                    ticker_obj = yf.Ticker(ticker)
                    new_data = ticker_obj.history(start=cutoff_date.strftime('%Y-%m-%d'))
                    new_data.index = new_data.index.tz_localize(None)
                    
                    # Combine datasets
                    combined_data = pd.concat([existing_data, new_data])
                    combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                    combined_data.sort_index(inplace=True)
                    
                    # Update database
                    success = self.store_dataframe(combined_data, table_name)
                    if not success:
                        raise ValueError(f"Failed to update data for {ticker}")
                    
                    return combined_data[(combined_data.index >= start_date) & (combined_data.index <= end_date)]
                
                # If data is current enough, return filtered data from database
                df = pd.read_sql_table(table_name, self.engine)
                df.set_index('Date', inplace=True)
                return df[(df.index >= start_date) & (df.index <= end_date)]
            
            # If table doesn't exist, check if beyond default period
            default_start = (pd.Timestamp.now() - pd.DateOffset(years=20)).strftime('%Y-%m-%d')
            if start_date < default_start:
                logging.info(f"Requested start date {start_date} is beyond default period and no existing data")
                # Fetch data directly from yfinance for the specific period
                ticker_obj = yf.Ticker(ticker)
                df = ticker_obj.history(start=start_date, end=end_date)
                if df.empty:
                    raise ValueError(f"No data found for {ticker} in requested date range")
                df.index = df.index.tz_localize(None)
                return df
            
            # If within default period, store all historical data first
            logging.info(f"Data not found in database for {ticker}, fetching data")
            success = self.store_historical_data(ticker)
            if not success:
                raise ValueError(f"Failed to store data for {ticker}")
            df = pd.read_sql_table(table_name, self.engine)
            df.set_index('Date', inplace=True)
            return df[(df.index >= start_date) & (df.index <= end_date)]
                    
        except Exception as e:
            logging.error(f"Error in get_historical_data for {ticker}: {str(e)}")
            raise
        
        
    def get_financial_data(self, ticker: str, metric_description: str, start_year: str, end_year: str) -> pd.Series:
        """Get financial data from database first, if not exists then fetch from EODHD API and store it."""
        cleaned_ticker = self.clean_ticker_for_table_name(ticker)
        table_name = f"roic_{cleaned_ticker}"
        values = {}

        try:
            if not is_stock(ticker):
                return None

            # First check if data exists in database
            if self.table_exists(table_name):
                logger.info(f"Getting financial data for {ticker} from database")
                df = pd.read_sql_table(table_name, self.engine)
                if not df.empty:
                    for year in range(int(start_year), int(end_year) + 1):
                        year_data = df[df['fiscal_year'] == year]
                        if not year_data.empty:
                            metric_field = METRICS_MAP.get(metric_description)
                            if metric_field in year_data.columns:
                                values[year] = year_data[metric_field].iloc[0]
                    if values:
                        return pd.Series(values)

            # If not in database or incomplete, get from EODHD API
            logger.info(f"Getting financial data for {ticker} from EODHD API")
            
            # Get data from EODHD
            eodhd_ticker = self.convert_to_eodhd_ticker(ticker)
            eodhd_url = f"{self.EODHD_BASE_URL}/fundamentals/{eodhd_ticker}?api_token={self.EODHD_API_KEY}&fmt=json"
            response = requests.get(eodhd_url)
            
            if response.status_code != 200:
                raise ValueError(f"EODHD API request failed with status {response.status_code}")
            
            data = response.json()
            logger.debug(f"EODHD Data Structure:")
            logger.debug(f"Keys in root: {list(data.keys())}")
            if 'Financials' in data:
                logger.debug(f"Keys in Financials: {list(data['Financials'].keys())}")
            
            # Process the data
            financial_data = []
            metric_field = METRICS_MAP.get(metric_description)
            
            # Get all required data
            income_data = data.get('Financials', {}).get('Income_Statement', {}).get('yearly', {})
            shares_data = data.get('outstandingShares', {}).get('annual', {})
            balance_data = data.get('Financials', {}).get('Balance_Sheet', {}).get('yearly', {})
            cash_flow_data = data.get('Financials', {}).get('Cash_Flow', {}).get('yearly', {})
            
            # Process each year
            current_year = datetime.now().year
            for year in range(int(start_year), int(end_year) + 1):
                try:
                    # Skip future years and current year (likely incomplete)
                    if year >= current_year:
                        continue

                    year_data = {
                        'fiscal_year': year,
                        'period_label': 'FY',
                        'period_end_date': f"{year}-12-31"
                    }

                    # Get net income and revenue
                    for date, entry in income_data.items():
                        if str(year) in date:
                            try:
                                net_income = float(entry.get('netIncome') or 0)
                                revenue = float(entry.get('totalRevenue') or 0)
                                operating_income = float(entry.get('operatingIncome') or 0)
                                # Only store if we have actual data (non-zero values)
                                if net_income != 0 and revenue != 0:
                                    year_data['is_net_income'] = net_income
                                    year_data['is_sales_and_services_revenues'] = revenue
                                    if revenue > 0:
                                        year_data['oper_margin'] = float(f"{(operating_income / revenue * 100):.15f}")
                            except (TypeError, ValueError) as e:
                                logger.warning(f"Error processing income data for {year}: {str(e)}")
                            break

                    # Get shares data
                    shares = None
                    # Get shares from Balance Sheet commonStock
                    for date, entry in balance_data.items():
                        if str(year) in date:
                            common_stock = entry.get('commonStock')
                            if common_stock:
                                shares = self.get_shares_from_common_stock(common_stock, ticker)
                                break

                    # Calculate EPS only if we have valid shares and net income
                    if shares and shares > 0 and 'is_net_income' in year_data:
                        year_data['is_sh_for_diluted_eps'] = shares
                        year_data['eps'] = year_data['is_net_income'] / shares

                    # Get cash flow data
                    for date, entry in cash_flow_data.items():
                        if str(year) in date:
                            cf_oper = float(entry.get('totalCashFromOperatingActivities', 0))
                            cap_ex = float(entry.get('capitalExpenditures', 0))
                            if cf_oper != 0 and cap_ex != 0:  # Changed from 'or' to 'and'
                                year_data['cf_cash_from_oper'] = cf_oper
                                year_data['cf_cap_expenditures'] = cap_ex
                            break

                    # Get balance sheet data and calculate ROIC
                    for date, entry in balance_data.items():
                        if str(year) in date:
                            # Create income_stmt and balance_sheet DataFrames for ROIC calculation
                            income_stmt = pd.DataFrame(income_data).T
                            balance_sheet = pd.DataFrame(balance_data).T
                            
                            # Calculate ROIC using original method
                            year_data['return_on_inv_capital'] = self.calculate_roic(income_stmt, balance_sheet, date)
                            break

                    # Store the requested metric in values dict if it exists and is valid
                    if metric_field in year_data and year_data[metric_field] != 0:
                        values[year] = year_data[metric_field]

                    # Only append year_data if it contains complete data
                    required_fields = ['is_net_income', 'is_sales_and_services_revenues', 'eps']
                    if all(field in year_data for field in required_fields):
                        financial_data.append(year_data)

                except Exception as e:
                    logger.error(f"Error processing data for {year}: {str(e)}")

            # Store all data in database
            if financial_data:
                df = pd.DataFrame(financial_data)
                self.store_dataframe(df, table_name)
                logger.info(f"Successfully stored EODHD data for {ticker}")

            return pd.Series(values)

        except Exception as e:
            logger.error(f"Error getting financial data for {ticker}: {str(e)}")
            logger.warning(f"EODHD API failed for {ticker}: Could not get {metric_description} from EODHD, trying database")
            return None
    
    def store_historical_data(self, ticker: str, start_date: str = None, end_date: str = None) -> bool:
        """
        Fetch and store historical price data from yfinance.
        Uses custom date range if provided, otherwise defaults to 10 years of data.
        
        Parameters:
        -----------
        ticker : str
            Stock ticker symbol
        start_date : str, optional
            Start date in YYYY-MM-DD format
        end_date : str, optional
            End date in YYYY-MM-DD format
        
        Returns:
        --------
        bool
            Success status of the operation
        """
        try:
            print(f"Fetching historical data for {ticker} from yfinance")
            ticker_obj = yf.Ticker(ticker)
            
            # Get the latest trading day (last Friday if weekend)
            latest_trading_day = pd.Timestamp.now()
            while latest_trading_day.weekday() > 4:  # 5 = Saturday, 6 = Sunday
                latest_trading_day -= pd.Timedelta(days=1)
                
            # If no dates specified, use default 10 year range
            if start_date is None or end_date is None:
                end_date = latest_trading_day.strftime('%Y-%m-%d')
                start_date = (latest_trading_day - pd.DateOffset(years=20)).strftime('%Y-%m-%d')
                df = ticker_obj.history(start=start_date)
            else:
                # Use specified date range but ensure end_date isn't beyond latest trading day
                end_date = min(pd.to_datetime(end_date), latest_trading_day).strftime('%Y-%m-%d')
                df = ticker_obj.history(start=start_date, end=end_date)
            
            if df.empty:
                print(f"No historical data found for {ticker}")
                return False
            
            # Process the data
            df.index = df.index.tz_localize(None)
            cleaned_ticker = self.clean_ticker_for_table_name(ticker)
            table_name = f"his_{cleaned_ticker}"
            
            # Store in database
            return self.store_dataframe(df, table_name)
                    
        except Exception as e:
            print(f"Error storing historical data for {ticker}: {e}")
            return False
    
    
    def calculate_roic(self, income_stmt, balance_sheet, date):
        """Calculate ROIC = (Operating Income - Tax) / (Total Assets - Total Current Liabilities)"""
        try:
            operating_income = 0
            if 'Operating Income' in income_stmt.index:
                operating_income = float(income_stmt.loc['Operating Income', date] or 0)
            
            income_tax = 0
            if 'Income Tax Expense' in income_stmt.index:
                income_tax = float(income_stmt.loc['Income Tax Expense', date] or 0)
            
            total_assets = 0
            total_current_liabilities = 0
            
            if date in balance_sheet.columns:
                if 'Total Assets' in balance_sheet.index:
                    total_assets = float(balance_sheet.loc['Total Assets', date] or 0)
                if 'Total Current Liabilities' in balance_sheet.index:
                    total_current_liabilities = float(balance_sheet.loc['Total Current Liabilities', date] or 0)
            
            numerator = operating_income - income_tax
            denominator = total_assets - total_current_liabilities
            
            if denominator and denominator != 0:
                roic = (numerator / denominator) * 100
                return float(f"{roic:.15f}")
            return 0.0
            
        except Exception as e:
            logger.error(f"Error calculating ROIC: {str(e)}")
            return 0.0

    def convert_to_eodhd_ticker(self, ticker: str) -> str:
        """
        Convert Yahoo Finance ticker to EODHD format.
        
        Rules:
        - For US stocks: Remove any suffix and add .US (e.g., AAPL -> AAPL.US)
        - For non-US exchanges:
            - TSX: .TO -> .TSE (e.g., TD.TO -> TD.TSE)
            - LSE: .L -> .LSE (e.g., VOD.L -> VOD.LSE)
            - HK: .HK -> .HK (e.g., 0700.HK -> 0700.HK)
            - China SZ: .SZ -> .SZ (e.g., 000001.SZ -> 000001.SZ)
            - China SH: .SS -> .SH (e.g., 600000.SS -> 600000.SH)
            - etc.
        """
        # Exchange mapping from Yahoo to EODHD
        exchange_map = {
            'TO': 'TSE',    # Toronto
            'L': 'LSE',     # London
            'PA': 'PA',     # Paris
            'DE': 'XETRA',  # German
            'MI': 'MI',     # Milan
            'MC': 'MC',     # Madrid
            'AX': 'AU',     # Australian
            'AS': 'AS',     # Amsterdam
            'BR': 'BR',     # Brussels
            'ST': 'ST',     # Stockholm
            'HK': 'HK',     # Hong Kong
            'SZ': 'SHE',     # Shenzhen
            'SS': 'SHG',     # Shanghai (Yahoo uses SS, EODHD uses SH)
            'TW': 'TW',     # Taiwan
            'KS': 'KO',     # Korea
            'T': 'T',       # Tokyo
        }
        
        # Split ticker into base and exchange (if any)
        parts = ticker.split('.')
        base_ticker = parts[0]
        
        # Handle special cases first
        if '^' in ticker:  # Indices
            return None
        if '-' in ticker or '=' in ticker:  # Special symbols
            return None
        
        # Handle Hong Kong stocks - ensure 4 digits with leading zeros
        if len(parts) > 1 and parts[1] == 'HK':
            base_ticker = base_ticker.zfill(4)
        
        # Handle China A-shares - ensure 6 digits with leading zeros
        if len(parts) > 1 and parts[1] in ['SZ', 'SS']:
            base_ticker = base_ticker.zfill(6)
        
        if len(parts) == 1:  # No exchange suffix
            return f"{base_ticker}.US"  # Assume US stock
        
        exchange = parts[1]
        if exchange in exchange_map:
            return f"{base_ticker}.{exchange_map[exchange]}"
        
        # If exchange not found in mapping, return None
        logger.warning(f"Unknown exchange suffix in ticker: {ticker}")
        return None

    def store_financial_data(self, ticker: str, start_year: str = None, end_year: str = None) -> bool:
        """Fetch and store financial data, try ROIC API first, then EODHD, then yfinance"""
        try:
            logger.info(f"Fetching financial data for {ticker}")
            
            if not start_year or not end_year:
                current_year = datetime.now().year
                end_year = str(current_year)
                start_year = str(current_year - 10)

            # Try ROIC API first
            try:
                logger.info(f"Trying ROIC API for {ticker}")
                url = f"{self.BASE_URL}/financials/{ticker}"
                response = requests.get(url, headers={'Authorization': f'Bearer {self.API_KEY}'})
                response.raise_for_status()
                data = response.json()
                
                if data and not any('N/A' in str(v) for v in data.values()):
                    # Process ROIC API data
                    return self.process_roic_data(data, ticker, start_year, end_year)
                    
            except Exception as e:
                logger.warning(f"ROIC API failed for {ticker}: {str(e)}, trying EODHD")

            # If ROIC API fails or has N/A, try EODHD
            try:
                eodhd_ticker = self.convert_to_eodhd_ticker(ticker)
                eodhd_url = f"{self.EODHD_BASE_URL}/fundamentals/{eodhd_ticker}?api_token={self.EODHD_API_KEY}&fmt=json"
                response = requests.get(eodhd_url)
                if response.status_code == 200:
                    return self.get_financial_data(ticker, "eps", start_year, end_year) is not None
                
            except Exception as e:
                logger.warning(f"EODHD API failed for {ticker}: {str(e)}, trying yfinance")

            # If both ROIC and EODHD fail, try yfinance
            try:
                yf_ticker = yf.Ticker(ticker)
                financials = yf_ticker.financials
                if not financials.empty:
                    return self.process_yfinance_data(financials, ticker, start_year, end_year)
                
            except Exception as e:
                logger.error(f"All APIs failed for {ticker}: {str(e)}")
                return False

        except Exception as e:
            logger.error(f"Error storing financial data for {ticker}: {str(e)}")
            return False

    def get_analysis_dates(self, end_date: str, lookback_type: str, 
                            lookback_value: int) -> str:
            """
            Calculate start date based on lookback period

            Parameters:
            -----------
            end_date : str
                End date in YYYY-MM-DD format
            lookback_type : str
                Type of lookback period ('quarters' or 'days')
            lookback_value : int
                Number of quarters or days to look back

            Returns:
            --------
            str
                Start date in YYYY-MM-DD format
            """
            try:
                # Handle None or empty end_date
                if not end_date:
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    
                # Validate date format
                try:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError:
                    print(f"Invalid date format: {end_date}, using current date")
                    end_dt = datetime.now()
                    
                if lookback_type == 'quarters':
                    start_dt = end_dt - relativedelta(months=3*lookback_value)
                else:  # days
                    start_dt = end_dt - relativedelta(days=lookback_value)
                    
                return start_dt.strftime("%Y-%m-%d")
                
            except Exception as e:
                print(f"Error calculating analysis dates: {str(e)}")
                raise

    def create_metrics_table(self, ticker: str, metrics: list, 
                           start_year: str, end_year: str) -> pd.DataFrame:
        """
        Creates a combined table of all metrics with selective growth rates.
        If no data is available, returns None without showing table header.

        Parameters:
        -----------
        ticker : str
            Stock ticker symbol
        metrics : list
            List of metrics to fetch
        start_year : str
            Start year in YYYY format
        end_year : str
            End year in YYYY format

        Returns:
        --------
        pd.DataFrame or None
            DataFrame containing metrics and growth rates or None if no data available
        """
        data = {}
        growth_rates = {}

        # Check if any metrics have data before creating table
        has_data = False
        for metric in metrics:
            metric = metric.lower()
            series = self.get_financial_data(ticker.upper(), metric, start_year, end_year)
            
            if series is not None:
                has_data = True
                data[metric] = series

                # Calculate CAGR only for specified metrics
                if metric in self.CAGR_METRICS:
                    try:
                        first_value = series.iloc[0]
                        last_value = series.iloc[-1]
                        num_years = len(series) - 1
                        if num_years > 0 and first_value > 0 and last_value > 0:
                            growth_rate = ((last_value / first_value) ** (1 / num_years) - 1) * 100
                            growth_rates[metric] = growth_rate
                    except Exception as e:
                        print(f"Error calculating CAGR for {metric}: {str(e)}")
                        growth_rates[metric] = None

        # If no data was found for any metrics, return None without creating table
        if not has_data:
            return None

        try:
            # Create main DataFrame with metrics
            df = pd.DataFrame(data).T

            # Add growth rates column only for specified metrics
            df['CAGR %'] = None  # Initialize with None
            for metric in self.CAGR_METRICS:
                if metric in growth_rates and metric in df.index:
                    df.at[metric, 'CAGR %'] = growth_rates[metric]

            return df
        except Exception as e:
            print(f"Error creating metrics table: {str(e)}")
            return None

    def calculate_returns(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate daily returns for a price series

        Parameters:
        -----------
        df : pd.DataFrame
            DataFrame containing price data

        Returns:
        --------
        pd.Series
            Series containing daily returns
        """
        try:
            if 'Close' not in df.columns:
                raise ValueError("Price data must contain 'Close' column")
                
            returns = df['Close'].pct_change()
            returns.fillna(0, inplace=True)
            return returns
            
        except Exception as e:
            print(f"Error calculating returns: {str(e)}")
            raise

    @retry_with_backoff(retries=3)
    def store_historical_data_with_retry(self, ticker, start_date, end_date):
        rate_limiter = RateLimiter(calls_per_second=2)
        rate_limiter.wait()
        return self.store_historical_data(ticker, start_date, end_date)
    @retry_with_backoff(retries=3)
    def store_financial_data_with_retry(self, ticker: str, start_year: str = None, end_year: str = None) -> bool:
        """Store financial data with retry mechanism"""
        rate_limiter = RateLimiter(calls_per_second=1)  # Limit to 1 call per second
        rate_limiter.wait()
        return self.store_financial_data(ticker, start_year, end_year)

    def get_shares_from_common_stock(self, common_stock: str, ticker: str) -> float:
        """Convert commonStock value to actual shares count based on ticker"""
        try:
            if not common_stock:
                return 0
            
            # Handle string values that might contain commas or other formatting
            clean_value = str(common_stock).replace(',', '').replace('.00', '')
            shares = float(clean_value)
            
            # For Chinese stocks (SZ, SS), divide by 10000 to convert from total shares to millions
            if any(suffix in ticker for suffix in ['.SZ', '.SS']):
                shares = shares / 10000  # Convert to millions
            
            return shares
        except (ValueError, AttributeError) as e:
            logger.error(f"Error converting commonStock value '{common_stock}': {str(e)}")
            return 0