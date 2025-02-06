# app/data/news_service.py

from typing import Dict, List, Tuple, Optional
import logging
from datetime import datetime, timedelta, date, timezone
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import NewsArticle, ArticleSymbol, ArticleMetric

class NewsService:
    """Service class for handling news article operations"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def close(self):
        """Clean up resources"""
        try:
            if hasattr(self, 'engine'):
                self.engine.dispose()
        except Exception as e:
            self.logger.error(f"Error disposing engine: {str(e)}")


    def save_article(self, article: Dict) -> int:
        """Save article and related data to database"""
        try:
            external_id = article.get('external_id')
            if not external_id:
                self.logger.error("Article missing external ID")
                return None

            # Check for existing article
            existing_article = NewsArticle.query.filter_by(external_id=external_id).first()
            if existing_article:
                return existing_article.id

            # Create new article
            new_article = NewsArticle(
                external_id=external_id,
                title=article.get('title'),
                content=article.get('content'),
                url=article.get('url'),
                published_at=article.get('published_at'),
                source=article.get('source'),
                sentiment_label=article.get('sentiment', {}).get('overall_sentiment'),
                sentiment_score=article.get('sentiment', {}).get('confidence'),
                sentiment_explanation=article.get('sentiment', {}).get('explanation'),
                brief_summary=article.get('summary', {}).get('brief'),
                key_points=article.get('summary', {}).get('key_points'),
                market_impact_summary=article.get('summary', {}).get('market_impact'),
                ai_summary=None,
                ai_insights=None,
                ai_sentiment_rating=None
            )

            # Add symbols
            if article.get('symbols'):
                seen_symbols = set()  # Track unique symbols
                for symbol_data in article['symbols']:
                    symbol = symbol_data.get('symbol') if isinstance(symbol_data, dict) else symbol_data
                    if symbol and symbol not in seen_symbols:
                        seen_symbols.add(symbol)
                        new_article.symbols.append(ArticleSymbol(symbol=symbol))

            # Add metrics with deduplication
            if article.get('metrics'):
                metrics_by_type = {}  # Track unique metric types
                for metric_type, metric_data in article['metrics'].items():
                    if isinstance(metric_data, dict):
                        values = metric_data.get('values', [])
                        contexts = metric_data.get('contexts', [])
                        # Only take the first occurrence of each metric type
                        if metric_type not in metrics_by_type and values and contexts:
                            new_article.metrics.append(
                                ArticleMetric(
                                    metric_type=metric_type,
                                    metric_value=values[0],
                                    metric_context=contexts[0]
                                )
                            )
                            metrics_by_type[metric_type] = True

            # Save to database
            db.session.add(new_article)
            db.session.commit()
            self.logger.info(f"Successfully saved article with external_id: {external_id}")
            return new_article.id

        except Exception as e:
            self.logger.error(f"Database error while saving article: {str(e)}")
            db.session.rollback()
            return None
        
     
    def get_daily_sentiment_summary(self, date: str, symbol: str = None) -> Dict:
        """Get sentiment summary for a specific date"""
        # Implement sentiment summary logic
        return {
            "total_articles": 0,
            "sentiment_distribution": {
                "positive": 0,
                "negative": 0,
                "neutral": 0
            },
            "average_sentiment": 0
        }

    def get_trending_topics(self, days: int = 7) -> List[Dict]:
        """Get trending topics from recent articles"""
        # Implement trending topics logic
        return []
   
    def _add_symbols(self, article: NewsArticle, symbols_data: List) -> None:
        """
        Add symbols to article
        
        Args:
            article (NewsArticle): Article object to add symbols to
            symbols_data (List): List of symbols or symbol dictionaries
        """
        for symbol_data in symbols_data:
            symbol = symbol_data.get('symbol') if isinstance(symbol_data, dict) else symbol_data
            if symbol:
                article.symbols.append(ArticleSymbol(symbol=symbol))

    def _add_metrics(self, article: NewsArticle, metrics_data: Dict) -> None:
        """
        Add metrics to article
        
        Args:
            article (NewsArticle): Article object to add metrics to
            metrics_data (Dict): Dictionary of metric data
        """
        for metric_type, metric_data in metrics_data.items():
            if isinstance(metric_data, dict):
                values = metric_data.get('values', [])
                contexts = metric_data.get('contexts', [])
                for value, context in zip(values, contexts):
                    article.metrics.append(
                        ArticleMetric(
                            metric_type=metric_type,
                            metric_value=value,
                            metric_context=context
                        )
                    )

    def get_articles_by_date_range(self, start_date, end_date, symbol=None, page=1, per_page=20):
        try:
            query = NewsArticle.query

            # Ensure UTC datetime objects
            if isinstance(start_date, (date, datetime)):
                start_date = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            if isinstance(end_date, (date, datetime)):
                end_date = datetime.combine(end_date, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(days=1)

            # Convert string dates to UTC
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date).astimezone(timezone.utc)
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date).astimezone(timezone.utc)

            # Apply inclusive UTC date range
            query = query.filter(NewsArticle.published_at >= start_date)
            query = query.filter(NewsArticle.published_at <= end_date)

            # Match exact symbol with exchange prefix
            if symbol:
                # Use symbol exactly as stored in database
                exact_symbol = symbol.strip().upper()  # Normalize to uppercase
                query = query.join(NewsArticle.symbols)
                query = query.filter(ArticleSymbol.symbol == exact_symbol)
                query = query.distinct(NewsArticle.id)

            # Execute query with pagination
            query = query.order_by(NewsArticle.published_at.desc())
            paginated_articles = query.paginate(page=page, per_page=per_page, error_out=False)
            
            return [article.to_dict() for article in paginated_articles.items], paginated_articles.total

        except ValueError as e:
            self.logger.error(f"Invalid date format: {str(e)}")
            return [], 0
        except Exception as e:
            self.logger.error(f"Error getting articles by date range: {str(e)}")
            return [], 0

    def search_articles(
        self,
        keyword: str = None,
        symbol: str = None,
        start_date: str = None,
        end_date: str = None,
        sentiment: str = None,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[List[Dict], int]:
        """
        Search articles with various filters
        
        Args:
            keyword (str, optional): Search keyword for title and content
            symbol (str, optional): Filter by stock symbol
            start_date (str, optional): Start date in ISO format
            end_date (str, optional): End date in ISO format
            sentiment (str, optional): Filter by sentiment label
            page (int): Page number for pagination
            per_page (int): Number of items per page
            
        Returns:
            Tuple[List[Dict], int]: List of articles and total count
        """
        try:
            query = NewsArticle.query

            # Apply filters
            if keyword:
                query = query.filter(
                    db.or_(
                        NewsArticle.title.ilike(f'%{keyword}%'),
                        NewsArticle.brief_summary.ilike(f'%{keyword}%')
                    )
                )

            if symbol:
                query = query.join(NewsArticle.symbols).filter(
                    ArticleSymbol.symbol == symbol
                )

            if start_date:
                query = query.filter(NewsArticle.published_at >= start_date)

            if end_date:
                query = query.filter(NewsArticle.published_at <= end_date)

            if sentiment:
                query = query.filter(NewsArticle.sentiment_label == sentiment)

            # Get total count
            total = query.count()

            # Apply pagination and ordering
            paginated_articles = query.order_by(NewsArticle.published_at.desc())\
                                    .paginate(page=page, per_page=per_page, error_out=False)

            return [article.to_dict() for article in paginated_articles.items], total

        except Exception as e:
            self.logger.error(f"Error searching articles: {str(e)}")
            return [], 0

    def get_article_by_id(self, article_id: int) -> Optional[Dict]:
        """
        Get article by ID
        
        Args:
            article_id (int): Article ID
            
        Returns:
            Optional[Dict]: Article data if found, None if not found
        """
        try:
            article = NewsArticle.query.get(article_id)
            return article.to_dict() if article else None
        except Exception as e:
            self.logger.error(f"Error getting article by ID: {str(e)}")
            return None

    def get_article_by_external_id(self, external_id: str) -> Optional[Dict]:
        """
        Get article by external ID
        
        Args:
            external_id (str): External article ID
            
        Returns:
            Optional[Dict]: Article data if found, None if not found
        """
        try:
            article = NewsArticle.query.filter_by(external_id=external_id).first()
            return article.to_dict() if article else None
        except Exception as e:
            self.logger.error(f"Error getting article by external ID: {str(e)}")
            return None

    def delete_article(self, article_id: int) -> bool:
        """
        Delete article by ID
        
        Args:
            article_id (int): Article ID
            
        Returns:
            bool: True if successful, False if failed
        """
        try:
            article = NewsArticle.query.get(article_id)
            if article:
                db.session.delete(article)
                db.session.commit()
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error deleting article: {str(e)}")
            db.session.rollback()
            return False

    def get_sentiment_summary(self, days=7, symbol=None):
        """Get sentiment analysis with precise UTC date handling"""
        try:
            # 1. Get UTC date range
            utc_now = datetime.now(timezone.utc)
            end_date = utc_now.replace(hour=23, minute=59, second=59)
            start_date = (end_date - timedelta(days=days-1)).replace(hour=0, minute=0, second=0)
            
            # 2. Generate complete date range in UTC
            date_range = [
                (start_date + timedelta(days=i)).date()
                for i in range(days)
            ]
            
            # 3. Get articles with UTC date filtering
            articles, _ = self.get_articles_by_date_range(
                start_date=start_date,
                end_date=end_date,
                symbol=symbol,
                per_page=0
            )

            # 4. Initialize daily data with UTC dates
            daily_data = {
                d.strftime("%Y-%m-%d"): {
                    'total_sentiment': 0,
                    'article_count': 0
                } for d in date_range
            }

            # 5. Process articles with strict UTC dates
            for article in articles:
                # Parse as UTC datetime
                pub_dt = datetime.fromisoformat(
                    article['published_at'].replace('Z', '+00:00')
                ).astimezone(timezone.utc)
                
                date_str = pub_dt.date().strftime("%Y-%m-%d")
                
                if date_str in daily_data:
                    sentiment = article.get('ai_sentiment_rating') or 0
                    daily_data[date_str]['total_sentiment'] += sentiment
                    daily_data[date_str]['article_count'] += 1

            # 6. Generate ordered response
            sorted_dates = [d.strftime("%Y-%m-%d") for d in date_range]
            daily_sentiment = {date: daily_data[date] for date in sorted_dates}

            # 7. Calculate average sentiment
            total_sentiment = 0
            total_articles = 0
            for date_str in sorted_dates:
                data = daily_data[date_str]
                avg = data['total_sentiment'] / data['article_count'] if data['article_count'] > 0 else 0
                daily_sentiment[date_str] = {
                    'average_sentiment': round(avg, 2),
                    'article_count': data['article_count']
                }

                if data['article_count'] > 0:
                    total_sentiment += avg
                    total_articles += data['article_count']

            # 8. Generate complete response
            result = {
                "average_sentiment": round(total_sentiment / total_articles, 2) if total_articles > 0 else 0,
                "daily_sentiment": daily_sentiment,
                "highest_day": {"date": None, "value": -1},
                "lowest_day": {"date": None, "value": 1},
                "total_articles": total_articles
            }

            # Update highest and lowest day
            for date_str in sorted_dates:
                data = daily_data[date_str]
                if data['article_count'] > 0:
                    if data['total_sentiment'] > result['highest_day']['value']:
                        result['highest_day'] = {'date': date_str, 'value': data['total_sentiment'] / data['article_count']}
                    if data['total_sentiment'] < result['lowest_day']['value']:
                        result['lowest_day'] = {'date': date_str, 'value': data['total_sentiment'] / data['article_count']}

            return result

        except Exception as e:
            self.logger.error(f"Sentiment error: {str(e)}")
            return self._empty_sentiment_response(days)

    def _empty_sentiment_response(self, days):
        """Generate empty response structure with all dates"""
        end_date = datetime.now()
        return {
            "average_sentiment": 0,
            "daily_sentiment": {
                (end_date - timedelta(days=i)).strftime("%Y-%m-%d"): {
                    "average_sentiment": 0,
                    "article_count": 0
                } for i in range(days)
            },
            "highest_day": {"date": None, "value": 0},
            "lowest_day": {"date": None, "value": 0},
            "total_articles": 0
        }