# app/utils/analysis/news_analyzer.py

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

class NewsAnalyzer:
    def __init__(self, api_token: str):
        """Initialize NewsAnalyzer with required resources"""
        self.client = ApifyClient(api_token)
        self.logger = logging.getLogger(__name__)
        
        try:
            # Download required NLTK packages
            nltk_packages = ['punkt', 'averaged_perceptron_tagger', 'vader_lexicon']
            for package in nltk_packages:
                try:
                    nltk.data.find(f'tokenizers/{package}')
                except LookupError:
                    nltk.download(package, quiet=True)
            
            self.vader = SentimentIntensityAnalyzer()
            self.logger.info("Successfully initialized NLTK resources")
            
        except Exception as e:
            self.logger.error(f"Error initializing NLTK resources: {str(e)}")
            raise

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

    def analyze_article(self, article: Dict) -> Optional[Dict]:
        """Analyze a single article"""
        try:
            # Extract content
            content = article.get("descriptionText", "")
            title = article.get("title", "")
            
            # Create base article structure
            analyzed = {
                "external_id": article.get("id", str(hash(title + content))),
                "title": title,
                "content": content,
                "url": article.get("storyPath", ""),
                "published_at": datetime.fromtimestamp(
                    article.get("published", 0) / 1000
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "source": article.get("source", "Unknown"),
                "symbols": [{"symbol": s["symbol"]} for s in article.get("relatedSymbols", [])],
            }
            
            # Add analysis
            analyzed.update({
                "sentiment": self.analyze_sentiment(content),
                "summary": self.generate_summary(content),
                "metrics": self.extract_metrics(content)
            })
            
            return analyzed
            
        except Exception as e:
            self.logger.error(f"Error analyzing article: {str(e)}")
            return None

    def analyze_sentiment(self, text: str) -> Dict:
        """Analyze sentiment using VADER and TextBlob"""
        try:
            # TextBlob analysis
            blob = TextBlob(text)
            textblob_polarity = blob.sentiment.polarity
            
            # VADER analysis
            vader_scores = self.vader.polarity_scores(text)
            compound_score = vader_scores['compound']
            
            # Determine sentiment
            if compound_score >= 0.05:
                sentiment = "POSITIVE"
                explanation = "Strong positive" if compound_score > 0.5 else "Moderately positive"
            elif compound_score <= -0.05:
                sentiment = "NEGATIVE"
                explanation = "Strong negative" if compound_score < -0.5 else "Moderately negative"
            else:
                sentiment = "NEUTRAL"
                explanation = "Neutral or mixed sentiment"
            
            return {
                "overall_sentiment": sentiment,
                "explanation": explanation,
                "confidence": abs(compound_score),
                "scores": vader_scores
            }
            
        except Exception as e:
            self.logger.error(f"Error in sentiment analysis: {str(e)}")
            return {"overall_sentiment": "NEUTRAL", "confidence": 0}

    def generate_summary(self, text: str) -> Dict:
        """Generate article summaries"""
        try:
            blob = TextBlob(text)
            sentences = blob.sentences
            
            if not sentences:
                return {"brief": text, "key_points": text}
            
            # Brief summary (first sentence)
            brief = str(sentences[0])
            if len(sentences) > 1:
                brief += " " + str(sentences[-1])
                
            # Key points (up to 3 most relevant sentences)
            key_points = [str(s) for s in sentences[:3]]
            
            return {
                "brief": brief,
                "key_points": " ".join(key_points),
                "market_impact": brief  # Simplified market impact
            }
            
        except Exception as e:
            self.logger.error(f"Error generating summary: {str(e)}")
            return {"brief": "Summary unavailable", "key_points": ""}

    def extract_metrics(self, text: str) -> Dict:
        """Extract financial metrics with context"""
        try:
            return {
                "percentage": {
                    "values": self._extract_percentages(text),
                    "contexts": self._extract_contexts(text, r'\d+%')
                }
            }
        except Exception as e:
            self.logger.error(f"Error extracting metrics: {str(e)}")
            return {}

    def _extract_percentages(self, text: str) -> List[float]:
        """Extract percentage values from text"""
        matches = re.findall(r'(\d+(?:\.\d+)?)%', text)
        return [float(match) for match in matches]

    def _extract_contexts(self, text: str, pattern: str) -> List[str]:
        """Extract context around matches"""
        contexts = []
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            contexts.append(text[start:end].strip())
        return contexts