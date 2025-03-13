# app/news/routes.py

import os
import re
from flask import Blueprint, render_template, request, jsonify, current_app, redirect, url_for
from flask_login import login_required
from app.utils.analysis.news_service import NewsAnalysisService
from app.utils.analytics.news_analytics import NewsAnalytics
from datetime import datetime, timedelta
import logging
from http import HTTPStatus
# from app import admin_required
from functools import wraps
from flask import abort
from flask_login import current_user
from app.models import NewsArticle, ArticleSymbol
from openai import OpenAI
from app import db
# import httpx
# from app.utils.config.news_config import DEFAULT_SYMBOLS
import time
from sqlalchemy import or_, and_
import markdown  # Add at top
from app.utils.symbol_utils import normalize_ticker
logger = logging.getLogger(__name__)
bp = Blueprint('news', __name__)


# Initialize services
news_service = NewsAnalysisService()

DEFAULT_SYMBOLS = [
    "NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:AMZN", "NASDAQ:GOOGL", "NASDAQ:META",
    "NASDAQ:NVDA", "NASDAQ:TSLA", "NYSE:BRK.A", "NYSE:V", "NYSE:JPM",
    "NYSE:JNJ", "NYSE:WMT", "NYSE:MA", "NYSE:PG", "NASDAQ:AVGO",
    "NYSE:CVX", "NYSE:HD", "NYSE:MRK", "NYSE:KO", "NASDAQ:PEP", 
    "NYSE:BAC", "NYSE:DIS", "NASDAQ:COST", "NASDAQ:CSCO", "NYSE:VZ",
    "NYSE:ABT", "NASDAQ:ADBE", "NASDAQ:CMCSA", "NYSE:NKE", "NYSE:TMO"
    ]
# DEFAULT_SYMBOLS = [
#     "HKEX:0700", "HKEX:9988", "HKEX:1299", "HKEX:0941", "HKEX:0388",
#     "HKEX:0005", "HKEX:3690", "HKEX:2318", "HKEX:2628", "HKEX:1211",
#     "HKEX:1810", "HKEX:2382", "HKEX:1024", "HKEX:9618", "HKEX:2269",
#     "HKEX:2018", "HKEX:2020", "HKEX:1177", "HKEX:1928", "HKEX:0883",
#     "HKEX:1088", "HKEX:0857", "HKEX:0386", "HKEX:0001", "HKEX:0016",
#     "HKEX:0011", "HKEX:0002", "HKEX:0003", "HKEX:0006", "HKEX:0012",
#     "HKEX:0017", "HKEX:0019", "HKEX:0066", "HKEX:0083", "HKEX:0101",
#     "HKEX:0135", "HKEX:0151", "HKEX:0175", "HKEX:0267", "HKEX:0288",
#     "HKEX:0291", "HKEX:0293", "HKEX:0330", "HKEX:0392", "HKEX:0688",
#     "HKEX:0762", "HKEX:0823", "HKEX:0960", "HKEX:1038", "HKEX:1109"
# ]

# Add at the top with other constants
FUTURES_MAPPING = {
    # Metals
    'GOLD': ['COMEX:GC1!', 'COMEX:GC', 'TVC:GOLD', 'FXCM:GOLD'],
    'SILVER': ['COMEX:SI1!', 'COMEX:SI', 'TVC:SILVER', 'FXCM:SILVER'],
    'COPPER': ['COMEX:HG1!', 'COMEX:HG', 'TVC:COPPER', 'FXCM:COPPER'],
    'PLATINUM': ['NYMEX:PL1!', 'NYMEX:PL', 'TVC:PLATINUM', 'FXCM:PLATINUM'],
    
    # Energy
    'OIL': ['NYMEX:CL1!', 'NYMEX:CL', 'NYMEX:WTI', 'TVC:USOIL', 'FXCM:OIL'],
    'BRENT': ['NYMEX:BZ1!', 'NYMEX:BZ'],
    'GAS': ['NYMEX:NG1!', 'NYMEX:NG'],
    
    # Agriculture
    'CORN': ['CBOT:ZC1!', 'CBOT:ZC'],
    'WHEAT': ['CBOT:ZW1!', 'CBOT:ZW'],
    'SOYBEANS': ['CBOT:ZS1!', 'CBOT:ZS'],
    'COFFEE': ['NYMEX:KC1!', 'NYMEX:KC'],
    
    # Indices Futures
    'SP500': ['CME:ES1!', 'SP:SPX'],
    'NASDAQ': ['CME:NQ1!', 'NASDAQ:IXIC'],
    'DOW': ['CBOT:YM1!', 'DJ:DJI']
}

def init_analytics():
    """Initialize analytics with database session"""
    return NewsAnalytics(current_app.db.session)

@bp.route('/')
@login_required
def index():
    """News dashboard homepage."""
    try:
        period = request.args.get('period', 'day')
        symbol = request.args.get('symbol', 'all')
        days = 7 if period == 'week' else (30 if period == 'month' else 1)

        # Get latest articles
        latest_articles = NewsArticle.query.order_by(
            NewsArticle.published_at.desc()
        ).limit(10).all()

        # Get most mentioned symbols
        trending_symbols = news_service.get_trending_symbols(days=days)

        # Get sentiment distribution
        sentiment_data = news_service.get_overall_sentiment(days=days)
        
        # Fix the sentiment_summary structure to match what the template expects
        sentiment_summary = {
            'sentiment_distribution': {
                'positive': sentiment_data.get('positive', 0),
                'neutral': sentiment_data.get('neutral', 0),
                'negative': sentiment_data.get('negative', 0)
            },
            'overall_score': sentiment_data.get('overall_score', 0),
            'total_articles': sentiment_data.get('total_articles', 0)
        }

        return render_template(
            'news/analysis.html',
            latest_articles=latest_articles,
            trending_symbols=trending_symbols,
            sentiment_summary=sentiment_summary,
            period=period,
            symbol=symbol
        )
    except Exception as e:
        logger.error(f"Error in news index: {str(e)}")
        db.session.rollback()  # Rollback in case of error
        return render_template(
            'news/analysis.html',
            error=str(e),
            latest_articles=[],
            trending_symbols=[],
            sentiment_summary={
                'sentiment_distribution': {'positive': 0, 'neutral': 0, 'negative': 0},
                'overall_score': 0,
                'total_articles': 0
            },
            period=request.args.get('period', 'day'),
            symbol=request.args.get('symbol', 'all')
        )

@bp.route('/fetch')
@login_required
def fetch():
    """Render the Fetch News page"""
    return render_template('news/fetch.html')
@bp.route('/sentiment')
def analysis():
    return render_template('news/sentiment.html')
@bp.route('/search', methods=['GET', 'POST'])
@login_required
def search():
    """Search news articles by symbol"""
    symbol = request.args.get('symbol', '').strip().upper()
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').strip().upper()
        
    # Convert hyphen to dot in stock symbols (e.g., BRK-A to BRK.A)
    symbol = symbol.replace('-', '.')
    symbol = normalize_ticker(symbol, purpose='search')

    # Redirect if empty symbol parameter exists
    if 'symbol' in request.args and not symbol:
        return redirect(url_for('news.search'))

    # Convert Yahoo Finance symbols to TradingView format for news search
    if symbol.endswith('.L'):
        # Convert RIO.L to LSE:RIO
        search_symbol = f"LSE:{symbol[:-2]}"
    else:
        search_symbol = symbol

    try:
        page = request.args.get('page', 1, type=int)
        
        # Always initialize search_params
        search_params = {'symbol': search_symbol}
        
        if not search_symbol:
            return render_template(
                'news/search.html',
                articles=None,
                search_params=search_params,
                min=min
            )

        # Build the base query
        query = NewsArticle.query

        # Handle special keywords (case insensitive)
        symbol_parts = symbol.split()
        regions = ['CHINA', 'US', 'HK', 'OTHER']
        sorts = ['HIGHEST', 'LOWEST', 'LATEST']
        
        # Extract region and sort from symbol parts
        region_filter = next((p for p in symbol_parts if p in regions), None)
        sort_order = next((p for p in symbol_parts if p in sorts), 'LATEST')

        # Apply region filter
        if region_filter == 'CHINA':
            query = query.filter(
                or_(
                    NewsArticle.symbols.any(ArticleSymbol.symbol.like('SSE:%')),
                    NewsArticle.symbols.any(ArticleSymbol.symbol.like('SZSE:%'))
                )
            )
        elif region_filter == 'US':
            query = query.filter(
                or_(
                    NewsArticle.symbols.any(ArticleSymbol.symbol.like('NASDAQ:%')),
                    NewsArticle.symbols.any(ArticleSymbol.symbol.like('NYSE:%')),
                    NewsArticle.symbols.any(ArticleSymbol.symbol.like('AMEX:%'))
                )
            )
        elif region_filter == 'HK':
            query = query.filter(
                NewsArticle.symbols.any(ArticleSymbol.symbol.like('HKEX:%'))
            )
        elif region_filter == 'OTHER':
            query = query.filter(
                and_(
                    ~NewsArticle.symbols.any(ArticleSymbol.symbol.like('NASDAQ:%')),
                    ~NewsArticle.symbols.any(ArticleSymbol.symbol.like('NYSE:%')),
                    ~NewsArticle.symbols.any(ArticleSymbol.symbol.like('AMEX:%')),
                    ~NewsArticle.symbols.any(ArticleSymbol.symbol.like('SSE:%')),
                    ~NewsArticle.symbols.any(ArticleSymbol.symbol.like('SZSE:%')),
                    ~NewsArticle.symbols.any(ArticleSymbol.symbol.like('HKEX:%'))
                )
            )

        # Apply sorting
        if sort_order == 'HIGHEST':
            query = query.filter(NewsArticle.ai_sentiment_rating.isnot(None))
            query = query.order_by(
                NewsArticle.ai_sentiment_rating.desc(),
                NewsArticle.published_at.desc()
            )
        elif sort_order == 'LOWEST':
            query = query.filter(NewsArticle.ai_sentiment_rating.isnot(None))
            query = query.order_by(
                NewsArticle.ai_sentiment_rating.asc(),
                NewsArticle.published_at.desc()
            )
        else:  # LATEST
            query = query.order_by(NewsArticle.published_at.desc())

        # If no region/sort filters applied, handle as symbol search
        if not region_filter and sort_order == 'LATEST' and search_symbol.upper() not in (regions + sorts):
            # Convert symbol formats
            if re.match(r'^\d{4}\.HK$', search_symbol):
                search_symbol = f"HKEX:{int(search_symbol.replace('.HK', ''))}"
            elif re.search(r'\.SS$', search_symbol):
                search_symbol = f"SSE:{search_symbol.replace('.SS', '')}"
            elif re.search(r'\.SZ$', search_symbol):
                search_symbol = f"SZSE:{search_symbol.replace('.SZ', '')}"
            
            # Build symbol conditions
            if ':' not in search_symbol:
                symbol_conditions = [
                    ArticleSymbol.symbol == f"NASDAQ:{search_symbol}",
                    ArticleSymbol.symbol == f"NYSE:{search_symbol}",
                    ArticleSymbol.symbol == f"HKEX:{search_symbol}",
                    ArticleSymbol.symbol == f"SSE:{search_symbol}",
                    ArticleSymbol.symbol == f"SZSE:{search_symbol}",
                    ArticleSymbol.symbol == f"LSE:{search_symbol}",
                    ArticleSymbol.symbol == f"TSE:{search_symbol}",
                    ArticleSymbol.symbol == f"AMEX:{search_symbol}",
                    ArticleSymbol.symbol == search_symbol
                ]
                query = query.filter(NewsArticle.symbols.any(or_(*symbol_conditions)))
            # For US stocks with exchange prefix, try both exchanges
            elif search_symbol.startswith(('NYSE:', 'NASDAQ:')):
                base_symbol = search_symbol.split(':')[1]
                symbol_conditions = [
                    ArticleSymbol.symbol == f"NYSE:{base_symbol}",
                    ArticleSymbol.symbol == f"NASDAQ:{base_symbol}"
                ]
                query = query.filter(NewsArticle.symbols.any(or_(*symbol_conditions)))
            else:
                query = query.filter(NewsArticle.symbols.any(ArticleSymbol.symbol == search_symbol))

        # Paginate the results - 1 item per page
        pagination = query.paginate(page=page, per_page=1, error_out=False)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'articles': [{
                    'url': article.url,
                    'title': article.title,
                    'published_at': article.published_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'ai_summary': markdown.markdown(article.ai_summary, extensions=['fenced_code', 'tables']),
                    'ai_insights': markdown.markdown(article.ai_insights, extensions=['fenced_code', 'tables']),
                    'ai_sentiment_rating': article.ai_sentiment_rating,
                    'symbols': [{'symbol': s.symbol} for s in article.symbols]
                } for article in pagination.items],
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev,
                'page': pagination.page,
                'pages': pagination.pages,
                'total': pagination.total
            })

        return render_template(
            'news/search.html',
            articles=pagination,
            search_params=search_params,
            min=min
        )

    except Exception as e:
        current_app.logger.error(f"Error in search route: {str(e)}", exc_info=True)
        error_msg = f"An error occurred while searching: {str(e)}"
        return render_template(
            'news/search.html',
            error=error_msg,
            articles=None,
            search_params={'symbol': symbol if symbol else ''},
            min=min
        )

@bp.route('/api/fetch', methods=['POST'])
@login_required
def fetch_news():
    """Fetch and analyze news for specific symbols"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), HTTPStatus.BAD_REQUEST
            
        symbols = data.get('symbols', [])
        if not symbols:
            return jsonify({'status': 'error', 'message': 'No symbols provided'}), HTTPStatus.BAD_REQUEST
            
        limit = min(int(data.get('limit', 10)), 50)  # Cap limit at 50
        timeout = int(data.get('timeout', 30))  # Allow configurable timeout, default 30s
        
        logger.info(f"Fetching news for symbols: {symbols}, limit: {limit}")
        
        try:
            # Add a timeout to the news service call
            articles = news_service.fetch_and_analyze_news(
                symbols=symbols, 
                limit=limit,
                timeout=timeout
            )
            
            if not articles and len(symbols) > 0:
                logger.warning(f"No articles found for symbols: {symbols}")
                return jsonify({
                    'status': 'success',
                    'message': 'No articles found',
                    'articles': []
                })
            
            return jsonify({
                'status': 'success',
                'message': f'Successfully fetched {len(articles)} articles',
                'articles': articles
            })
        except Exception as service_error:
            logger.error(f"News service error for symbols {symbols}: {str(service_error)}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': f'News service error: {str(service_error)}',
                'symbols': symbols
            }), HTTPStatus.SERVICE_UNAVAILABLE
            
    except Exception as e:
        logger.error(f"Error fetching news: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Failed to fetch news: {str(e)}',
        }), HTTPStatus.INTERNAL_SERVER_ERROR

@bp.route('/api/batch-fetch', methods=['POST'])
@login_required
def batch_fetch():
    """Batch fetch news articles"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), HTTPStatus.BAD_REQUEST
        
        chunk_size = 5  # Process 5 symbols at a time
        symbols = data.get('symbols', DEFAULT_SYMBOLS[:10]) 
        articles_per_symbol = min(int(data.get('limit', 2)), 5)
        
        # Delete articles with no content and no insights
        try:
            articles_to_delete = NewsArticle.query.filter(
                NewsArticle.content.is_(None),
                NewsArticle.ai_insights.is_(None)
            ).all()
            
            for article in articles_to_delete:
                db.session.delete(article)
            
            db.session.commit()
            logger.info(f"Deleted {len(articles_to_delete)} articles with no content and insights")
        except Exception as e:
            logger.error(f"Error deleting empty articles: {str(e)}")
            db.session.rollback()
        
        all_articles = []
        chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
        
        for chunk in chunks:
            for symbol in chunk:
                try:
                    articles = news_service.fetch_and_analyze_news(
                        symbols=[symbol], 
                        limit=articles_per_symbol
                    )
                    all_articles.extend(articles)
                except Exception as e:
                    logger.error(f"Error fetching {symbol}: {str(e)}")
                    continue
        
        return jsonify({
            'status': 'success',
            'articles': all_articles,
            'total': len(all_articles)
        })
        
    except Exception as e:
        logger.error(f"Batch fetch error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
from datetime import datetime

def initialize_articles(cutoff_time: str) -> None:
    """
    Initialize AI fields for articles created after a specific timestamp.
    
    Args:
        cutoff_time (str): The timestamp in the format 'YYYY-MM-DD HH:MM:SS'.
                          Articles created after this time will have their AI fields set to None.
    """
    try:
        # Convert the cutoff_time string to a datetime object
        cutoff_datetime = datetime.strptime(cutoff_time, "%Y-%m-%d %H:%M:%S")
        
        # Update articles created after the cutoff time
        articles_updated = NewsArticle.query.filter(
            NewsArticle.created_at >= cutoff_datetime
        ).update({
            NewsArticle.ai_summary: None,
            NewsArticle.ai_insights: None,
            NewsArticle.ai_sentiment_rating: None
        })
        
        # Commit the changes to the database
        db.session.commit()
        logger.info(f"Initialized {articles_updated} articles created after {cutoff_time} with None values for AI fields")
    except Exception as e:
        logger.error(f"Error initializing articles: {str(e)}")
        db.session.rollback()
        raise
@bp.route('/api/get-articles-to-update', methods=['GET'])
@login_required
def get_articles_to_update():
    try:
        # Only fetch articles with missing AI fields
        missing_fields_articles = NewsArticle.query.filter(
            db.or_(
                NewsArticle.ai_summary.is_(None),
                NewsArticle.ai_insights.is_(None),
                NewsArticle.ai_sentiment_rating.is_(None)
            ),
            NewsArticle.content.isnot(None)
        ).all()
        
        # Still count irregular articles separately for reporting,
        # but don't include them in the total to process
        irregular_articles = NewsArticle.query.filter(
            db.or_(
                # Short or invalid content
                db.and_(NewsArticle.ai_summary.isnot(None), db.func.length(NewsArticle.ai_summary) < 50),
                db.and_(NewsArticle.ai_insights.isnot(None), db.func.length(NewsArticle.ai_insights) < 50),
                # Error markers in content
                db.and_(NewsArticle.ai_summary.isnot(None), NewsArticle.ai_summary.contains('error')),
                db.and_(NewsArticle.ai_insights.isnot(None), NewsArticle.ai_insights.contains('error')),
                # Summary contains placeholders left unchanged
                db.and_(NewsArticle.ai_summary.isnot(None), NewsArticle.ai_summary.contains('Keyword 1')),
                db.and_(NewsArticle.ai_insights.isnot(None), NewsArticle.ai_insights.contains('Insight 1'))
            ),
            NewsArticle.content.isnot(None)
        ).all()

        # Return the count of articles to be updated
        return jsonify({
            'status': 'success',
            'count': len(missing_fields_articles),
            'missing_fields_count': len(missing_fields_articles),
            'irregular_count': len(irregular_articles),
            'process_irregular': False  # Flag indicating we don't process irregular content in batch
        })
    except Exception as e:
        logger.error(f"Error getting articles to update: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
@bp.route('/api/latest-articles-wrapup', methods=['GET'])
@login_required
def get_latest_articles_wrapup():
    try:
        # Fetch the latest 10 articles
        articles = NewsArticle.query.order_by(NewsArticle.published_at.desc()).limit(10).all()

        wrapup_results = []

        for article in articles:
            wrapup_results.append({
                'id': article.id,
                'title': article.title,
                'url': article.url,
                'published_at': article.published_at.strftime("%Y-%m-%d %H:%M:%S"),
                'wrapup': article.brief_summary or "No summary available."  # Use brief_summary
            })

        return jsonify({
            'status': 'success',
            'articles': wrapup_results
        })

    except Exception as e:
        logger.error(f"Error in get_latest_articles_wrapup: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
@bp.route('/api/update-summaries', methods=['POST'])
@login_required
def update_ai_summaries():
    try:
        import requests

        OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
        OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }

        # Only fetch articles with missing AI fields, not irregular ones
        articles = NewsArticle.query.filter(
            db.or_(
                NewsArticle.ai_summary.is_(None),
                NewsArticle.ai_insights.is_(None),
                NewsArticle.ai_sentiment_rating.is_(None)
            ),
            NewsArticle.content.isnot(None)
        ).order_by(NewsArticle.id.desc()).limit(10).all()
        
        logger.info(f"Processing {len(articles)} articles with missing AI fields")
        
        processed = 0
        results = []

        for article in articles:
            try:
                ai_summary = None
                ai_insights = None
                ai_sentiment_rating = None
                
                if not article.ai_summary:
                    summary_payload = {
                        "model": "anthropic/claude-3.7-sonnet",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"""Generate summary with STRICT markdown formatting:
**Key Concepts/Keywords**  
- Keyword 1  
- Keyword 2  

**Key Points**  
- Point 1  
- Point 2  

**Context**  
- Background 1  
- Background 2  

Use proper line breaks between list items. Article: {article.content}"""
                            }
                        ],
                        "max_tokens": 500
                    }
                    summary_response = requests.post(OPENROUTER_API_URL, headers=headers, json=summary_payload)
                    summary_response.raise_for_status()
                    ai_summary = summary_response.json()['choices'][0]['message']['content']

                if not article.ai_insights:
                    insights_payload = {
                        "model": "anthropic/claude-3.7-sonnet",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"""Generate financial insights with STRICT markdown formatting:
**Key Insights**  
- Insight 1  
- Insight 2  

**Market Implications**  
- Implication 1  
- Implication 2  

**Conclusion**  
- Clear one-sentence conclusion  

Use proper line breaks between list items. Article: {article.content}"""
                            }
                        ],
                        "max_tokens": 500
                    }
                    insights_response = requests.post(OPENROUTER_API_URL, headers=headers, json=insights_payload)
                    insights_response.raise_for_status()
                    ai_insights = insights_response.json()['choices'][0]['message']['content']

                if article.ai_sentiment_rating is None:
                    sentiment_payload = {
                        "model": "anthropic/claude-3.7-sonnet",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"Analyze the market sentiment of this article and provide a single number rating from -100 (extremely bearish) to 100 (extremely bullish). Only return the number: {article.content}"
                            }
                        ],
                        "max_tokens": 10
                    }
                    sentiment_response = requests.post(OPENROUTER_API_URL, headers=headers, json=sentiment_payload)
                    sentiment_response.raise_for_status()
                    try:
                        rating = int(sentiment_response.json()['choices'][0]['message']['content'].strip())
                        ai_sentiment_rating = max(min(rating, 100), -100)
                    except ValueError:
                        logger.error(f"Could not parse sentiment rating for article {article.id}")
                        ai_sentiment_rating = 0

                # Calculate total content length to verify if processing was successful
                total_content = ""
                if ai_summary:
                    total_content += ai_summary
                if ai_insights:
                    total_content += ai_insights
                if ai_sentiment_rating is not None:
                    total_content += str(ai_sentiment_rating)
                
                # Only save if total content length is adequate (at least 100 characters)
                if len(total_content) >= 100:
                    if ai_summary:
                        article.ai_summary = ai_summary
                    if ai_insights:
                        article.ai_insights = ai_insights
                    if ai_sentiment_rating is not None:
                        article.ai_sentiment_rating = ai_sentiment_rating
                        
                    db.session.commit()
                    processed += 1
                    results.append({
                        'id': article.id,
                        'title': article.title,
                        'ai_sentiment_rating': article.ai_sentiment_rating,
                        'success': True,
                        'reprocessed': False
                    })
                else:
                    logger.warning(f"AI processing for article {article.id} yielded insufficient content ({len(total_content)} characters). Skipping.")
                    results.append({
                        'id': article.id,
                        'title': article.title,
                        'success': False,
                        'reason': 'Insufficient AI-generated content length'
                    })

            except Exception as e:
                logger.error(f"Error processing article {article.id}: {str(e)}")
                db.session.rollback()
                results.append({
                    'id': article.id,
                    'title': article.title if hasattr(article, 'title') else 'Unknown',
                    'success': False,
                    'reason': str(e)
                })
                continue

        return jsonify({
            'status': 'success',
            'processed': processed,
            'articles': results
        })

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/api/sentiment')
@login_required
def get_sentiment():
    """Get sentiment analysis data"""
    try:
        symbol = request.args.get('symbol')
        days = min(int(request.args.get('days', 7)), 90)
        
        if not symbol:
            return jsonify({
                'status': 'error',
                'message': 'Missing required symbol parameter'
            }), HTTPStatus.BAD_REQUEST

        symbol_upper = symbol.upper()
        symbol_filter = None  # Initialize symbol_filter
        
        # Handle special cases
        if symbol_upper == 'ALL':
            pass  # Keep existing behavior for 'all'
        else:
            # Check if it's a futures commodity
            if symbol_upper in FUTURES_MAPPING:
                futures_symbols = FUTURES_MAPPING[symbol_upper]
                symbol_filter = [ArticleSymbol.symbol == sym for sym in futures_symbols]
            elif ':' not in symbol_upper:
                # Try to match with any exchange prefix or without prefix
                symbol_filter = [
                    ArticleSymbol.symbol == f"NASDAQ:{symbol_upper}",
                    ArticleSymbol.symbol == f"NYSE:{symbol_upper}",
                    ArticleSymbol.symbol == f"HKEX:{symbol_upper}",
                    ArticleSymbol.symbol == f"SSE:{symbol_upper}",     # Shanghai Stock Exchange
                    ArticleSymbol.symbol == f"SZSE:{symbol_upper}",    # Shenzhen Stock Exchange
                    ArticleSymbol.symbol == f"LSE:{symbol_upper}",     # London Stock Exchange
                    ArticleSymbol.symbol == f"TSE:{symbol_upper}",     # Tokyo Stock Exchange
                    ArticleSymbol.symbol == f"TSX:{symbol_upper}",     # Toronto Stock Exchange
                    ArticleSymbol.symbol == f"ASX:{symbol_upper}",     # Australian Securities Exchange
                    ArticleSymbol.symbol == f"AMEX:{symbol_upper}",    # American Stock Exchange
                    ArticleSymbol.symbol == f"EURONEXT:{symbol_upper}", # European Exchange
                    ArticleSymbol.symbol == f"XETR:{symbol_upper}",    # German Exchange
                    ArticleSymbol.symbol == f"SP:{symbol_upper}",      # S&P
                    ArticleSymbol.symbol == f"DJ:{symbol_upper}",      # Dow Jones
                    ArticleSymbol.symbol == f"FOREXCOM:{symbol_upper}", # Forex
                    ArticleSymbol.symbol == f"BITSTAMP:{symbol_upper}", # Crypto
                    ArticleSymbol.symbol == f"COMEX:{symbol_upper}",   # Commodities Exchange
                    ArticleSymbol.symbol == f"NYMEX:{symbol_upper}",   # NY Mercantile Exchange
                    ArticleSymbol.symbol == f"TVC:{symbol_upper}",     # TradingView
                    ArticleSymbol.symbol == symbol_upper
                ]
            else:
                symbol_filter = [ArticleSymbol.symbol == symbol_upper]

        daily_data = news_service.get_sentiment_timeseries(
            symbol=symbol,
            days=days,
            symbol_filter=symbol_filter
        )
        
        # Calculate overall statistics
        total_sentiment = 0
        total_articles = 0
        highest_day = {'date': None, 'value': -100}
        lowest_day = {'date': None, 'value': 100}
        
        for date, data in daily_data.items():
            if data['article_count'] > 0:
                total_articles += data['article_count']
                total_sentiment += data['average_sentiment'] * data['article_count']
                
                if data['average_sentiment'] > highest_day['value']:
                    highest_day = {'date': date, 'value': data['average_sentiment']}
                if data['average_sentiment'] < lowest_day['value']:
                    lowest_day = {'date': date, 'value': data['average_sentiment']}
        
        average_sentiment = round(total_sentiment / total_articles, 2) if total_articles > 0 else 0
        
        return jsonify({
            'status': 'success',
            'data': {
                'average_sentiment': average_sentiment,
                'daily_sentiment': daily_data,
                'highest_day': highest_day,
                'lowest_day': lowest_day,
                'total_articles': total_articles
            }
        })
    except Exception as e:
        logger.error(f"Error getting sentiment data: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), HTTPStatus.INTERNAL_SERVER_ERROR

@bp.route('/api/trending')
@login_required
def get_trending():
    """Get trending topics"""
    try:
        days = int(request.args.get('days', 7))
        topics = news_service.get_trending_topics(days=days)
        return jsonify(topics)
    except Exception as e:
        logger.error(f"Error getting trending topics: {str(e)}")
        return jsonify({'error': 'Failed to get trending topics'}), 500

# @bp.route('/api/news/sentiment')
# @login_required
# def get_sentiment():
#     """Get sentiment analysis for specified parameters"""
#     try:
#         analytics = init_analytics()
        
#         symbol = request.args.get('symbol')
#         days = min(int(request.args.get('days', 7)), 90)  # Cap at 90 days
#         include_metrics = request.args.get('include_metrics', 'true').lower() == 'true'
        
#         analysis = analytics.get_sentiment_analysis(
#             symbol=symbol,
#             days=days,
#             include_metrics=include_metrics
#         )
        
#         return jsonify({
#             'status': 'success',
#             'data': analysis
#         })
        
#     except Exception as e:
#         logger.error(f"Error getting sentiment analysis: {str(e)}", exc_info=True)
#         return jsonify({
#             'status': 'error',
#             'message': 'Failed to get sentiment analysis'
#         }), HTTPStatus.INTERNAL_SERVER_ERROR

# @bp.route('/api/news/trending')
# @login_required
# def get_trending():
#     """Get trending topics analysis"""
#     try:
#         analytics = init_analytics()
#         days = min(int(request.args.get('days', 7)), 30)  # Cap at 30 days
        
#         topics = analytics.get_trending_topics(days=days)
        
#         return jsonify({
#             'status': 'success',
#             'data': topics
#         })
        
#     except Exception as e:
#         logger.error(f"Error getting trending topics: {str(e)}", exc_info=True)
#         return jsonify({
#             'status': 'error',
#             'message': 'Failed to get trending topics'
#         }), HTTPStatus.INTERNAL_SERVER_ERROR

# @bp.route('/api/news/correlations')
# @login_required
# def get_correlations():
#     """Get symbol correlations"""
#     try:
#         analytics = init_analytics()
        
#         symbol = request.args.get('symbol')
#         if not symbol:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Symbol is required'
#             }), HTTPStatus.BAD_REQUEST
            
#         days = min(int(request.args.get('days', 30)), 90)  # Cap at 90 days
        
#         correlations = analytics.get_symbol_correlations(
#             symbol=symbol,
#             days=days
#         )
        
#         return jsonify({
#             'status': 'success',
#             'data': correlations
#         })
        
#     except Exception as e:
#         logger.error(f"Error getting correlations: {str(e)}", exc_info=True)
#         return jsonify({
#             'status': 'error',
#             'message': 'Failed to get correlations'
#         }), HTTPStatus.INTERNAL_SERVER_ERROR

def _get_search_params():
    """Extract and validate search parameters from request"""
    now = datetime.now()
    
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, int(request.args.get('per_page', 20)))
    except (TypeError, ValueError):
        page = 1
        per_page = 20

    keyword = request.args.get('keyword')
    keyword = None if keyword in ['None', '', None] else keyword

    symbol = request.args.get('symbol')
    symbol = None if symbol in ['None', '', None] else symbol

    return {
        'keyword': keyword,
        'symbol': symbol,
        'start_date': request.args.get('start_date') or (now - timedelta(days=30)).strftime("%Y-%m-%d"),
        'end_date': request.args.get('end_date') or now.strftime("%Y-%m-%d"),
        'sentiment': request.args.get('sentiment') or None,
        'page': page,
        'per_page': per_page,
        'include_analytics': request.args.get('include_analytics', 'false').lower() == 'true'
    }
@bp.teardown_request
def cleanup(exception):
    """Cleanup resources after each request"""
    try:
        if hasattr(news_service, 'close'):
            news_service.close()
    except Exception as e:
        logger.error(f"Error in cleanup: {str(e)}")
        
@bp.route('/api/symbol-suggest')
@login_required
def symbol_suggest():
    symbol = request.args.get('symbol', '')
    if not symbol:
        return jsonify({'suggestions': []})
    
    suggested_symbol = get_tradingview_symbol(symbol)
    return jsonify({'suggestions': [{'symbol': suggested_symbol}]})

def get_tradingview_symbol(symbol):
    """Convert stock symbol to TradingView format"""
    symbol = symbol.upper()
    
    # Common NASDAQ stocks
    nasdaq_stocks = {
        'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'GOOG', 'META', 'NVDA', 'TSLA', 'AVGO', 
        'ADBE', 'CSCO', 'INTC', 'QCOM', 'AMD', 'INTU', 'AMAT', 'MU', 'NFLX', 'PEP'
    }
    
    # Hong Kong stocks
    if re.match(r'^\d{4}\.HK$', symbol, re.IGNORECASE):
        return f"HKEX:{symbol.replace('.HK', '').replace('.hk', '')}"
    elif symbol.startswith('0') and re.search(r'\.HK$', symbol, re.IGNORECASE):
        return f"HKEX:{symbol.replace('0', '').replace('.HK', '').replace('.hk', '')}"
        
    # Shanghai stocks
    elif re.search(r'\.SS$', symbol, re.IGNORECASE):
        return f"SSE:{symbol.replace('.SS', '').replace('.ss', '')}"
    
    # NASDAQ stocks
    elif symbol in nasdaq_stocks:
        return f"NASDAQ:{symbol}"
    elif symbol.endswith('.O'):
        return f"NASDAQ:{symbol.replace('.O', '')}"
        
    # Default to NYSE
    return f"NYSE:{symbol}"

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)  # HTTP 403 Forbidden
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/articles/manage')
@admin_required
def manage_articles():
    """Show editable table of articles"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        search = request.args.get('search', '')

        # Get paginated articles
        query = NewsArticle.query
        
        if search:
            search = f"%{search}%"
            query = query.filter(NewsArticle.title.ilike(search))
            
        articles = query.order_by(NewsArticle.published_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)

        return render_template(
            'news/manage_articles.html',
            articles=articles,
            search=search
        )

    except Exception as e:
        logger.error(f"Error managing articles: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/articles/update/<int:article_id>', methods=['GET', 'POST'])
@admin_required
def update_article(article_id):
    """Update article content"""
    try:
        article = NewsArticle.query.get_or_404(article_id)
        
        # Handle GET request to fetch article data
        if request.method == 'GET':
            return jsonify({
                'title': article.title,
                'content': article.content,
                'ai_summary': article.ai_summary,
                'ai_insights': article.ai_insights,
                'ai_sentiment_rating': article.ai_sentiment_rating
            })

        # Handle POST request to update article
        data = request.get_json()

        # Update fields if provided
        if 'title' in data:
            article.title = data['title']
        if 'content' in data:
            article.content = data['content']
        if 'ai_summary' in data:
            article.ai_summary = data['ai_summary']
        if 'ai_insights' in data:
            article.ai_insights = data['ai_insights']
        if 'ai_sentiment_rating' in data:
            article.ai_sentiment_rating = float(data['ai_sentiment_rating'])

        db.session.commit()
        return jsonify({'status': 'success'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/articles/view/<int:article_id>')
@admin_required
def view_article(article_id):
    """View article details"""
    try:
        article = NewsArticle.query.get_or_404(article_id)
        return render_template(
            'news/view_article.html',
            article=article
        )
    except Exception as e:
        logger.error(f"Error viewing article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/articles/clear-content/<int:article_id>', methods=['POST'])
@admin_required
def clear_article_content(article_id):
    """Clear only article content, keep AI fields"""
    try:
        article = NewsArticle.query.get_or_404(article_id)
        article.content = None
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing article {article_id} content: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/articles/clear-all-content', methods=['POST'])
@admin_required
def clear_all_content():
    """Clear content from all articles but preserve AI fields"""
    try:
        # Get search parameter to maintain filter if exists
        search = request.args.get('search', '')
        query = NewsArticle.query

        if search:
            search = f"%{search}%"
            query = query.filter(NewsArticle.title.ilike(search))

        # Update all matching articles
        articles = query.all()
        count = 0
        for article in articles:
            if article.content is not None:
                article.content = None
                count += 1
            if article.sentiment_label is not None:
                article.sentiment_label = None
                count += 1
            if article.sentiment_score is not None:
                article.sentiment_score = None
                count += 1
            if article.sentiment_explanation is not None:
                article.sentiment_explanation = None
                count += 1
            if article.brief_summary is not None:
                article.brief_summary = None
                count += 1
            if article.key_points is not None:
                article.key_points = None
                count += 1
            if article.market_impact_summary is not None:
                article.market_impact_summary = None
                count += 1

        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Cleared content from {count} articles'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing all content: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/articles/delete/<int:article_id>', methods=['POST'])
@admin_required
def delete_article(article_id):
    """Delete an article"""
    try:
        article = NewsArticle.query.get_or_404(article_id)
        db.session.delete(article)
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/irregular-ai-content')
@login_required
@admin_required
def irregular_ai_content():
    """Display articles with irregular AI content for review and reprocessing"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 10
        
        # Find articles with potentially irregular AI processing
        query = NewsArticle.query.filter(
            db.or_(
                # Short or invalid content
                db.and_(NewsArticle.ai_summary.isnot(None), db.func.length(NewsArticle.ai_summary) < 100),
                db.and_(NewsArticle.ai_insights.isnot(None), db.func.length(NewsArticle.ai_insights) < 100),
                # Error markers in content
                db.and_(NewsArticle.ai_summary.isnot(None), NewsArticle.ai_summary.contains('error')),
                db.and_(NewsArticle.ai_insights.isnot(None), NewsArticle.ai_insights.contains('error')),
                # Summary contains placeholders left unchanged
                db.and_(NewsArticle.ai_summary.isnot(None), NewsArticle.ai_summary.contains('Keyword 1')),
                db.and_(NewsArticle.ai_insights.isnot(None), NewsArticle.ai_insights.contains('Insight 1'))
            ),
            NewsArticle.content.isnot(None)
        ).order_by(NewsArticle.id.desc())
        
        # Paginate results
        articles = query.paginate(page=page, per_page=per_page)
        
        return render_template(
            'news/irregular_ai_content.html',
            articles=articles
        )
        
    except Exception as e:
        logger.error(f"Error displaying irregular AI content: {str(e)}")
        return render_template(
            'news/irregular_ai_content.html',
            error=str(e),
            articles=None
        )

@bp.route('/api/reprocess-article/<int:article_id>', methods=['POST'])
@login_required
@admin_required
def reprocess_article(article_id):
    """Reprocess AI content for a single article"""
    try:
        import requests
        
        # Get the article
        article = NewsArticle.query.get_or_404(article_id)
        
        if not article.content:
            return jsonify({
                'status': 'error',
                'message': 'Cannot reprocess article with no content'
            }), 400
        
        OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
        OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Process summary
        summary_payload = {
            "model": "anthropic/claude-3.7-sonnet",
            "messages": [
                {
                    "role": "user",
                    "content": f"""Generate summary with STRICT markdown formatting:
**Key Concepts/Keywords**  
- Keyword 1  
- Keyword 2  

**Key Points**  
- Point 1  
- Point 2  

**Context**  
- Background 1  
- Background 2  

Use proper line breaks between list items. Article: {article.content}"""
                }
            ],
            "max_tokens": 500
        }
        summary_response = requests.post(OPENROUTER_API_URL, headers=headers, json=summary_payload)
        summary_response.raise_for_status()
        ai_summary = summary_response.json()['choices'][0]['message']['content']
        
        # Process insights
        insights_payload = {
            "model": "anthropic/claude-3.7-sonnet",
            "messages": [
                {
                    "role": "user",
                    "content": f"""Generate financial insights with STRICT markdown formatting:
**Key Insights**  
- Insight 1  
- Insight 2  

**Market Implications**  
- Implication 1  
- Implication 2  

**Conclusion**  
- Clear one-sentence conclusion  

Use proper line breaks between list items. Article: {article.content}"""
                }
            ],
            "max_tokens": 500
        }
        insights_response = requests.post(OPENROUTER_API_URL, headers=headers, json=insights_payload)
        insights_response.raise_for_status()
        ai_insights = insights_response.json()['choices'][0]['message']['content']
        
        # Process sentiment
        sentiment_payload = {
            "model": "anthropic/claude-3.7-sonnet",
            "messages": [
                {
                    "role": "user",
                    "content": f"Analyze the market sentiment of this article and provide a single number rating from -100 (extremely bearish) to 100 (extremely bullish). Only return the number: {article.content}"
                }
            ],
            "max_tokens": 10
        }
        sentiment_response = requests.post(OPENROUTER_API_URL, headers=headers, json=sentiment_payload)
        sentiment_response.raise_for_status()
        
        try:
            rating = int(sentiment_response.json()['choices'][0]['message']['content'].strip())
            ai_sentiment_rating = max(min(rating, 100), -100)
        except ValueError:
            logger.error(f"Could not parse sentiment rating for article {article.id}")
            ai_sentiment_rating = 0
        
        # Calculate total content length to verify if processing was successful
        total_content = ai_summary + ai_insights + str(ai_sentiment_rating)
        
        if len(total_content) < 100:
            return jsonify({
                'status': 'error',
                'message': 'Generated AI content is too short - processing may have failed'
            }), 400
        
        # Update the article
        article.ai_summary = ai_summary
        article.ai_insights = ai_insights
        article.ai_sentiment_rating = ai_sentiment_rating
        
        # Save changes
        db.session.commit()
        
        # Return success
        return jsonify({
            'status': 'success',
            'message': 'Article successfully reprocessed',
            'article': {
                'id': article.id,
                'title': article.title,
                'ai_summary': article.ai_summary,
                'ai_insights': article.ai_insights,
                'ai_sentiment_rating': article.ai_sentiment_rating
            }
        })
        
    except Exception as e:
        logger.error(f"Error reprocessing article {article_id}: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500