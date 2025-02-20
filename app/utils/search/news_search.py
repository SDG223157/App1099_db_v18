# app/utils/search/news_search.py

from typing import List, Dict, Tuple
from sqlalchemy import or_, and_, func, desc, distinct
from sqlalchemy.orm import Session
from ...models import NewsArticle, ArticleSymbol, ArticleMetric
import re
from datetime import datetime, timedelta
from textblob import TextBlob

class NewsSearch:
    def __init__(self, session: Session):
        self.session = session

    def advanced_search(
        self,
        keywords: List[str] = None,
        symbols: List[str] = None,
        sentiment: str = None,
        min_sentiment_score: float = None,
        start_date: str = None,
        end_date: str = None,
        sources: List[str] = None,
        metric_type: str = None,
        metric_min_value: float = None,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[List[Dict], int]:
        """Advanced search with multiple filters"""
        query = self.session.query(NewsArticle)

        # Keyword search (with phrase support)
        if keywords:
            keyword_filters = []
            for keyword in keywords:
                if '"' in keyword:  # Exact phrase match
                    phrase = keyword.replace('"', '')
                    keyword_filters.append(
                        NewsArticle.content.like(f"%{phrase}%")
                    )
                else:  # Individual word match
                    keyword_filters.append(or_(
                        NewsArticle.content.like(f"%{keyword}%"),
                        NewsArticle.title.like(f"%{keyword}%")
                    ))
            query = query.filter(and_(*keyword_filters))

        # Symbol filter
        if symbols:
            query = query.join(ArticleSymbol).filter(
                ArticleSymbol.symbol.in_(symbols)
            )

        # Sentiment filter
        if sentiment:
            query = query.filter(NewsArticle.sentiment_label == sentiment)
        if min_sentiment_score is not None:
            query = query.filter(NewsArticle.sentiment_score >= min_sentiment_score)

        # Date range filter
        if start_date:
            query = query.filter(NewsArticle.published_at >= start_date)
        if end_date:
            query = query.filter(NewsArticle.published_at <= end_date)

        # Source filter
        if sources:
            query = query.filter(NewsArticle.source.in_(sources))

        # Metric filter
        if metric_type and metric_min_value is not None:
            query = query.join(ArticleMetric).filter(and_(
                ArticleMetric.metric_type == metric_type,
                ArticleMetric.value >= metric_min_value
            ))

        # Get total count
        total_count = query.count()

        # Add pagination
        query = query.order_by(desc(NewsArticle.published_at))
        query = query.offset((page - 1) * per_page).limit(per_page)

        # Execute query and convert to dict
        articles = [article.to_dict() for article in query.all()]
        
        return articles, total_count

    def find_similar_articles(
        self,
        article_id: int,
        max_results: int = 5
    ) -> List[Dict]:
        """Find articles similar to the given article"""
        # Get the original article
        original = self.session.query(NewsArticle).get(article_id)
        if not original:
            return []

        # Create TextBlob for original article
        original_blob = TextBlob(original.content)

        # Get articles from the same time period
        time_window = timedelta(days=7)
        candidates = (self.session.query(NewsArticle)
                    .filter(
                        NewsArticle.id != article_id,
                        NewsArticle.published_at.between(
                            original.published_at - time_window,
                            original.published_at + time_window
                        )
                    )
                    .all())

        # Calculate similarity scores
        similarities = []
        for candidate in candidates:
            candidate_blob = TextBlob(candidate.content)
            
            # Calculate similarity score based on multiple factors
            content_similarity = original_blob.similarity(candidate_blob)
            sentiment_similarity = 1 - abs(
                original.sentiment_score - candidate.sentiment_score
            )
            
            # Combine scores (you can adjust weights)
            total_score = (content_similarity * 0.7 + sentiment_similarity * 0.3)
            
            similarities.append((candidate, total_score))

        # Sort by similarity score and get top results
        similar_articles = sorted(
            similarities,
            key=lambda x: x[1],
            reverse=True
        )[:max_results]

        return [article[0].to_dict() for article in similar_articles]

    def get_trending_entities(
        self,
        days: int = 7,
        min_occurrences: int = 3
    ) -> Dict[str, List[Dict]]:
        """Get trending entities (companies, people, topics)"""
        # Get recent articles
        start_date = datetime.now() - timedelta(days=days)
        articles = (self.session.query(NewsArticle)
                   .filter(NewsArticle.published_at >= start_date)
                   .all())

        entities = {
            'companies': {},
            'people': {},
            'topics': {}
        }

        for article in articles:
            blob = TextBlob(article.content)
            
            # Extract noun phrases and classify them
            for phrase in blob.noun_phrases:
                if self._is_company(phrase):
                    entities['companies'][phrase] = entities['companies'].get(phrase, 0) + 1
                elif self._is_person(phrase):
                    entities['people'][phrase] = entities['people'].get(phrase, 0) + 1
                else:
                    entities['topics'][phrase] = entities['topics'].get(phrase, 0) + 1

        # Format results
        result = {}
        for category, items in entities.items():
            # Filter by minimum occurrences and sort by count
            trending = [
                {'entity': entity, 'occurrences': count}
                for entity, count in items.items()
                if count >= min_occurrences
            ]
            result[category] = sorted(
                trending,
                key=lambda x: x['occurrences'],
                reverse=True
            )[:10]  # Top 10 for each category

        return result

    # app/utils/search/news_search.py (continued)

    def _is_company(self, phrase: str) -> bool:
        """Simple heuristic to identify company names"""
        company_indicators = [
            'Inc', 'Corp', 'Ltd', 'LLC', 'Company', 'Technologies',
            'Holdings', 'Group', 'International', 'Incorporated',
            'Corporation', 'Limited', 'Bank', 'Partners'
        ]
        return any(indicator in phrase for indicator in company_indicators)

    def _is_person(self, phrase: str) -> bool:
        """Simple heuristic to identify person names"""
        # Check for common titles
        titles = ['Mr', 'Mrs', 'Ms', 'Dr', 'CEO', 'President', 'Director']
        if any(title in phrase for title in titles):
            return True
        
        # Check for name-like patterns (two or more capitalized words)
        words = phrase.split()
        if len(words) >= 2 and all(word[0].isupper() for word in words if word):
            return True
            
        return False

    def search_by_topic(self, topic: str, days: int = 30) -> List[Dict]:
        """Search articles by topic with relevant context"""
        start_date = datetime.now() - timedelta(days=days)
        
        # Search for articles containing the topic
        query = self.session.query(
            NewsArticle,
            func.ts_rank(
                func.to_tsvector('english', NewsArticle.content),
                func.plainto_tsquery('english', topic)
            ).label('relevance')
        ).filter(
            NewsArticle.published_at >= start_date,
            or_(
                NewsArticle.content.ilike(f'%{topic}%'),
                NewsArticle.title.ilike(f'%{topic}%')
            )
        ).order_by(desc('relevance'))

        articles = query.all()
        results = []

        for article, relevance in articles:
            # Extract relevant context around the topic
            context = self._extract_context(article.content, topic)
            
            article_dict = article.to_dict()
            article_dict['relevance'] = float(relevance)
            article_dict['topic_context'] = context
            results.append(article_dict)

        return results

    def _extract_context(self, text: str, topic: str, window: int = 100) -> str:
        """Extract context around a topic mention"""
        # Find all occurrences of the topic
        pattern = re.compile(topic, re.IGNORECASE)
        matches = list(pattern.finditer(text))
        
        contexts = []
        for match in matches:
            start = max(0, match.start() - window)
            end = min(len(text), match.end() + window)
            
            # Get the context and highlight the topic
            context = text[start:end]
            if start > 0:
                context = f"...{context}"
            if end < len(text):
                context = f"{context}..."
                
            contexts.append(context)
            
        return contexts

    def get_topic_trends(self, topics: List[str], days: int = 30) -> Dict[str, List[Dict]]:
        """Analyze trends for specific topics over time"""
        start_date = datetime.now() - timedelta(days=days)
        results = {}
        
        for topic in topics:
            # Get daily mentions and sentiment
            daily_stats = (
                self.session.query(
                    func.date(NewsArticle.published_at).label('date'),
                    func.count().label('mentions'),
                    func.avg(NewsArticle.sentiment_score).label('avg_sentiment')
                )
                .filter(
                    NewsArticle.published_at >= start_date,
                    or_(
                        NewsArticle.content.ilike(f'%{topic}%'),
                        NewsArticle.title.ilike(f'%{topic}%')
                    )
                )
                .group_by(func.date(NewsArticle.published_at))
                .order_by(func.date(NewsArticle.published_at))
                .all()
            )
            
            results[topic] = [{
                'date': stats.date.strftime('%Y-%m-%d'),
                'mentions': stats.mentions,
                'sentiment': float(stats.avg_sentiment) if stats.avg_sentiment else 0
            } for stats in daily_stats]
            
        return results

    def get_related_topics(self, topic: str, min_correlation: float = 0.3) -> List[Dict]:
        """Find topics that frequently appear together"""
        # Get articles containing the main topic
        base_articles = set(
            article.id for article in
            self.session.query(NewsArticle.id)
            .filter(or_(
                NewsArticle.content.ilike(f'%{topic}%'),
                NewsArticle.title.ilike(f'%{topic}%')
            ))
        )
        
        if not base_articles:
            return []

        # Extract and count all noun phrases from these articles
        related = {}
        total_articles = len(base_articles)
        
        articles = (
            self.session.query(NewsArticle)
            .filter(NewsArticle.id.in_(base_articles))
        )
        
        for article in articles:
            blob = TextBlob(article.content)
            for phrase in blob.noun_phrases:
                if phrase.lower() != topic.lower():
                    related[phrase] = related.get(phrase, 0) + 1
        
        # Calculate correlation scores
        correlations = []
        for phrase, count in related.items():
            correlation = count / total_articles
            if correlation >= min_correlation:
                correlations.append({
                    'topic': phrase,
                    'correlation': correlation,
                    'occurrences': count
                })
        
        return sorted(correlations, key=lambda x: x['correlation'], reverse=True)

    def get_source_stats(self, start_date: str, end_date: str) -> List[Dict]:
        """Get statistics by news source"""
        stats = (
            self.session.query(
                NewsArticle.source,
                func.count().label('article_count'),
                func.avg(NewsArticle.sentiment_score).label('avg_sentiment'),
                func.count(distinct(ArticleSymbol.symbol)).label('unique_symbols')
            )
            .outerjoin(ArticleSymbol)
            .filter(NewsArticle.published_at.between(start_date, end_date))
            .group_by(NewsArticle.source)
            .order_by(desc('article_count'))
        )
        
        return [{
            'source': stat.source,
            'article_count': stat.article_count,
            'avg_sentiment': float(stat.avg_sentiment) if stat.avg_sentiment else 0,
            'unique_symbols': stat.unique_symbols
        } for stat in stats]