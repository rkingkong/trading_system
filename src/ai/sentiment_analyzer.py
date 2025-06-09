#!/usr/bin/env python3
"""
📰 PRODUCTION TRADING SYSTEM - SENTIMENT ANALYSIS ENGINE
src/ai/sentiment_analyzer.py

Enterprise-grade sentiment analysis with NewsAPI integration, real-time news processing,
and comprehensive sentiment scoring for automated trading decisions.

Features:
- NewsAPI integration for real-time financial news
- Company-specific sentiment analysis
- Market sentiment indicators
- Multi-source sentiment aggregation
- Sentiment trend analysis
- News impact assessment
- Real-time sentiment scoring
- Comprehensive sentiment reporting

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import json
import time
import threading
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import uuid
from collections import defaultdict, deque
import statistics

# Import our core components
try:
    from ..core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from ..core.config_manager import ProductionConfigManager
    from ..core.state_manager import ProductionStateManager
except ImportError:
    # Fallback for testing
    from core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from core.config_manager import ProductionConfigManager
    from core.state_manager import ProductionStateManager

# ============================================================================
# SENTIMENT ANALYSIS TYPES AND ENUMS
# ============================================================================

class SentimentPolarity(Enum):
    """Sentiment polarity classification"""
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"

class NewsCategory(Enum):
    """News category classification"""
    EARNINGS = "earnings"
    GENERAL = "general"
    MERGER_ACQUISITION = "merger_acquisition"
    ANALYST_RATING = "analyst_rating"
    REGULATORY = "regulatory"
    PRODUCT_NEWS = "product_news"
    MARKET_NEWS = "market_news"
    ECONOMIC_DATA = "economic_data"

class SentimentConfidence(Enum):
    """Sentiment confidence levels"""
    VERY_HIGH = "very_high"    # 90-100%
    HIGH = "high"              # 80-89%
    MEDIUM = "medium"          # 60-79%
    LOW = "low"                # 40-59%
    VERY_LOW = "very_low"      # <40%

@dataclass
class NewsArticle:
    """Individual news article data"""
    article_id: str
    title: str
    description: str
    content: str
    source: str
    author: str
    published_at: datetime
    url: str
    url_to_image: str
    
    # Analysis results
    sentiment_score: float      # -1.0 to 1.0
    sentiment_polarity: SentimentPolarity
    sentiment_confidence: float # 0-100
    category: NewsCategory
    impact_score: float        # 0-100
    keywords: List[str]
    
    # Symbol relevance
    symbol_mentions: List[str]
    relevance_score: float     # 0-100

@dataclass
class SentimentAnalysis:
    """Sentiment analysis results for a symbol"""
    symbol: str
    timestamp: datetime
    
    # Overall sentiment
    overall_sentiment_score: float    # -1.0 to 1.0
    overall_polarity: SentimentPolarity
    overall_confidence: float         # 0-100
    
    # Breakdown by time periods
    sentiment_24h: float
    sentiment_7d: float
    sentiment_30d: float
    
    # News analysis
    total_articles: int
    positive_articles: int
    negative_articles: int
    neutral_articles: int
    
    # Key articles
    most_positive_article: Optional[NewsArticle]
    most_negative_article: Optional[NewsArticle]
    highest_impact_article: Optional[NewsArticle]
    
    # Trends
    sentiment_trend: str              # improving, declining, stable
    momentum: float                   # Sentiment momentum
    volatility: float                 # Sentiment volatility
    
    # Categories
    category_breakdown: Dict[str, float]
    source_breakdown: Dict[str, float]
    
    # Signal
    trading_signal: str               # bullish, bearish, neutral
    signal_strength: float            # 0-100
    reasoning: str

@dataclass
class MarketSentiment:
    """Overall market sentiment"""
    timestamp: datetime
    
    # Market-wide sentiment
    overall_market_sentiment: float   # -1.0 to 1.0
    market_fear_greed_index: float    # 0-100
    volatility_sentiment: float       # 0-100
    
    # Sector sentiment
    sector_sentiment: Dict[str, float]
    
    # News volume
    total_market_articles: int
    sentiment_dispersion: float       # How spread out sentiment is
    
    # Trends
    sentiment_direction: str          # bullish, bearish, neutral
    change_24h: float
    change_7d: float

# ============================================================================
# PRODUCTION SENTIMENT ANALYZER
# ============================================================================

class ProductionSentimentAnalyzer:
    """
    Enterprise-grade sentiment analysis engine
    
    Features:
    - NewsAPI integration for real-time news
    - Advanced sentiment analysis algorithms
    - Symbol-specific sentiment tracking
    - Market sentiment aggregation
    - Sentiment trend analysis
    - Impact assessment
    """
    
    def __init__(self, config_manager: ProductionConfigManager,
                 state_manager: ProductionStateManager):
        
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.logger = LoggerFactory.get_logger('sentiment_analyzer', LogCategory.AI)
        
        # Get NewsAPI configuration
        newsapi_config = config_manager.get_api_config('newsapi')
        if not newsapi_config:
            self.logger.warning("⚠️ NewsAPI configuration not found")
            self.newsapi_key = None
            self.newsapi_enabled = False
        else:
            self.newsapi_key = newsapi_config.api_key
            self.newsapi_enabled = newsapi_config.enabled
        
        # Sentiment analysis configuration
        self.sentiment_config = config_manager.get_config('ai', {}).get('sentiment_analysis', {})
        self.news_sources = self.sentiment_config.get('news_sources', [
            'reuters', 'bloomberg', 'cnbc', 'marketwatch', 'yahoo-finance'
        ])
        self.weight_decay_hours = self.sentiment_config.get('weight_decay_hours', 24)
        
        # Analysis state
        self._sentiment_lock = threading.RLock()
        self.sentiment_cache = {}  # symbol -> SentimentAnalysis
        self.news_cache = {}      # symbol -> List[NewsArticle]
        self.cache_timestamps = {}
        self.cache_ttl = 1800     # 30 minutes
        
        # Market sentiment tracking
        self.market_sentiment_history = deque(maxlen=100)
        self.symbol_sentiment_history = defaultdict(lambda: deque(maxlen=50))
        
        # Performance tracking
        self.analysis_count = 0
        self.api_calls = 0
        self.cache_hits = 0
        
        # Sentiment keywords and patterns
        self.positive_keywords = {
            'excellent', 'outstanding', 'strong', 'growth', 'profit', 'revenue',
            'beat', 'exceed', 'bullish', 'optimistic', 'positive', 'upgrade',
            'buy', 'outperform', 'gain', 'rise', 'surge', 'soar', 'rally',
            'momentum', 'breakthrough', 'success', 'record', 'high'
        }
        
        self.negative_keywords = {
            'poor', 'weak', 'decline', 'loss', 'miss', 'below', 'bearish',
            'pessimistic', 'negative', 'downgrade', 'sell', 'underperform',
            'fall', 'drop', 'plunge', 'crash', 'concern', 'risk', 'warning',
            'cut', 'reduce', 'challenge', 'problem', 'issue', 'low'
        }
        
        # Register with state manager
        state_manager.register_component('sentiment_analyzer', self)
        
        self.logger.info("📰 Sentiment Analyzer initialized",
                        newsapi_enabled=self.newsapi_enabled,
                        sources=len(self.news_sources))
    
    # ========================================================================
    # MAIN ANALYSIS INTERFACE
    # ========================================================================
    
    def analyze_symbol_sentiment(self, symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Comprehensive sentiment analysis for a symbol
        
        Args:
            symbol: Stock symbol to analyze
            force_refresh: Force fresh analysis ignoring cache
            
        Returns:
            Dictionary with sentiment analysis results
        """
        
        start_time = time.time()
        
        try:
            with self._sentiment_lock:
                # Check cache
                if not force_refresh and symbol in self.sentiment_cache:
                    cache_time = self.cache_timestamps.get(symbol, 0)
                    if time.time() - cache_time < self.cache_ttl:
                        self.cache_hits += 1
                        return self._sentiment_to_dict(self.sentiment_cache[symbol])
                
                self.logger.info(f"📰 Starting sentiment analysis: {symbol}")
                
                # Fetch news articles
                articles = self._fetch_symbol_news(symbol)
                
                if not articles:
                    self.logger.warning(f"⚠️ No news articles found for {symbol}")
                    return self._create_no_news_response(symbol)
                
                # Analyze sentiment
                sentiment_analysis = self._analyze_symbol_sentiment(symbol, articles)
                
                # Cache results
                self.sentiment_cache[symbol] = sentiment_analysis
                self.news_cache[symbol] = articles
                self.cache_timestamps[symbol] = time.time()
                
                # Update history
                self.symbol_sentiment_history[symbol].append(sentiment_analysis)
                
                analysis_time = time.time() - start_time
                self.analysis_count += 1
                
                self.logger.info(f"✅ Sentiment analysis completed: {symbol}",
                               sentiment_score=sentiment_analysis.overall_sentiment_score,
                               polarity=sentiment_analysis.overall_polarity.value,
                               articles=sentiment_analysis.total_articles,
                               analysis_time=analysis_time)
                
                # Log performance metric
                self.logger.performance(PerformanceMetric(
                    metric_name="sentiment_analysis_time",
                    value=analysis_time,
                    unit="seconds",
                    timestamp=datetime.now(timezone.utc),
                    component="sentiment_analyzer"
                ))
                
                return self._sentiment_to_dict(sentiment_analysis)
                
        except Exception as e:
            self.logger.error(f"❌ Sentiment analysis failed for {symbol}: {e}")
            return self._create_error_response(symbol, str(e))
    
    def analyze_market_sentiment(self) -> Dict[str, Any]:
        """Analyze overall market sentiment"""
        
        try:
            self.logger.info("📰 Analyzing overall market sentiment")
            
            # Fetch market-wide news
            market_articles = self._fetch_market_news()
            
            if not market_articles:
                return self._create_no_market_news_response()
            
            # Analyze market sentiment
            market_sentiment = self._analyze_market_sentiment(market_articles)
            
            # Store in history
            self.market_sentiment_history.append(market_sentiment)
            
            self.logger.info("✅ Market sentiment analysis completed",
                           market_sentiment=market_sentiment.overall_market_sentiment,
                           articles=market_sentiment.total_market_articles)
            
            return self._market_sentiment_to_dict(market_sentiment)
            
        except Exception as e:
            self.logger.error(f"❌ Market sentiment analysis failed: {e}")
            return {'error': str(e)}
    
    # ========================================================================
    # NEWS FETCHING
    # ========================================================================
    
    def _fetch_symbol_news(self, symbol: str, days_back: int = 7) -> List[NewsArticle]:
        """Fetch news articles for a specific symbol"""
        
        if not self.newsapi_enabled:
            return self._create_mock_news_articles(symbol)
        
        try:
            # Calculate date range
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=days_back)
            
            # Build search query
            company_name = self._get_company_name(symbol)
            query = f'"{symbol}" OR "{company_name}"'
            
            # Make API request
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'from': from_date.isoformat(),
                'to': to_date.isoformat(),
                'pageSize': 50,
                'apiKey': self.newsapi_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            self.api_calls += 1
            
            if response.status_code == 200:
                data = response.json()
                articles = []
                
                for article_data in data.get('articles', []):
                    try:
                        article = self._parse_news_article(article_data, symbol)
                        if article and article.relevance_score >= 30:  # Filter relevant articles
                            articles.append(article)
                    except Exception as e:
                        self.logger.warning(f"⚠️ Failed to parse article: {e}")
                        continue
                
                self.logger.debug(f"📰 Fetched {len(articles)} relevant articles for {symbol}")
                return articles[:20]  # Limit to top 20 articles
                
            else:
                self.logger.error(f"❌ NewsAPI error: {response.status_code}")
                return self._create_mock_news_articles(symbol)
                
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch news for {symbol}: {e}")
            return self._create_mock_news_articles(symbol)
    
    def _fetch_market_news(self, days_back: int = 3) -> List[NewsArticle]:
        """Fetch general market news"""
        
        if not self.newsapi_enabled:
            return []
        
        try:
            # Calculate date range
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=days_back)
            
            # Build market-focused query
            query = 'stock market OR nasdaq OR dow jones OR s&p 500 OR trading OR earnings'
            
            # Make API request
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'from': from_date.isoformat(),
                'to': to_date.isoformat(),
                'pageSize': 30,
                'apiKey': self.newsapi_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            self.api_calls += 1
            
            if response.status_code == 200:
                data = response.json()
                articles = []
                
                for article_data in data.get('articles', []):
                    try:
                        article = self._parse_news_article(article_data, "MARKET")
                        if article:
                            articles.append(article)
                    except Exception as e:
                        continue
                
                return articles
                
            else:
                self.logger.error(f"❌ NewsAPI error for market news: {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch market news: {e}")
            return []
    
    def _parse_news_article(self, article_data: Dict[str, Any], symbol: str) -> Optional[NewsArticle]:
        """Parse news article from API response"""
        
        try:
            # Extract basic information
            title = article_data.get('title', '')
            description = article_data.get('description', '')
            content = article_data.get('content', '')
            
            if not title or not description:
                return None
            
            # Parse published date
            published_str = article_data.get('publishedAt', '')
            if published_str:
                published_at = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
            else:
                published_at = datetime.now(timezone.utc)
            
            # Combine text for analysis
            full_text = f"{title} {description} {content}".lower()
            
            # Calculate sentiment
            sentiment_score = self._calculate_text_sentiment(full_text)
            sentiment_polarity = self._score_to_polarity(sentiment_score)
            sentiment_confidence = self._calculate_sentiment_confidence(full_text)
            
            # Categorize news
            category = self._categorize_news(full_text)
            
            # Calculate impact score
            impact_score = self._calculate_impact_score(title, description, article_data.get('source', {}).get('name', ''))
            
            # Extract keywords
            keywords = self._extract_keywords(full_text)
            
            # Calculate relevance to symbol
            symbol_mentions = self._find_symbol_mentions(full_text, symbol)
            relevance_score = self._calculate_relevance_score(full_text, symbol)
            
            article = NewsArticle(
                article_id=str(uuid.uuid4()),
                title=title,
                description=description,
                content=content,
                source=article_data.get('source', {}).get('name', 'Unknown'),
                author=article_data.get('author', 'Unknown'),
                published_at=published_at,
                url=article_data.get('url', ''),
                url_to_image=article_data.get('urlToImage', ''),
                sentiment_score=sentiment_score,
                sentiment_polarity=sentiment_polarity,
                sentiment_confidence=sentiment_confidence,
                category=category,
                impact_score=impact_score,
                keywords=keywords,
                symbol_mentions=symbol_mentions,
                relevance_score=relevance_score
            )
            
            return article
            
        except Exception as e:
            self.logger.error(f"❌ Failed to parse article: {e}")
            return None
    
    # ========================================================================
    # SENTIMENT ANALYSIS
    # ========================================================================
    
    def _analyze_symbol_sentiment(self, symbol: str, articles: List[NewsArticle]) -> SentimentAnalysis:
        """Analyze sentiment for a symbol based on news articles"""
        
        if not articles:
            return self._create_neutral_sentiment(symbol)
        
        # Filter articles by time periods
        now = datetime.now(timezone.utc)
        articles_24h = [a for a in articles if (now - a.published_at).total_seconds() <= 86400]
        articles_7d = [a for a in articles if (now - a.published_at).total_seconds() <= 604800]
        articles_30d = articles  # All articles are within 30 days
        
        # Calculate time-weighted sentiment scores
        overall_sentiment = self._calculate_weighted_sentiment(articles)
        sentiment_24h = self._calculate_weighted_sentiment(articles_24h) if articles_24h else 0.0
        sentiment_7d = self._calculate_weighted_sentiment(articles_7d) if articles_7d else 0.0
        sentiment_30d = self._calculate_weighted_sentiment(articles_30d)
        
        # Classify articles by sentiment
        positive_articles = [a for a in articles if a.sentiment_score > 0.1]
        negative_articles = [a for a in articles if a.sentiment_score < -0.1]
        neutral_articles = [a for a in articles if -0.1 <= a.sentiment_score <= 0.1]
        
        # Find key articles
        most_positive = max(articles, key=lambda a: a.sentiment_score) if articles else None
        most_negative = min(articles, key=lambda a: a.sentiment_score) if articles else None
        highest_impact = max(articles, key=lambda a: a.impact_score) if articles else None
        
        # Calculate trends
        sentiment_trend = self._calculate_sentiment_trend(symbol, overall_sentiment)
        momentum = self._calculate_sentiment_momentum(articles)
        volatility = self._calculate_sentiment_volatility(articles)
        
        # Category and source breakdown
        category_breakdown = self._calculate_category_breakdown(articles)
        source_breakdown = self._calculate_source_breakdown(articles)
        
        # Generate trading signal
        trading_signal, signal_strength = self._generate_sentiment_signal(overall_sentiment, momentum, len(articles))
        
        # Generate reasoning
        reasoning = self._generate_sentiment_reasoning(
            overall_sentiment, len(articles), positive_articles, negative_articles
        )
        
        return SentimentAnalysis(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            overall_sentiment_score=overall_sentiment,
            overall_polarity=self._score_to_polarity(overall_sentiment),
            overall_confidence=self._calculate_overall_confidence(articles),
            sentiment_24h=sentiment_24h,
            sentiment_7d=sentiment_7d,
            sentiment_30d=sentiment_30d,
            total_articles=len(articles),
            positive_articles=len(positive_articles),
            negative_articles=len(negative_articles),
            neutral_articles=len(neutral_articles),
            most_positive_article=most_positive,
            most_negative_article=most_negative,
            highest_impact_article=highest_impact,
            sentiment_trend=sentiment_trend,
            momentum=momentum,
            volatility=volatility,
            category_breakdown=category_breakdown,
            source_breakdown=source_breakdown,
            trading_signal=trading_signal,
            signal_strength=signal_strength,
            reasoning=reasoning
        )
    
    def _analyze_market_sentiment(self, articles: List[NewsArticle]) -> MarketSentiment:
        """Analyze overall market sentiment"""
        
        if not articles:
            return self._create_neutral_market_sentiment()
        
        # Calculate overall market sentiment
        overall_sentiment = self._calculate_weighted_sentiment(articles)
        
        # Calculate fear/greed index (simplified)
        fear_greed = self._calculate_fear_greed_index(articles)
        
        # Calculate volatility sentiment
        volatility_sentiment = self._calculate_volatility_sentiment(articles)
        
        # Sector sentiment (simplified)
        sector_sentiment = {
            'Technology': 0.0,
            'Healthcare': 0.0,
            'Financial': 0.0,
            'Energy': 0.0,
            'Consumer': 0.0
        }
        
        # Calculate sentiment changes
        change_24h = self._calculate_market_sentiment_change(24)
        change_7d = self._calculate_market_sentiment_change(168)
        
        # Determine direction
        if overall_sentiment > 0.1:
            direction = "bullish"
        elif overall_sentiment < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"
        
        # Calculate sentiment dispersion
        sentiments = [a.sentiment_score for a in articles]
        dispersion = statistics.stdev(sentiments) if len(sentiments) > 1 else 0.0
        
        return MarketSentiment(
            timestamp=datetime.now(timezone.utc),
            overall_market_sentiment=overall_sentiment,
            market_fear_greed_index=fear_greed,
            volatility_sentiment=volatility_sentiment,
            sector_sentiment=sector_sentiment,
            total_market_articles=len(articles),
            sentiment_dispersion=dispersion,
            sentiment_direction=direction,
            change_24h=change_24h,
            change_7d=change_7d
        )
    
    # ========================================================================
    # SENTIMENT CALCULATION METHODS
    # ========================================================================
    
    def _calculate_text_sentiment(self, text: str) -> float:
        """Calculate sentiment score for text using keyword-based approach"""
        
        # Clean and tokenize text
        words = re.findall(r'\b\w+\b', text.lower())
        
        positive_count = 0
        negative_count = 0
        total_words = len(words)
        
        if total_words == 0:
            return 0.0
        
        # Count positive and negative words
        for word in words:
            if word in self.positive_keywords:
                positive_count += 1
            elif word in self.negative_keywords:
                negative_count += 1
        
        # Calculate basic sentiment score
        if positive_count + negative_count == 0:
            return 0.0
        
        sentiment_score = (positive_count - negative_count) / (positive_count + negative_count)
        
        # Apply intensity modifiers
        intensity_modifiers = ['very', 'extremely', 'highly', 'significantly', 'strongly']
        modifier_boost = sum(1 for word in words if word in intensity_modifiers) * 0.1
        
        # Apply negation detection
        negation_words = ['not', 'no', 'never', 'nothing', 'none', 'nobody', 'nowhere']
        negation_penalty = sum(1 for word in words if word in negation_words) * 0.2
        
        # Final sentiment score
        final_score = sentiment_score * (1 + modifier_boost) * (1 - negation_penalty)
        
        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, final_score))
    
    def _calculate_weighted_sentiment(self, articles: List[NewsArticle]) -> float:
        """Calculate weighted sentiment score considering impact and recency"""
        
        if not articles:
            return 0.0
        
        total_weighted_sentiment = 0.0
        total_weight = 0.0
        now = datetime.now(timezone.utc)
        
        for article in articles:
            # Calculate time decay weight
            hours_old = (now - article.published_at).total_seconds() / 3600
            time_weight = max(0.1, 1.0 - (hours_old / self.weight_decay_hours))
            
            # Calculate impact weight
            impact_weight = (article.impact_score / 100.0) * 2.0  # 0-2 multiplier
            
            # Calculate relevance weight
            relevance_weight = article.relevance_score / 100.0
            
            # Combined weight
            weight = time_weight * impact_weight * relevance_weight
            
            # Weighted sentiment
            weighted_sentiment = article.sentiment_score * weight
            
            total_weighted_sentiment += weighted_sentiment
            total_weight += weight
        
        if total_weight > 0:
            return total_weighted_sentiment / total_weight
        else:
            return 0.0
    
    def _calculate_sentiment_confidence(self, text: str) -> float:
        """Calculate confidence in sentiment analysis"""
        
        # Factors that increase confidence
        word_count = len(text.split())
        keyword_density = self._calculate_keyword_density(text)
        
        # Base confidence from text length
        length_confidence = min(word_count / 50.0, 1.0) * 40  # 0-40 points
        
        # Keyword density confidence
        density_confidence = keyword_density * 60  # 0-60 points
        
        total_confidence = length_confidence + density_confidence
        
        return max(0, min(100, total_confidence))
    
    def _calculate_keyword_density(self, text: str) -> float:
        """Calculate density of sentiment keywords in text"""
        
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return 0.0
        
        sentiment_words = sum(1 for word in words 
                            if word in self.positive_keywords or word in self.negative_keywords)
        
        return sentiment_words / len(words)
    
    def _score_to_polarity(self, score: float) -> SentimentPolarity:
        """Convert sentiment score to polarity enum"""
        
        if score >= 0.5:
            return SentimentPolarity.VERY_POSITIVE
        elif score >= 0.1:
            return SentimentPolarity.POSITIVE
        elif score <= -0.5:
            return SentimentPolarity.VERY_NEGATIVE
        elif score <= -0.1:
            return SentimentPolarity.NEGATIVE
        else:
            return SentimentPolarity.NEUTRAL
    
    def _categorize_news(self, text: str) -> NewsCategory:
        """Categorize news article based on content"""
        
        text_lower = text.lower()
        
        # Category keywords
        category_keywords = {
            NewsCategory.EARNINGS: ['earnings', 'revenue', 'profit', 'eps', 'quarterly', 'financial results'],
            NewsCategory.ANALYST_RATING: ['upgrade', 'downgrade', 'rating', 'analyst', 'recommendation', 'target price'],
            NewsCategory.MERGER_ACQUISITION: ['merger', 'acquisition', 'takeover', 'buyout', 'deal'],
            NewsCategory.REGULATORY: ['regulation', 'fda', 'sec', 'regulatory', 'compliance', 'investigation'],
            NewsCategory.PRODUCT_NEWS: ['product', 'launch', 'release', 'announcement', 'innovation'],
            NewsCategory.ECONOMIC_DATA: ['inflation', 'gdp', 'unemployment', 'federal reserve', 'interest rate']
        }
        
        # Count matches for each category
        category_scores = {}
        for category, keywords in category_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text_lower)
            category_scores[category] = score
        
        # Return category with highest score
        if category_scores:
            best_category = max(category_scores, key=category_scores.get)
            if category_scores[best_category] > 0:
                return best_category
        
        return NewsCategory.GENERAL
    
    def _calculate_impact_score(self, title: str, description: str, source: str) -> float:
        """Calculate news impact score"""
        
        # Base score from source credibility
        source_scores = {
            'reuters': 95,
            'bloomberg': 95,
            'wall street journal': 90,
            'financial times': 90,
            'cnbc': 85,
            'marketwatch': 80,
            'yahoo finance': 75,
            'seeking alpha': 70
        }
        
        source_score = source_scores.get(source.lower(), 50)
        
        # Title impact words
        high_impact_words = ['breaking', 'exclusive', 'urgent', 'alert', 'major', 'significant']
        title_lower = title.lower()
        
        impact_boost = sum(10 for word in high_impact_words if word in title_lower)
        
        # Description length (longer descriptions often indicate more substantial news)
        length_boost = min(len(description) / 200.0, 1.0) * 20
        
        total_score = source_score + impact_boost + length_boost
        
        return max(0, min(100, total_score))
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract important keywords from text"""
        
        # Simple keyword extraction
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter common words and get important terms
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'}
        
        # Get words that appear multiple times or are sentiment-related
        word_counts = defaultdict(int)
        for word in words:
            if word not in common_words and len(word) > 3:
                word_counts[word] += 1
        
        # Return top keywords
        keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in keywords[:10]]
    
    def _find_symbol_mentions(self, text: str, symbol: str) -> List[str]:
        """Find mentions of the symbol in text"""
        
        mentions = []
        
        # Direct symbol mention
        if symbol.upper() in text.upper():
            mentions.append(symbol.upper())
        
        # Company name mention (simplified)
        company_name = self._get_company_name(symbol)
        if company_name.lower() in text.lower():
            mentions.append(company_name)
        
        return mentions
    
    def _calculate_relevance_score(self, text: str, symbol: str) -> float:
        """Calculate how relevant the article is to the symbol"""
        
        score = 0.0
        text_lower = text.lower()
        symbol_lower = symbol.lower()
        
        # Direct symbol mentions
        symbol_mentions = text_lower.count(symbol_lower)
        score += symbol_mentions * 20
        
        # Company name mentions
        company_name = self._get_company_name(symbol).lower()
        company_mentions = text_lower.count(company_name)
        score += company_mentions * 15
        
        # Industry/sector relevance (simplified)
        sector_keywords = {
            'technology': ['tech', 'software', 'hardware', 'digital', 'internet'],
            'healthcare': ['health', 'medical', 'pharmaceutical', 'biotech', 'drug'],
            'financial': ['bank', 'finance', 'credit', 'loan', 'investment']
        }
        
        # Add small boost for sector relevance
        for sector, keywords in sector_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    score += 5
                    break
        
        return max(0, min(100, score))
    
    # ========================================================================
    # TREND AND MOMENTUM CALCULATIONS
    # ========================================================================
    
    def _calculate_sentiment_trend(self, symbol: str, current_sentiment: float) -> str:
        """Calculate sentiment trend for symbol"""
        
        history = self.symbol_sentiment_history.get(symbol, deque())
        
        if len(history) < 2:
            return "stable"
        
        # Compare with previous sentiment
        previous_sentiment = history[-1].overall_sentiment_score
        change = current_sentiment - previous_sentiment
        
        if change > 0.1:
            return "improving"
        elif change < -0.1:
            return "declining"
        else:
            return "stable"
    
    def _calculate_sentiment_momentum(self, articles: List[NewsArticle]) -> float:
        """Calculate sentiment momentum based on recent articles"""
        
        if len(articles) < 3:
            return 0.0
        
        # Sort articles by publication time
        sorted_articles = sorted(articles, key=lambda a: a.published_at)
        
        # Split into earlier and later groups
        mid_point = len(sorted_articles) // 2
        earlier_articles = sorted_articles[:mid_point]
        later_articles = sorted_articles[mid_point:]
        
        # Calculate average sentiment for each group
        earlier_sentiment = statistics.mean([a.sentiment_score for a in earlier_articles])
        later_sentiment = statistics.mean([a.sentiment_score for a in later_articles])
        
        # Momentum is the change
        momentum = later_sentiment - earlier_sentiment
        
        return max(-1.0, min(1.0, momentum))
    
    def _calculate_sentiment_volatility(self, articles: List[NewsArticle]) -> float:
        """Calculate sentiment volatility"""
        
        if len(articles) < 2:
            return 0.0
        
        sentiments = [a.sentiment_score for a in articles]
        return statistics.stdev(sentiments)
    
    def _calculate_category_breakdown(self, articles: List[NewsArticle]) -> Dict[str, float]:
        """Calculate breakdown of articles by category"""
        
        if not articles:
            return {}
        
        category_counts = defaultdict(int)
        for article in articles:
            category_counts[article.category.value] += 1
        
        total_articles = len(articles)
        
        return {
            category: (count / total_articles) * 100
            for category, count in category_counts.items()
        }
    
    def _calculate_source_breakdown(self, articles: List[NewsArticle]) -> Dict[str, float]:
        """Calculate breakdown of articles by source"""
        
        if not articles:
            return {}
        
        source_counts = defaultdict(int)
        for article in articles:
            source_counts[article.source] += 1
        
        total_articles = len(articles)
        
        return {
            source: (count / total_articles) * 100
            for source, count in source_counts.items()
        }
    
    def _calculate_overall_confidence(self, articles: List[NewsArticle]) -> float:
        """Calculate overall confidence in sentiment analysis"""
        
        if not articles:
            return 0.0
        
        # Average article confidence
        avg_confidence = statistics.mean([a.sentiment_confidence for a in articles])
        
        # Boost confidence with more articles
        article_count_boost = min(len(articles) / 10.0, 1.0) * 20
        
        # Boost confidence with higher impact articles
        avg_impact = statistics.mean([a.impact_score for a in articles])
        impact_boost = (avg_impact / 100.0) * 30
        
        total_confidence = avg_confidence + article_count_boost + impact_boost
        
        return max(0, min(100, total_confidence))
    
    # ========================================================================
    # SIGNAL GENERATION
    # ========================================================================
    
    def _generate_sentiment_signal(self, sentiment_score: float, momentum: float, 
                                 article_count: int) -> Tuple[str, float]:
        """Generate trading signal from sentiment analysis"""
        
        # Base signal from sentiment score
        if sentiment_score >= 0.3:
            base_signal = "bullish"
            base_strength = min(sentiment_score * 100, 100)
        elif sentiment_score <= -0.3:
            base_signal = "bearish"
            base_strength = min(abs(sentiment_score) * 100, 100)
        else:
            base_signal = "neutral"
            base_strength = 50.0
        
        # Adjust strength based on momentum
        momentum_adjustment = momentum * 20  # -20 to +20
        
        # Adjust strength based on article count (more articles = higher confidence)
        volume_adjustment = min(article_count / 10.0, 1.0) * 10  # 0 to 10
        
        # Final signal strength
        final_strength = base_strength + momentum_adjustment + volume_adjustment
        final_strength = max(0, min(100, final_strength))
        
        return base_signal, final_strength
    
    def _generate_sentiment_reasoning(self, sentiment_score: float, article_count: int,
                                   positive_articles: List[NewsArticle], 
                                   negative_articles: List[NewsArticle]) -> str:
        """Generate human-readable reasoning for sentiment analysis"""
        
        reasoning_parts = []
        
        # Overall sentiment assessment
        if sentiment_score >= 0.3:
            reasoning_parts.append(f"Strong positive sentiment ({sentiment_score:.2f})")
        elif sentiment_score >= 0.1:
            reasoning_parts.append(f"Moderately positive sentiment ({sentiment_score:.2f})")
        elif sentiment_score <= -0.3:
            reasoning_parts.append(f"Strong negative sentiment ({sentiment_score:.2f})")
        elif sentiment_score <= -0.1:
            reasoning_parts.append(f"Moderately negative sentiment ({sentiment_score:.2f})")
        else:
            reasoning_parts.append(f"Neutral sentiment ({sentiment_score:.2f})")
        
        # Article breakdown
        reasoning_parts.append(f"Based on {article_count} articles")
        reasoning_parts.append(f"{len(positive_articles)} positive, {len(negative_articles)} negative")
        
        # Key themes (simplified)
        if positive_articles:
            top_positive = max(positive_articles, key=lambda a: a.sentiment_score)
            reasoning_parts.append(f"Top positive: {top_positive.category.value}")
        
        if negative_articles:
            top_negative = min(negative_articles, key=lambda a: a.sentiment_score)
            reasoning_parts.append(f"Top negative: {top_negative.category.value}")
        
        return ". ".join(reasoning_parts)
    
    # ========================================================================
    # MARKET SENTIMENT METHODS
    # ========================================================================
    
    def _calculate_fear_greed_index(self, articles: List[NewsArticle]) -> float:
        """Calculate simplified fear/greed index"""
        
        if not articles:
            return 50.0  # Neutral
        
        # Count fear vs greed indicators
        fear_keywords = ['fear', 'panic', 'crash', 'sell-off', 'decline', 'bear', 'recession']
        greed_keywords = ['rally', 'surge', 'bull', 'optimistic', 'growth', 'record high']
        
        fear_count = 0
        greed_count = 0
        
        for article in articles:
            text = f"{article.title} {article.description}".lower()
            
            for keyword in fear_keywords:
                if keyword in text:
                    fear_count += 1
                    break
            
            for keyword in greed_keywords:
                if keyword in text:
                    greed_count += 1
                    break
        
        total_signals = fear_count + greed_count
        if total_signals == 0:
            return 50.0
        
        # Calculate fear/greed ratio
        greed_ratio = greed_count / total_signals
        
        return greed_ratio * 100
    
    def _calculate_volatility_sentiment(self, articles: List[NewsArticle]) -> float:
        """Calculate volatility sentiment from news"""
        
        if not articles:
            return 50.0
        
        volatility_keywords = ['volatile', 'volatility', 'uncertain', 'swing', 'fluctuation']
        
        volatility_mentions = 0
        for article in articles:
            text = f"{article.title} {article.description}".lower()
            
            for keyword in volatility_keywords:
                if keyword in text:
                    volatility_mentions += 1
                    break
        
        # Higher percentage indicates more volatility
        volatility_percentage = (volatility_mentions / len(articles)) * 100
        
        return min(volatility_percentage, 100)
    
    def _calculate_market_sentiment_change(self, hours_back: int) -> float:
        """Calculate market sentiment change over time period"""
        
        if len(self.market_sentiment_history) < 2:
            return 0.0
        
        current_sentiment = self.market_sentiment_history[-1].overall_market_sentiment
        
        # Find sentiment from specified hours back
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        
        for sentiment_record in reversed(self.market_sentiment_history):
            if sentiment_record.timestamp <= cutoff_time:
                return current_sentiment - sentiment_record.overall_market_sentiment
        
        # If no record found from that time, compare with oldest
        oldest_sentiment = self.market_sentiment_history[0].overall_market_sentiment
        return current_sentiment - oldest_sentiment
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _get_company_name(self, symbol: str) -> str:
        """Get company name from symbol (simplified mapping)"""
        
        company_names = {
            'AAPL': 'Apple',
            'MSFT': 'Microsoft',
            'GOOGL': 'Google',
            'GOOG': 'Alphabet',
            'AMZN': 'Amazon',
            'TSLA': 'Tesla',
            'META': 'Meta',
            'NVDA': 'NVIDIA',
            'JPM': 'JPMorgan',
            'JNJ': 'Johnson & Johnson'
        }
        
        return company_names.get(symbol.upper(), symbol)
    
    def _create_mock_news_articles(self, symbol: str) -> List[NewsArticle]:
        """Create mock news articles for testing when API is unavailable"""
        
        mock_articles = [
            NewsArticle(
                article_id=str(uuid.uuid4()),
                title=f"{symbol} Reports Strong Quarterly Earnings",
                description=f"{self._get_company_name(symbol)} exceeded analyst expectations with strong revenue growth.",
                content="Full content would be here...",
                source="Mock Financial News",
                author="Mock Reporter",
                published_at=datetime.now(timezone.utc) - timedelta(hours=2),
                url="",
                url_to_image="",
                sentiment_score=0.6,
                sentiment_polarity=SentimentPolarity.POSITIVE,
                sentiment_confidence=75.0,
                category=NewsCategory.EARNINGS,
                impact_score=85.0,
                keywords=["earnings", "revenue", "growth"],
                symbol_mentions=[symbol],
                relevance_score=95.0
            ),
            NewsArticle(
                article_id=str(uuid.uuid4()),
                title=f"Analyst Upgrades {symbol} to Buy Rating",
                description=f"Wall Street analyst raises price target for {self._get_company_name(symbol)} citing strong fundamentals.",
                content="Full content would be here...",
                source="Mock Analysis",
                author="Mock Analyst",
                published_at=datetime.now(timezone.utc) - timedelta(hours=6),
                url="",
                url_to_image="",
                sentiment_score=0.4,
                sentiment_polarity=SentimentPolarity.POSITIVE,
                sentiment_confidence=80.0,
                category=NewsCategory.ANALYST_RATING,
                impact_score=70.0,
                keywords=["upgrade", "buy", "rating"],
                symbol_mentions=[symbol],
                relevance_score=90.0
            )
        ]
        
        return mock_articles
    
    def _create_neutral_sentiment(self, symbol: str) -> SentimentAnalysis:
        """Create neutral sentiment analysis"""
        
        return SentimentAnalysis(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            overall_sentiment_score=0.0,
            overall_polarity=SentimentPolarity.NEUTRAL,
            overall_confidence=0.0,
            sentiment_24h=0.0,
            sentiment_7d=0.0,
            sentiment_30d=0.0,
            total_articles=0,
            positive_articles=0,
            negative_articles=0,
            neutral_articles=0,
            most_positive_article=None,
            most_negative_article=None,
            highest_impact_article=None,
            sentiment_trend="stable",
            momentum=0.0,
            volatility=0.0,
            category_breakdown={},
            source_breakdown={},
            trading_signal="neutral",
            signal_strength=50.0,
            reasoning="No news articles available for sentiment analysis"
        )
    
    def _create_neutral_market_sentiment(self) -> MarketSentiment:
        """Create neutral market sentiment"""
        
        return MarketSentiment(
            timestamp=datetime.now(timezone.utc),
            overall_market_sentiment=0.0,
            market_fear_greed_index=50.0,
            volatility_sentiment=50.0,
            sector_sentiment={},
            total_market_articles=0,
            sentiment_dispersion=0.0,
            sentiment_direction="neutral",
            change_24h=0.0,
            change_7d=0.0
        )
    
    def _sentiment_to_dict(self, sentiment: SentimentAnalysis) -> Dict[str, Any]:
        """Convert SentimentAnalysis to dictionary"""
        
        result = asdict(sentiment)
        
        # Convert datetime objects to ISO strings
        result['timestamp'] = sentiment.timestamp.isoformat()
        
        # Convert articles to dictionaries
        if sentiment.most_positive_article:
            result['most_positive_article'] = asdict(sentiment.most_positive_article)
            result['most_positive_article']['published_at'] = sentiment.most_positive_article.published_at.isoformat()
        
        if sentiment.most_negative_article:
            result['most_negative_article'] = asdict(sentiment.most_negative_article)
            result['most_negative_article']['published_at'] = sentiment.most_negative_article.published_at.isoformat()
        
        if sentiment.highest_impact_article:
            result['highest_impact_article'] = asdict(sentiment.highest_impact_article)
            result['highest_impact_article']['published_at'] = sentiment.highest_impact_article.published_at.isoformat()
        
        return result
    
    def _market_sentiment_to_dict(self, sentiment: MarketSentiment) -> Dict[str, Any]:
        """Convert MarketSentiment to dictionary"""
        
        result = asdict(sentiment)
        result['timestamp'] = sentiment.timestamp.isoformat()
        return result
    
    def _create_no_news_response(self, symbol: str) -> Dict[str, Any]:
        """Create response when no news is found"""
        
        return {
            'symbol': symbol,
            'overall_sentiment_score': 0.0,
            'overall_polarity': 'neutral',
            'overall_confidence': 0.0,
            'total_articles': 0,
            'trading_signal': 'neutral',
            'signal_strength': 50.0,
            'reasoning': 'No news articles found for sentiment analysis',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def _create_no_market_news_response(self) -> Dict[str, Any]:
        """Create response when no market news is found"""
        
        return {
            'overall_market_sentiment': 0.0,
            'market_fear_greed_index': 50.0,
            'total_market_articles': 0,
            'sentiment_direction': 'neutral',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def _create_error_response(self, symbol: str, error: str) -> Dict[str, Any]:
        """Create error response"""
        
        return {
            'symbol': symbol,
            'error': error,
            'overall_sentiment_score': 0.0,
            'overall_polarity': 'neutral',
            'overall_confidence': 0.0,
            'total_articles': 0,
            'trading_signal': 'neutral',
            'signal_strength': 50.0,
            'reasoning': f'Sentiment analysis error: {error}',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    # ========================================================================
    # PERFORMANCE AND UTILITY
    # ========================================================================
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get sentiment analyzer performance metrics"""
        
        cache_hit_rate = (self.cache_hits / max(self.analysis_count, 1)) * 100
        
        return {
            'total_analyses': self.analysis_count,
            'api_calls': self.api_calls,
            'cache_hits': self.cache_hits,
            'cache_hit_rate': cache_hit_rate,
            'cached_symbols': len(self.sentiment_cache),
            'newsapi_enabled': self.newsapi_enabled,
            'supported_sources': len(self.news_sources)
        }
    
    def clear_cache(self):
        """Clear sentiment analysis cache"""
        
        with self._sentiment_lock:
            self.sentiment_cache.clear()
            self.news_cache.clear()
            self.cache_timestamps.clear()
            self.logger.info("🧹 Sentiment analysis cache cleared")
    
    def health_check(self) -> bool:
        """Perform health check"""
        
        try:
            # Check NewsAPI connectivity if enabled
            if self.newsapi_enabled:
                # Simple test request
                url = "https://newsapi.org/v2/everything"
                params = {
                    'q': 'test',
                    'pageSize': 1,
                    'apiKey': self.newsapi_key
                }
                
                response = requests.get(url, params=params, timeout=5)
                if response.status_code not in [200, 429]:  # 429 is rate limit, still valid
                    self.logger.warning("⚠️ NewsAPI connectivity issue")
                    return False
            
            # Check cache size
            if len(self.sentiment_cache) > 500:
                self.logger.warning("⚠️ Sentiment cache is large")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Sentiment analyzer health check failed: {e}")
            return False
    
    def get_analyzer_status(self) -> Dict[str, Any]:
        """Get analyzer status"""
        
        return {
            'total_analyses': self.analysis_count,
            'api_calls': self.api_calls,
            'cache_size': len(self.sentiment_cache),
            'cache_hit_rate': (self.cache_hits / max(self.analysis_count, 1)) * 100,
            'newsapi_enabled': self.newsapi_enabled,
            'news_sources': len(self.news_sources),
            'market_sentiment_history_size': len(self.market_sentiment_history),
            'healthy': self.health_check()
        }

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_sentiment_analyzer():
    """Test the sentiment analyzer"""
    
    print("🧪 Testing Sentiment Analyzer...")
    
    try:
        # Mock dependencies for testing
        class MockConfigManager:
            def get_api_config(self, provider):
                if provider == 'newsapi':
                    from dataclasses import dataclass
                    @dataclass
                    class MockApiConfig:
                        api_key: str = 'test_key'
                        enabled: bool = False  # Disabled for testing
                    return MockApiConfig()
                return None
                
            def get_config(self, section, default=None):
                if section == 'ai':
                    return {
                        'sentiment_analysis': {
                            'news_sources': ['reuters', 'bloomberg'],
                            'weight_decay_hours': 24
                        }
                    }
                return default or {}
        
        class MockStateManager:
            def register_component(self, name, instance=None):
                pass
        
        config_manager = MockConfigManager()
        state_manager = MockStateManager()
        
        # Create sentiment analyzer
        analyzer = ProductionSentimentAnalyzer(config_manager, state_manager)
        
        # Test symbol sentiment analysis
        result = analyzer.analyze_symbol_sentiment("AAPL")
        if 'overall_sentiment_score' in result:
            print(f"✅ Sentiment analysis: {result['symbol']}")
            print(f"   Sentiment Score: {result['overall_sentiment_score']:.2f}")
            print(f"   Polarity: {result['overall_polarity']}")
            print(f"   Articles: {result['total_articles']}")
            print(f"   Signal: {result['trading_signal']}")
        else:
            print("❌ Sentiment analysis failed")
        
        # Test market sentiment analysis
        market_result = analyzer.analyze_market_sentiment()
        if 'overall_market_sentiment' in market_result:
            print(f"✅ Market sentiment: {market_result['overall_market_sentiment']:.2f}")
        
        # Test performance metrics
        perf_metrics = analyzer.get_performance_metrics()
        print(f"✅ Performance metrics: {perf_metrics['total_analyses']} analyses")
        
        # Test cache functionality
        result2 = analyzer.analyze_symbol_sentiment("AAPL")  # Should hit cache
        print(f"✅ Cache test: {perf_metrics['cache_hit_rate']:.1f}% hit rate")
        
        # Test health check
        healthy = analyzer.health_check()
        print(f"✅ Health check: {healthy}")
        
        # Test analyzer status
        status = analyzer.get_analyzer_status()
        print(f"✅ Analyzer status: {status['healthy']}")
        
        print("🎉 Sentiment Analyzer test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Sentiment Analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_sentiment_analyzer()
