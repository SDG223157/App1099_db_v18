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
from app.utils.data.eodhd_api import Financials, StatementType

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
    
    
    
    def get_historical_data(self, ticker: str, start_date: str, end_date: str = None) -> pd.DataFrame:
        """Get historical price data for a ticker"""
        try:
            # Convert BRK.A to BRK-A for Yahoo Finance
            if ticker == 'BRK.A':
                ticker = 'BRK-A'
                
            # Get data from yfinance
            yf_ticker = yf.Ticker(ticker)
            new_data = yf_ticker.history(start=start_date, end=end_date)
            
            if new_data.empty:
                raise ValueError(f"No data found for {ticker}")
                
            # Remove timezone info
            if hasattr(new_data.index, 'tz_localize'):
                new_data.index = new_data.index.tz_localize(None)
            elif hasattr(new_data.index, 'tz'):
                new_data.index = new_data.index.tz_convert(None)

            return new_data

        except Exception as e:
            logger.error(f"Error in get_historical_data for {ticker}: {str(e)}")
            raise
        
        
    def get_financial_data(self, ticker: str, metric_description: str, 
                        start_year: str, end_year: str) -> pd.Series:
        """
        Get financial data from MySQL database or ROIC API if not exists/incomplete.
        """
        cleaned_ticker = self.clean_ticker_for_table_name(ticker)
        table_name = f"roic_{cleaned_ticker}"
        MAX_MISSING_YEARS_TOLERANCE = 2 
        # company_name = yf.Ticker(ticker).info['longName']
        
        try:
            # First try to get data from database
            # if "^" in ticker or "-" in ticker or "=" in ticker:
            #     return None
            if not is_stock(ticker):
                return None
            # if company_name:
            # # Check for excluded terms using regex (case insensitive)
            #     excluded_terms = r'shares|etf|index|trust'
            #     if re.search(excluded_terms, company_name, re.IGNORECASE):
            #         return None
                
            
            if self.table_exists(table_name):
                print(f"Getting financial data for {ticker} from database")
                df = pd.read_sql_table(table_name, self.engine)
                
                metric_field = self.METRICS.get(metric_description.lower())
                if metric_field in df.columns:
                    df['fiscal_year'] = df['fiscal_year'].astype(int)
                    
                    # Filter for requested years
                    mask = (df['fiscal_year'] >= int(start_year)) & (df['fiscal_year'] <= int(end_year))
                    filtered_df = df[mask]
                    
                    # Check if we have all the years we need
                    requested_years = set(range(int(start_year), int(end_year) + 1))
                    actual_years = set(filtered_df['fiscal_year'].values)
                    missing_years = requested_years - actual_years
                    
                    return pd.Series(
                            filtered_df[metric_field].values,
                            index=filtered_df['fiscal_year'],
                            name=metric_description
                        )
                    # if len(missing_years) == 0:
                    # if len(missing_years) <= MAX_MISSING_YEARS_TOLERANCE:
                    #     return pd.Series(
                    #         filtered_df[metric_field].values,
                    #         index=filtered_df['fiscal_year'],
                    #         name=metric_description
                    #     )
                    # else:
                    #     print(f"Incomplete data for {ticker}, fetching from API")
                    #     # If data is incomplete, fetch all data and update database
                    #     success = self.store_financial_data(ticker, start_year, end_year)
                    #     if success:
                    #         df = pd.read_sql_table(table_name, self.engine)
                    #         df['fiscal_year'] = df['fiscal_year'].astype(int)
                    #         mask = (df['fiscal_year'] >= int(start_year)) & (df['fiscal_year'] <= int(end_year))
                    #         filtered_df = df[mask]
                    #         return pd.Series(
                    #             filtered_df[metric_field].values,
                    #             index=filtered_df['fiscal_year'],
                    #             name=metric_description
                    #         )

            # If not in database, store it first
            print(f"Data not found in database for {ticker}, fetching from API")
            success = self.store_financial_data(ticker, start_year, end_year)
            if success:
                df = pd.read_sql_table(table_name, self.engine)
                metric_field = self.METRICS.get(metric_description.lower())
                df['fiscal_year'] = df['fiscal_year'].astype(int)
                mask = (df['fiscal_year'] >= int(start_year)) & (df['fiscal_year'] <= int(end_year))
                filtered_df = df[mask]
                return pd.Series(
                    filtered_df[metric_field].values,
                    index=filtered_df['fiscal_year'],
                    name=metric_description
                )
            else:
                return None
                
        except Exception as e:
            print(f"Error in get_financial_data for {ticker}: {str(e)}")
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

    
    def store_financial_data(self, ticker: str, start_year: str = None, end_year: str = None) -> bool:
        """Fetch and store financial data using EODHD API"""
        try:
            logger.info(f"Fetching financial data for {ticker}")
            
            if not start_year or not end_year:
                current_year = datetime.now().year
                end_year = str(current_year)
                start_year = str(current_year - 10)

            # Initialize EODHD API and fetch data
            financials = Financials(ticker, self.API_KEY)
            financials._fetch_data()

            # Process each year's data
            financial_data = []
            for year in range(int(start_year), int(end_year) + 1):
                try:
                    year_str = str(year)
                    year_data = {
                        'fiscal_year': year,
                        'period_label': 'FY',
                        'period_end_date': f"{year}-12-31"
                    }

                    # Get annual metrics
                    revenue = financials.get_metric('Income_Statement', 'totalRevenue', year_str, freq='annual')
                    net_income = financials.get_metric('Income_Statement', 'netIncome', year_str, freq='annual')
                    operating_income = financials.get_metric('Income_Statement', 'operatingIncome', year_str, freq='annual')
                    shares = financials.get_metric('Balance_Sheet', 'commonStockSharesOutstanding', year_str, freq='annual')

                    if revenue and net_income:
                        year_data[METRICS_MAP['total revenues']] = float(revenue)
                        year_data[METRICS_MAP['net income']] = float(net_income)
                        
                        if operating_income and revenue:
                            year_data[METRICS_MAP['operating margin']] = (float(operating_income) / float(revenue)) * 100

                        if shares:
                            year_data[METRICS_MAP['diluted shares']] = float(shares)
                            year_data[METRICS_MAP['earnings per share']] = float(net_income) / float(shares)

                        financial_data.append(year_data)

                except Exception as e:
                    logger.error(f"Error processing data for {year}: {str(e)}")
                    continue

            # Store data in database
            if financial_data:
                cleaned_ticker = self.clean_ticker_for_table_name(ticker)
                table_name = f"roic_{cleaned_ticker}"
                df = pd.DataFrame(financial_data)
                return self.store_dataframe(df, table_name)

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
        """Convert commonStock value to actual shares count"""
        try:
            if not common_stock:
                return 0
            
            # Handle string values that might contain commas or other formatting
            clean_value = str(common_stock).replace(',', '').replace('.00', '')
            shares = float(clean_value)
            
            return shares
        except (ValueError, AttributeError) as e:
            logger.error(f"Error converting commonStock value '{common_stock}': {str(e)}")
            return 0