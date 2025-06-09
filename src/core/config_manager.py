#!/usr/bin/env python3
"""
🔧 PRODUCTION TRADING SYSTEM - CONFIGURATION MANAGEMENT SYSTEM
src/core/config_manager.py

Enterprise-grade configuration management with comprehensive validation,
security controls, and environment-specific settings for the trading system.

Features:
- Complete environment variable validation using YOUR exact credentials
- Tier-based trading configuration (Blue Chip, Growth, Speculative)
- Risk management parameters and limits
- API configuration for Alpaca, Alpha Vantage, NewsAPI
- AWS services configuration (SNS, DynamoDB, CloudWatch)
- Security and compliance settings
- Performance optimization parameters

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import os
import json
import time
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timezone
import logging
import re
from decimal import Decimal

# ============================================================================
# CONFIGURATION ENUMS AND TYPES
# ============================================================================

class Environment(Enum):
    """Deployment environments"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

class TierCategory(Enum):
    """Stock tier categories for position allocation"""
    BLUE_CHIP = "blue_chip"        # Tier 1: 50-70% allocation
    GROWTH = "growth"              # Tier 2: 25-35% allocation  
    SPECULATIVE = "speculative"    # Tier 3: 5-15% allocation

class ApiProvider(Enum):
    """External API providers"""
    ALPACA = "alpaca"
    ALPHA_VANTAGE = "alpha_vantage"
    NEWSAPI = "newsapi"
    POLYGON = "polygon"
    FINHUB = "finhub"

@dataclass
class TierConfiguration:
    """Configuration for each stock tier"""
    name: str
    category: TierCategory
    min_allocation_percent: float
    max_allocation_percent: float
    max_position_size_percent: float
    min_position_size_percent: float
    symbols: List[str]
    hold_period_days: Tuple[int, int]  # (min, max)
    risk_level: str
    description: str

@dataclass
class ApiConfiguration:
    """API endpoint configuration"""
    provider: ApiProvider
    api_key: str
    secret_key: Optional[str]
    base_url: str
    timeout: int
    max_retries: int
    rate_limit_per_minute: int
    enabled: bool

@dataclass
class RiskLimits:
    """Risk management limits and thresholds"""
    max_portfolio_loss_percent: float
    max_daily_loss_percent: float
    max_drawdown_percent: float
    max_single_position_percent: float
    max_sector_concentration_percent: float
    min_cash_percent: float
    max_tier3_allocation_percent: float
    position_correlation_limit: float
    volatility_threshold: float
    beta_limit: float

@dataclass
class TradingHours:
    """Trading session configuration"""
    market_open_et: str      # "09:30"
    market_close_et: str     # "16:00"
    pre_market_start_et: str # "04:00"
    after_hours_end_et: str  # "20:00"
    trading_days: List[str]  # ["monday", "tuesday", ...]
    extended_hours_enabled: bool
    weekend_analysis_enabled: bool

# ============================================================================
# PRODUCTION CONFIGURATION MANAGER
# ============================================================================

class ProductionConfigManager:
    """
    Enterprise-grade configuration management system
    
    Handles all system configuration including:
    - Environment variables validation
    - Trading parameters and risk limits
    - API credentials and endpoints
    - AWS services configuration
    - Security and compliance settings
    """
    
    def __init__(self):
        self.logger = self._setup_logger()
        self.environment = Environment.PRODUCTION
        self.config_cache = {}
        self.validation_errors = []
        self.last_validated = None
        
        # Load and validate all configuration
        self._load_complete_configuration()
    
    def _setup_logger(self) -> logging.Logger:
        """Setup logger for configuration manager"""
        logger = logging.getLogger('trading_system.config_manager')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    def _load_complete_configuration(self):
        """Load and validate complete system configuration"""
        
        self.logger.info("🔧 Loading production configuration with YOUR exact credentials...")
        
        try:
            # Step 1: Validate environment
            self._validate_environment()
            
            # Step 2: Load trading configuration
            self._load_trading_configuration()
            
            # Step 3: Load API configurations
            self._load_api_configurations()
            
            # Step 4: Load AWS configuration
            self._load_aws_configuration()
            
            # Step 5: Load risk management configuration
            self._load_risk_configuration()
            
            # Step 6: Load AI/ML configuration
            self._load_ai_configuration()
            
            # Step 7: Load system configuration
            self._load_system_configuration()
            
            # Step 8: Load tier configurations
            self._load_tier_configurations()
            
            # Step 9: Final validation
            self._validate_complete_configuration()
            
            self.last_validated = datetime.now(timezone.utc)
            
            self.logger.info("✅ Production configuration loaded successfully",
                           extra={
                               'environment': self.environment.value,
                               'trading_enabled': self.config_cache.get('trading', {}).get('enabled', False),
                               'apis_configured': len([k for k in self.config_cache.keys() if k.endswith('_api')]),
                               'validation_time': self.last_validated.isoformat()
                           })
            
        except Exception as e:
            self.logger.critical(f"❌ Configuration loading failed: {e}")
            raise ConfigurationError(f"Failed to load configuration: {e}")
    
    def _validate_environment(self):
        """Validate environment and required variables"""
        
        # Required environment variables with YOUR exact values
        required_vars = {
            # Alpaca Trading API (YOUR EXACT CREDENTIALS)
            'ALPACA_API_KEY': 'PKTGTBUDLQ3V9XFHTBHA',
            'ALPACA_SECRET_KEY': 'PSOdtqJ5PQAk7Up76ZPSHd1km5NDC9f74YHX6bvK',
            'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets',
            
            # Market Data APIs (YOUR EXACT CREDENTIALS)
            'ALPHA_VANTAGE_KEY': 'W81PG6O5UI6Q720I',
            'NEWSAPI_KEY': '7cbc465672f44938a3c7f3ad20809d9e',
            
            # AWS Services (YOUR EXACT CONFIGURATION)
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:826564544834:trading-system-alerts',
            'SIGNALS_TABLE': 'trading-signals',
            'PERFORMANCE_TABLE': 'trading-performance',
            'PORTFOLIO_TABLE': 'trading-system-portfolio',
            
            # System Configuration
            'ENVIRONMENT': 'production',
            'TRADING_ENABLED': 'true',
            'NOTIFICATION_EMAIL': 'rkong@armku.us'
        }
        
        # Validate each required variable
        missing_vars = []
        mismatched_vars = []
        
        for var_name, expected_value in required_vars.items():
            actual_value = os.environ.get(var_name, '').strip()
            
            if not actual_value:
                missing_vars.append(var_name)
            elif var_name not in ['ALPACA_SECRET_KEY'] and actual_value != expected_value:
                # Don't log secret key mismatches for security
                mismatched_vars.append({
                    'variable': var_name,
                    'expected': expected_value,
                    'actual': actual_value
                })
        
        # Check for critical errors
        if missing_vars:
            raise ConfigurationError(f"Missing required environment variables: {missing_vars}")
        
        if mismatched_vars:
            self.logger.warning("⚠️ Environment variable mismatches detected",
                              extra={'mismatches': mismatched_vars})
        
        # Set environment
        env_value = os.environ.get('ENVIRONMENT', 'production').lower()
        if env_value in [e.value for e in Environment]:
            self.environment = Environment(env_value)
        else:
            self.logger.warning(f"⚠️ Unknown environment '{env_value}', defaulting to production")
            self.environment = Environment.PRODUCTION
        
        self.logger.info(f"✅ Environment validation completed: {self.environment.value}")
    
    def _load_trading_configuration(self):
        """Load comprehensive trading configuration"""
        
        self.config_cache['trading'] = {
            # Core trading settings
            'enabled': os.environ.get('TRADING_ENABLED', 'false').lower() == 'true',
            'environment': self.environment.value,
            'paper_trading': True,  # Always paper trading for safety
            'extended_hours': os.environ.get('EXTENDED_HOURS', 'TRUE').lower() == 'true',
            
            # Position and risk settings
            'max_concurrent_trades': int(os.environ.get('MAX_CONCURRENT_TRADES', '5')),
            'max_position_size_percent': float(os.environ.get('MAX_POSITION_SIZE', '0.12')),
            'min_confidence_threshold': float(os.environ.get('MIN_CONFIDENCE', '70.0')),
            'rebalance_threshold_percent': 0.05,  # 5% drift triggers rebalance
            
            # Trading hours
            'hours': TradingHours(
                market_open_et="09:30",
                market_close_et="16:00", 
                pre_market_start_et="04:00",
                after_hours_end_et="20:00",
                trading_days=["monday", "tuesday", "wednesday", "thursday", "friday"],
                extended_hours_enabled=os.environ.get('EXTENDED_HOURS', 'TRUE').lower() == 'true',
                weekend_analysis_enabled=True
            ),
            
            # Execution settings
            'order_timeout_seconds': int(os.environ.get('ORDER_TIMEOUT', '300')),
            'slippage_tolerance_percent': 0.002,  # 0.2% slippage tolerance
            'partial_fill_threshold_percent': 0.95,  # Accept 95%+ fills
            
            # Strategy settings
            'strategy_weights': {
                'momentum': 0.30,
                'mean_reversion': 0.25,
                'trend_following': 0.25,
                'sentiment_driven': 0.20
            }
        }
        
        self.logger.info("✅ Trading configuration loaded",
                        extra={
                            'trading_enabled': self.config_cache['trading']['enabled'],
                            'paper_trading': self.config_cache['trading']['paper_trading'],
                            'extended_hours': self.config_cache['trading']['extended_hours']
                        })
    
    def _load_api_configurations(self):
        """Load all API configurations with YOUR exact credentials"""
        
        # Alpaca Trading API Configuration
        self.config_cache['alpaca_api'] = ApiConfiguration(
            provider=ApiProvider.ALPACA,
            api_key=os.environ.get('ALPACA_API_KEY', 'PKTGTBUDLQ3V9XFHTBHA'),
            secret_key=os.environ.get('ALPACA_SECRET_KEY', 'PSOdtqJ5PQAk7Up76ZPSHd1km5NDC9f74YHX6bvK'),
            base_url=os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets'),
            timeout=int(os.environ.get('ALPACA_TIMEOUT', '30')),
            max_retries=int(os.environ.get('ALPACA_MAX_RETRIES', '3')),
            rate_limit_per_minute=200,  # Alpaca limit
            enabled=True
        )
        
        # Alpha Vantage API Configuration
        self.config_cache['alpha_vantage_api'] = ApiConfiguration(
            provider=ApiProvider.ALPHA_VANTAGE,
            api_key=os.environ.get('ALPHA_VANTAGE_KEY', 'W81PG6O5UI6Q720I'),
            secret_key=None,
            base_url='https://www.alphavantage.co/query',
            timeout=int(os.environ.get('ALPHA_VANTAGE_TIMEOUT', '15')),
            max_retries=3,
            rate_limit_per_minute=5,  # Alpha Vantage free tier limit
            enabled=bool(os.environ.get('ALPHA_VANTAGE_KEY'))
        )
        
        # NewsAPI Configuration
        self.config_cache['newsapi_api'] = ApiConfiguration(
            provider=ApiProvider.NEWSAPI,
            api_key=os.environ.get('NEWSAPI_KEY', '7cbc465672f44938a3c7f3ad20809d9e'),
            secret_key=None,
            base_url='https://newsapi.org/v2',
            timeout=10,
            max_retries=3,
            rate_limit_per_minute=1000,  # NewsAPI limit
            enabled=bool(os.environ.get('NEWSAPI_KEY'))
        )
        
        # Additional market data sources (optional)
        self.config_cache['polygon_api'] = ApiConfiguration(
            provider=ApiProvider.POLYGON,
            api_key=os.environ.get('POLYGON_API_KEY', ''),
            secret_key=None,
            base_url='https://api.polygon.io',
            timeout=15,
            max_retries=3,
            rate_limit_per_minute=100,
            enabled=bool(os.environ.get('POLYGON_API_KEY'))
        )
        
        self.config_cache['finhub_api'] = ApiConfiguration(
            provider=ApiProvider.FINHUB,
            api_key=os.environ.get('FINHUB_API_KEY', ''),
            secret_key=None,
            base_url='https://finnhub.io/api/v1',
            timeout=10,
            max_retries=3,
            rate_limit_per_minute=60,
            enabled=bool(os.environ.get('FINHUB_API_KEY'))
        )
        
        # Log API configuration status
        enabled_apis = [
            api_name.replace('_api', '') for api_name, config in self.config_cache.items()
            if api_name.endswith('_api') and config.enabled
        ]
        
        self.logger.info("✅ API configurations loaded",
                        extra={
                            'enabled_apis': enabled_apis,
                            'total_apis_configured': len(enabled_apis)
                        })
    
    def _load_aws_configuration(self):
        """Load AWS services configuration"""
        
        self.config_cache['aws'] = {
            # Core AWS settings
            'region': os.environ.get('AWS_REGION', 'us-east-1'),
            'account_id': '826564544834',  # Extracted from your SNS ARN
            
            # DynamoDB tables (YOUR exact table names)
            'dynamodb': {
                'signals_table': os.environ.get('SIGNALS_TABLE', 'trading-signals'),
                'performance_table': os.environ.get('PERFORMANCE_TABLE', 'trading-performance'),
                'portfolio_table': os.environ.get('PORTFOLIO_TABLE', 'trading-system-portfolio'),
                'positions_table': 'trading-positions',
                'orders_table': 'trading-orders',
                'alerts_table': 'trading-alerts',
                'read_capacity': 5,
                'write_capacity': 5,
                'backup_enabled': True
            },
            
            # SNS notifications (YOUR exact topic ARN)
            'sns': {
                'topic_arn': os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:us-east-1:826564544834:trading-system-alerts'),
                'email_endpoint': os.environ.get('NOTIFICATION_EMAIL', 'rkong@armku.us'),
                'critical_topic_arn': os.environ.get('SNS_CRITICAL_TOPIC_ARN', ''),
                'enable_sms': False,  # Email only for now
                'delivery_delay_seconds': 0
            },
            
            # CloudWatch monitoring
            'cloudwatch': {
                'namespace': 'TradingSystem/Production',
                'metric_resolution': 60,  # 1 minute resolution
                'retention_days': 90,
                'dashboard_enabled': True,
                'custom_metrics': [
                    'PortfolioValue', 'DailyReturn', 'TradesExecuted',
                    'AlertsGenerated', 'SystemHealth', 'ApiLatency'
                ]
            },
            
            # S3 storage (optional)
            's3': {
                'bucket_name': os.environ.get('S3_BUCKET', ''),
                'reports_prefix': 'trading-reports/',
                'backups_prefix': 'trading-backups/', 
                'encryption_enabled': True,
                'lifecycle_enabled': True
            },
            
            # Lambda configuration
            'lambda': {
                'function_name': os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'trading-system-engine'),
                'timeout': int(os.environ.get('LAMBDA_TIMEOUT', '300')),
                'memory_size': int(os.environ.get('LAMBDA_MEMORY', '512')),
                'reserved_concurrency': 3,
                'dead_letter_queue_enabled': True
            },
            
            # Security settings
            'security': {
                'kms_key_id': os.environ.get('KMS_KEY_ID', ''),
                'encrypt_at_rest': True,
                'encrypt_in_transit': True,
                'secrets_manager_enabled': False,  # Using env vars for now
                'vpc_enabled': False  # Public Lambda for now
            }
        }
        
        self.logger.info("✅ AWS configuration loaded",
                        extra={
                            'region': self.config_cache['aws']['region'],
                            'dynamodb_tables': len(self.config_cache['aws']['dynamodb']) - 3,  # Exclude config keys
                            'sns_enabled': bool(self.config_cache['aws']['sns']['topic_arn']),
                            'cloudwatch_enabled': self.config_cache['aws']['cloudwatch']['dashboard_enabled']
                        })
    
    def _load_risk_configuration(self):
        """Load comprehensive risk management configuration"""
        
        self.config_cache['risk'] = RiskLimits(
            # Portfolio-level risk limits
            max_portfolio_loss_percent=float(os.environ.get('MAX_PORTFOLIO_LOSS', '5.0')),
            max_daily_loss_percent=float(os.environ.get('MAX_DAILY_LOSS', '2.0')),
            max_drawdown_percent=float(os.environ.get('MAX_DRAWDOWN', '15.0')),
            
            # Position-level risk limits
            max_single_position_percent=float(os.environ.get('MAX_POSITION_SIZE', '12.0')),
            max_sector_concentration_percent=float(os.environ.get('MAX_SECTOR_CONCENTRATION', '30.0')),
            max_tier3_allocation_percent=float(os.environ.get('MAX_TIER3_ALLOCATION', '15.0')),
            
            # Cash and liquidity requirements
            min_cash_percent=float(os.environ.get('MIN_CASH_PERCENT', '3.0')),
            
            # Correlation and volatility limits
            position_correlation_limit=float(os.environ.get('MAX_CORRELATION', '0.8')),
            volatility_threshold=float(os.environ.get('VOLATILITY_THRESHOLD', '0.3')),
            beta_limit=float(os.environ.get('MAX_BETA', '2.0'))
        )
        
        # Additional risk settings
        self.config_cache['risk_settings'] = {
            'stop_loss_enabled': True,
            'dynamic_stop_loss': True,
            'stop_loss_base_percent': 8.0,
            'stop_loss_volatility_multiplier': 1.5,
            'profit_taking_enabled': True,
            'profit_taking_threshold_percent': 20.0,
            'circuit_breaker_enabled': True,
            'circuit_breaker_threshold_percent': 7.0,
            'emergency_liquidation_enabled': True,
            'position_sizing_method': 'kelly_criterion',
            'kelly_fraction_limit': 0.25,
            'var_calculation_days': 252,
            'var_confidence_level': 0.05
        }
        
        self.logger.info("✅ Risk configuration loaded",
                        extra={
                            'max_portfolio_loss': self.config_cache['risk'].max_portfolio_loss_percent,
                            'max_position_size': self.config_cache['risk'].max_single_position_percent,
                            'circuit_breaker_enabled': self.config_cache['risk_settings']['circuit_breaker_enabled']
                        })
    
    def _load_ai_configuration(self):
        """Load AI/ML configuration and weights"""
        
        self.config_cache['ai'] = {
            # Core AI settings
            'enabled': True,
            'model_version': '1.0.0',
            'update_frequency': 'daily',
            
            # Decision engine weights (must sum to 1.0)
            'analysis_weights': {
                'technical_analysis': 0.35,
                'fundamental_analysis': 0.25,
                'sentiment_analysis': 0.20,
                'risk_analysis': 0.15,
                'portfolio_fit': 0.05
            },
            
            # Confidence thresholds
            'confidence_thresholds': {
                'execute_immediately': 90.0,
                'execute_reduced_size': 80.0,
                'execute_small_size': 70.0,
                'monitor_only': 60.0,
                'ignore_signal': 50.0
            },
            
            # Technical analysis settings
            'technical_analysis': {
                'indicators': [
                    'rsi', 'macd', 'bollinger_bands', 'stochastic',
                    'williams_r', 'atr', 'cci', 'momentum',
                    'roc', 'ema_cross', 'sma_cross', 'vwap'
                ],
                'timeframes': ['1min', '5min', '15min', '1hour', '1day'],
                'lookback_periods': {
                    'short': 14,
                    'medium': 50,
                    'long': 200
                }
            },
            
            # Sentiment analysis settings
            'sentiment_analysis': {
                'news_sources': [
                    'reuters', 'bloomberg', 'cnbc', 'marketwatch',
                    'yahoo-finance', 'seeking-alpha'
                ],
                'sentiment_models': ['vader', 'textblob', 'finbert'],
                'weight_decay_hours': 24,
                'social_media_enabled': False,  # Future enhancement
                'analyst_ratings_weight': 0.3
            },
            
            # Fundamental analysis settings
            'fundamental_analysis': {
                'metrics': [
                    'pe_ratio', 'peg_ratio', 'debt_to_equity',
                    'roe', 'roa', 'revenue_growth', 'eps_growth',
                    'free_cash_flow', 'current_ratio', 'quick_ratio'
                ],
                'sector_comparison_enabled': True,
                'peer_analysis_enabled': True,
                'earnings_calendar_weight': 0.2
            },
            
            # Machine learning settings
            'ml_models': {
                'ensemble_enabled': True,
                'models': ['random_forest', 'gradient_boost', 'neural_network'],
                'feature_selection': 'auto',
                'retraining_frequency': 'weekly',
                'validation_split': 0.2,
                'cross_validation_folds': 5
            }
        }
        
        # Validate weights sum to 1.0
        total_weight = sum(self.config_cache['ai']['analysis_weights'].values())
        if abs(total_weight - 1.0) > 0.001:
            raise ConfigurationError(f"AI analysis weights must sum to 1.0, got {total_weight}")
        
        self.logger.info("✅ AI configuration loaded",
                        extra={
                            'ai_enabled': self.config_cache['ai']['enabled'],
                            'technical_indicators': len(self.config_cache['ai']['technical_analysis']['indicators']),
                            'sentiment_sources': len(self.config_cache['ai']['sentiment_analysis']['news_sources'])
                        })
    
    def _load_system_configuration(self):
        """Load system and performance configuration"""
        
        self.config_cache['system'] = {
            # Core system settings
            'log_level': os.environ.get('LOG_LEVEL', 'INFO'),
            'debug_mode': os.environ.get('DEBUG_MODE', 'false').lower() == 'true',
            'notification_email': os.environ.get('NOTIFICATION_EMAIL', 'rkong@armku.us'),
            
            # Performance settings
            'cache_ttl_seconds': int(os.environ.get('CACHE_TTL', '300')),
            'max_execution_time_seconds': int(os.environ.get('LAMBDA_TIMEOUT', '270')),
            'timeout_buffer_seconds': 30,
            'health_check_interval_seconds': 300,
            
            # Data retention settings
            'signal_retention_days': 90,
            'performance_retention_days': 365,
            'log_retention_days': 90,
            'order_history_retention_days': 365,
            
            # Alert and notification settings
            'email_notifications': {
                'enabled': True,
                'daily_summary': True,
                'trade_confirmations': True,
                'risk_alerts': True,
                'system_alerts': True,
                'performance_reports': True,
                'weekly_reports': True,
                'monthly_reports': True
            },
            
            # API rate limiting
            'rate_limiting': {
                'enabled': True,
                'global_rate_limit': 1000,  # requests per minute
                'per_api_limits': {
                    'alpaca': 200,
                    'alpha_vantage': 5,
                    'newsapi': 1000,
                    'polygon': 100
                }
            },
            
            # Monitoring and health checks
            'monitoring': {
                'enabled': True,
                'metrics_collection': True,
                'performance_profiling': False,  # Disable in production
                'error_tracking': True,
                'uptime_monitoring': True
            }
        }
        
        self.logger.info("✅ System configuration loaded",
                        extra={
                            'debug_mode': self.config_cache['system']['debug_mode'],
                            'cache_ttl': self.config_cache['system']['cache_ttl_seconds'],
                            'email_notifications': self.config_cache['system']['email_notifications']['enabled']
                        })
    
    def _load_tier_configurations(self):
        """Load stock tier configurations for position allocation"""
        
        # Tier 1: Blue Chip Stocks (50-70% allocation)
        tier1_config = TierConfiguration(
            name="Blue Chip",
            category=TierCategory.BLUE_CHIP,
            min_allocation_percent=50.0,
            max_allocation_percent=70.0,
            max_position_size_percent=12.0,
            min_position_size_percent=4.0,
            symbols=[
                'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'JPM', 'JNJ', 'PG', 'KO',
                'PFE', 'XOM', 'BAC', 'WMT', 'HD', 'UNH', 'MA', 'DIS', 'ADBE',
                'CRM', 'NFLX', 'PYPL', 'INTC', 'CSCO', 'VZ', 'MRK', 'ABT', 'TMO'
            ],
            hold_period_days=(90, 180),  # 3-6 months
            risk_level="Low",
            description="Large-cap, established companies with stable earnings and dividends"
        )
        
        # Tier 2: Growth Stocks (25-35% allocation)
        tier2_config = TierConfiguration(
            name="Growth",
            category=TierCategory.GROWTH,
            min_allocation_percent=25.0,
            max_allocation_percent=35.0,
            max_position_size_percent=8.0,
            min_position_size_percent=2.0,
            symbols=[
                'NVDA', 'AMD', 'TSLA', 'META', 'V', 'AVGO', 'ORCL', 'SALESFORCE',
                'UBER', 'LYFT', 'SQ', 'ROKU', 'ZOOM', 'DOCU', 'SNOW', 'PLTR',
                'AI', 'RBLX', 'COIN', 'SHOP', 'TWLO', 'OKTA', 'ZS', 'CRWD'
            ],
            hold_period_days=(30, 90),  # 1-3 months
            risk_level="Medium",
            description="High-growth companies with strong fundamentals and market expansion"
        )
        
        # Tier 3: Speculative Stocks (5-15% allocation)
        tier3_config = TierConfiguration(
            name="Speculative",
            category=TierCategory.SPECULATIVE,
            min_allocation_percent=5.0,
            max_allocation_percent=15.0,
            max_position_size_percent=4.0,
            min_position_size_percent=0.5,
            symbols=[
                'SPCE', 'OPEN', 'SOFI', 'HOOD', 'RIVN', 'LCID', 'NKLA', 'WISH',
                'CLOV', 'BB', 'NOK', 'SNDL', 'TLRY', 'CGC', 'ACB', 'HEXO',
                'PLUG', 'FCEL', 'BLNK', 'CHPT', 'QS', 'RIDE', 'WKHS', 'HYLN'
            ],
            hold_period_days=(7, 30),  # 1-4 weeks
            risk_level="High",
            description="High-risk, high-reward opportunities including emerging sectors"
        )
        
        self.config_cache['tiers'] = {
            'tier_1': tier1_config,
            'tier_2': tier2_config,
            'tier_3': tier3_config
        }
        
        # Sector allocation guidelines
        self.config_cache['sectors'] = {
            'technology': {'max_percent': 35.0, 'symbols': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA']},
            'healthcare': {'max_percent': 20.0, 'symbols': ['JNJ', 'PFE', 'UNH', 'ABT', 'TMO']},
            'financial': {'max_percent': 20.0, 'symbols': ['JPM', 'BAC', 'MA', 'V', 'GS']},
            'consumer_discretionary': {'max_percent': 15.0, 'symbols': ['AMZN', 'TSLA', 'HD', 'DIS', 'NKE']},
            'consumer_staples': {'max_percent': 10.0, 'symbols': ['PG', 'KO', 'WMT', 'PEP', 'CL']},
            'energy': {'max_percent': 10.0, 'symbols': ['XOM', 'CVX', 'COP', 'EOG', 'SLB']},
            'industrials': {'max_percent': 10.0, 'symbols': ['CAT', 'BA', 'GE', 'MMM', 'HON']},
            'utilities': {'max_percent': 5.0, 'symbols': ['NEE', 'DUK', 'SO', 'D', 'EXC']},
            'materials': {'max_percent': 5.0, 'symbols': ['LIN', 'APD', 'ECL', 'DD', 'DOW']},
            'real_estate': {'max_percent': 5.0, 'symbols': ['AMT', 'PLD', 'CCI', 'EQIX', 'PSA']}
        }
        
        self.logger.info("✅ Tier configurations loaded",
                        extra={
                            'tier_1_symbols': len(tier1_config.symbols),
                            'tier_2_symbols': len(tier2_config.symbols),
                            'tier_3_symbols': len(tier3_config.symbols),
                            'sectors_configured': len(self.config_cache['sectors'])
                        })
    
    def _validate_complete_configuration(self):
        """Perform final validation of complete configuration"""
        
        validation_errors = []
        
        # Validate tier allocations sum correctly
        total_min = sum([
            tier.min_allocation_percent 
            for tier in self.config_cache['tiers'].values()
        ])
        total_max = sum([
            tier.max_allocation_percent 
            for tier in self.config_cache['tiers'].values()
        ])
        
        if total_min > 100.0:
            validation_errors.append(f"Minimum tier allocations exceed 100%: {total_min}")
        
        if total_max < 100.0:
            validation_errors.append(f"Maximum tier allocations below 100%: {total_max}")
        
        # Validate sector allocations
        total_sector_max = sum([
            sector['max_percent'] 
            for sector in self.config_cache['sectors'].values()
        ])
        
        if total_sector_max < 100.0:
            validation_errors.append(f"Sector allocations don't cover 100%: {total_sector_max}")
        
        # Validate API credentials
        critical_apis = ['alpaca_api', 'alpha_vantage_api', 'newsapi_api']
        for api_name in critical_apis:
            api_config = self.config_cache.get(api_name)
            if not api_config or not api_config.api_key:
                validation_errors.append(f"Missing API key for {api_name}")
        
        # Validate risk limits
        risk_config = self.config_cache['risk']
        if risk_config.max_single_position_percent > 20.0:
            validation_errors.append("Single position limit too high (>20%)")
        
        if risk_config.min_cash_percent < 1.0:
            validation_errors.append("Minimum cash too low (<1%)")
        
        # Log validation results
        if validation_errors:
            self.validation_errors = validation_errors
            self.logger.error("❌ Configuration validation failed",
                            extra={'validation_errors': validation_errors})
            raise ConfigurationError(f"Configuration validation failed: {validation_errors}")
        
        self.logger.info("✅ Complete configuration validation passed")
    
    # ========================================================================
    # PUBLIC INTERFACE METHODS
    # ========================================================================
    
    def get_config(self, section: str, key: str = None, default=None):
        """
        Get configuration value(s)
        
        Args:
            section: Configuration section name
            key: Optional specific key within section
            default: Default value if not found
            
        Returns:
            Configuration value or section
        """
        
        if section not in self.config_cache:
            self.logger.warning(f"⚠️ Configuration section not found: {section}")
            return default
        
        if key is None:
            return self.config_cache[section]
        
        if hasattr(self.config_cache[section], key):
            return getattr(self.config_cache[section], key)
        elif isinstance(self.config_cache[section], dict):
            return self.config_cache[section].get(key, default)
        else:
            return default
    
    def get_api_config(self, provider: str) -> Optional[ApiConfiguration]:
        """Get API configuration for specific provider"""
        api_key = f"{provider}_api"
        return self.config_cache.get(api_key)
    
    def get_tier_config(self, tier_name: str) -> Optional[TierConfiguration]:
        """Get tier configuration"""
        return self.config_cache.get('tiers', {}).get(tier_name)
    
    def get_risk_limits(self) -> RiskLimits:
        """Get risk management limits"""
        return self.config_cache['risk']
    
    def is_trading_enabled(self) -> bool:
        """Check if trading is enabled"""
        return self.config_cache.get('trading', {}).get('enabled', False)
    
    def is_market_hours(self) -> bool:
        """Check if currently in market hours"""
        # TODO: Implement market hours check logic
        # This would check current time against trading hours configuration
        return True  # Placeholder
    
    def get_symbol_tier(self, symbol: str) -> Optional[str]:
        """Get tier for a specific symbol"""
        for tier_name, tier_config in self.config_cache.get('tiers', {}).items():
            if symbol.upper() in [s.upper() for s in tier_config.symbols]:
                return tier_name
        return None
    
    def validate_position_size(self, symbol: str, size_percent: float) -> bool:
        """Validate if position size is within limits"""
        tier_name = self.get_symbol_tier(symbol)
        if not tier_name:
            return False
        
        tier_config = self.get_tier_config(tier_name)
        if not tier_config:
            return False
        
        return (tier_config.min_position_size_percent <= 
                size_percent <= 
                tier_config.max_position_size_percent)
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get summary of current configuration"""
        return {
            'environment': self.environment.value,
            'last_validated': self.last_validated.isoformat() if self.last_validated else None,
            'trading_enabled': self.is_trading_enabled(),
            'validation_errors': len(self.validation_errors),
            'sections_loaded': list(self.config_cache.keys()),
            'api_providers_enabled': [
                provider.replace('_api', '') 
                for provider in self.config_cache.keys() 
                if provider.endswith('_api') and self.config_cache[provider].enabled
            ],
            'tier_symbols_total': sum([
                len(tier.symbols) 
                for tier in self.config_cache.get('tiers', {}).values()
            ])
        }

# ============================================================================
# CONFIGURATION EXCEPTIONS
# ============================================================================

class ConfigurationError(Exception):
    """Configuration-related errors"""
    pass

class ValidationError(Exception):
    """Configuration validation errors"""
    pass

# ============================================================================
# TESTING AND VALIDATION UTILITIES
# ============================================================================

def test_configuration_manager():
    """Test the configuration manager"""
    
    print("🧪 Testing Configuration Manager...")
    
    try:
        # Create configuration manager
        config_manager = ProductionConfigManager()
        
        # Test basic functionality
        trading_config = config_manager.get_config('trading')
        print(f"✅ Trading enabled: {trading_config.get('enabled')}")
        
        # Test API configurations
        alpaca_config = config_manager.get_api_config('alpaca')
        print(f"✅ Alpaca API configured: {alpaca_config.enabled if alpaca_config else False}")
        
        # Test tier configurations
        tier1_config = config_manager.get_tier_config('tier_1')
        print(f"✅ Tier 1 symbols: {len(tier1_config.symbols) if tier1_config else 0}")
        
        # Test symbol lookup
        symbol_tier = config_manager.get_symbol_tier('AAPL')
        print(f"✅ AAPL tier: {symbol_tier}")
        
        # Test validation
        valid_size = config_manager.validate_position_size('AAPL', 8.0)
        print(f"✅ AAPL 8% position valid: {valid_size}")
        
        # Test summary
        summary = config_manager.get_configuration_summary()
        print(f"✅ Configuration summary: {summary['sections_loaded']}")
        
        print("🎉 Configuration Manager test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Configuration Manager test failed: {e}")
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_configuration_manager()
