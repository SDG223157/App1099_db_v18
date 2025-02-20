
from datetime import datetime
from textblob import TextBlob
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
import re
from typing import Dict, List, Optional
import logging
from apify_client import ApifyClient
import time
import random

class NewsFetcher:
    def __init__(self, api_token: str):
        """Initialize NewsFetcher with required resources"""
        self.client = ApifyClient(api_token)
        self.logger = logging.getLogger(__name__)
        
        

    def get_news(self, symbols: List[str], limit: int = 10, retries: int = 3) -> List[Dict]:
        """Fetch news from TradingView via Apify"""
        self.logger.debug(f"Fetching news for symbols: {symbols}")

        run_input = {
            "symbols": symbols,
            "proxy": {"useApifyProxy": True},
            "resultsLimit": limit
        }

        for attempt in range(retries):
            try:
                run = self.client.actor("mscraper/tradingview-news-scraper").call(run_input=run_input)
                
                if not run or not run.get("defaultDatasetId"):
                    continue

                items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
                return items

            except Exception as e:
                self.logger.error(f"Error fetching news (attempt {attempt + 1}): {str(e)}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)

        return []
