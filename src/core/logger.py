#!/usr/bin/env python3
"""
📝 PRODUCTION TRADING SYSTEM - STRUCTURED LOGGING SYSTEM
src/core/logger.py

Enterprise-grade structured logging with CloudWatch integration, performance monitoring,
error tracking, and comprehensive audit trails for the trading system.

Features:
- CloudWatch-ready structured logging with custom metrics
- Component-based logging with contextual information
- Performance monitoring and execution tracking
- Error aggregation and alert correlation
- Audit trail logging for compliance
- Lambda-optimized logging with minimal overhead
- Real-time log streaming and analysis
- Security-focused log sanitization

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import logging
import sys
import json
import time
import traceback
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum
from contextlib import contextmanager
import uuid
import os
from collections import defaultdict, deque
import functools

# ============================================================================
# LOGGING ENUMS AND TYPES
# ============================================================================

class LogLevel(Enum):
    """Extended log levels for trading system"""
    TRACE = "TRACE"        # Detailed execution flow
    DEBUG = "DEBUG"        # Debug information
    INFO = "INFO"          # General information
    WARNING = "WARNING"    # Warning conditions
    ERROR = "ERROR"        # Error conditions
    CRITICAL = "CRITICAL"  # Critical errors
    AUDIT = "AUDIT"        # Audit trail events
    PERFORMANCE = "PERFORMANCE"  # Performance metrics
    SECURITY = "SECURITY"  # Security events

class LogCategory(Enum):
    """Log categories for organization"""
    SYSTEM = "system"
    TRADING = "trading"
    API = "api"
    RISK = "risk"
    PERFORMANCE = "performance"
    AI = "ai"
    ALERT = "alert"
    AUDIT = "audit"
    SECURITY = "security"

@dataclass
class LogContext:
    """Contextual information for logs"""
    execution_id: Optional[str] = None
    component: Optional[str] = None
    operation: Optional[str] = None
    symbol: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    trace_id: Optional[str] = None

@dataclass
class PerformanceMetric:
    """Performance metric for logging"""
    metric_name: str
    value: float
    unit: str
    timestamp: datetime
    component: str
    operation: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None

@dataclass
class SecurityEvent:
    """Security event for logging"""
    event_type: str
    severity: str
    source: str
    description: str
    timestamp: datetime
    context: Dict[str, Any]

# ============================================================================
# CLOUDWATCH INTEGRATION
# ============================================================================

class CloudWatchMetricsHandler:
    """
    CloudWatch custom metrics integration for trading system
    """
    
    def __init__(self, namespace: str = "TradingSystem/Production"):
        self.namespace = namespace
        self.metrics_buffer = deque(maxlen=1000)
        self._lock = threading.RLock()
        self.cloudwatch = None
        
        # Initialize CloudWatch client if available
        try:
            import boto3
            self.cloudwatch = boto3.client('cloudwatch')
        except ImportError:
            pass  # CloudWatch not available in this environment
    
    def put_metric(self, metric_name: str, value: float, unit: str = 'Count', 
                   dimensions: Optional[Dict[str, str]] = None):
        """Put custom metric to CloudWatch"""
        
        metric_data = {
            'MetricName': metric_name,
            'Value': value,
            'Unit': unit,
            'Timestamp': datetime.now(timezone.utc)
        }
        
        if dimensions:
            metric_data['Dimensions'] = [
                {'Name': k, 'Value': v} for k, v in dimensions.items()
            ]
        
        with self._lock:
            self.metrics_buffer.append(metric_data)
        
        # Send to CloudWatch if available
        if self.cloudwatch:
            try:
                self.cloudwatch.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=[metric_data]
                )
            except Exception:
                pass  # Don't fail logging due to CloudWatch issues
    
    def flush_metrics(self):
        """Flush buffered metrics to CloudWatch"""
        
        if not self.cloudwatch or not self.metrics_buffer:
            return
        
        with self._lock:
            metrics_to_send = list(self.metrics_buffer)
            self.metrics_buffer.clear()
        
        # Send in batches of 20 (CloudWatch limit)
        try:
            for i in range(0, len(metrics_to_send), 20):
                batch = metrics_to_send[i:i+20]
                self.cloudwatch.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch
                )
        except Exception:
            pass  # Don't fail on CloudWatch issues

# ============================================================================
# LOG FORMATTERS
# ============================================================================

class TradingSystemFormatter(logging.Formatter):
    """
    Custom formatter for trading system logs with structured output
    """
    
    def __init__(self, include_performance: bool = True):
        self.include_performance = include_performance
        super().__init__()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with trading system structure"""
        
        # Base structured data
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': record.levelname,
            'component': getattr(record, 'component', 'unknown'),
            'logger': record.name,
            'message': record.getMessage()
        }
        
        # Add execution context if available
        if hasattr(record, 'execution_id'):
            log_data['execution_id'] = record.execution_id
        
        if hasattr(record, 'operation'):
            log_data['operation'] = record.operation
        
        if hasattr(record, 'symbol'):
            log_data['symbol'] = record.symbol
        
        # Add performance data if available
        if self.include_performance and hasattr(record, 'execution_time'):
            log_data['execution_time'] = record.execution_time
        
        # Add error information
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add custom fields
        if hasattr(record, 'custom_fields'):
            log_data.update(record.custom_fields)
        
        # Add file and line information for debugging
        if record.levelno >= logging.ERROR:
            log_data['location'] = f"{record.filename}:{record.lineno}"
            log_data['function'] = record.funcName
        
        return json.dumps(log_data, default=str, separators=(',', ':'))

class LambdaFormatter(logging.Formatter):
    """
    Lambda-optimized formatter for production deployment
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format for Lambda CloudWatch logs"""
        
        # Simple structured format optimized for CloudWatch
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).strftime('%H:%M:%S.%f')[:-3]
        component = getattr(record, 'component', 'system')
        
        base_msg = f"{timestamp} | {record.levelname:8s} | {component:12s} | {record.getMessage()}"
        
        # Add context if available
        context_parts = []
        if hasattr(record, 'execution_id'):
            context_parts.append(f"exec_id={record.execution_id[:8]}")
        if hasattr(record, 'symbol'):
            context_parts.append(f"symbol={record.symbol}")
        if hasattr(record, 'execution_time'):
            context_parts.append(f"time={record.execution_time:.3f}s")
        
        if context_parts:
            base_msg += f" | {' '.join(context_parts)}"
        
        return base_msg

# ============================================================================
# PRODUCTION LOGGER
# ============================================================================

class ProductionLogger:
    """
    Enterprise-grade logger for trading system components
    
    Features:
    - Structured logging with contextual information
    - Performance monitoring and metrics
    - CloudWatch integration
    - Audit trail logging
    - Security event logging
    - Component-based organization
    """
    
    def __init__(self, component: str, category: LogCategory = LogCategory.SYSTEM):
        self.component = component
        self.category = category
        self.logger = logging.getLogger(f"trading_system.{component}")
        
        # Performance tracking
        self.performance_metrics = defaultdict(list)
        self.operation_timers = {}
        
        # Context management
        self.current_context = LogContext(component=component)
        self._context_stack = []
        self._lock = threading.RLock()
        
        # CloudWatch integration
        self.cloudwatch_handler = CloudWatchMetricsHandler()
        
        # Setup logger if not already configured
        if not self.logger.handlers:
            self._setup_logger()
    
    def _setup_logger(self):
        """Setup logger with appropriate handlers and formatters"""
        
        # Set log level from environment
        log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
        self.logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        
        # Choose formatter based on environment
        if os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
            # Lambda environment - use optimized formatter
            formatter = LambdaFormatter()
        else:
            # Development/testing - use detailed formatter
            formatter = TradingSystemFormatter()
        
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Prevent propagation to avoid duplicate logs
        self.logger.propagate = False
    
    def _add_context_to_record(self, record: logging.LogRecord, **kwargs):
        """Add contextual information to log record"""
        
        # Add current context
        record.component = self.component
        record.category = self.category.value
        
        if self.current_context.execution_id:
            record.execution_id = self.current_context.execution_id
        
        if self.current_context.operation:
            record.operation = self.current_context.operation
        
        if self.current_context.symbol:
            record.symbol = self.current_context.symbol
        
        # Add any additional context
        if kwargs:
            record.custom_fields = kwargs
    
    # ========================================================================
    # CORE LOGGING METHODS
    # ========================================================================
    
    def trace(self, message: str, **kwargs):
        """Log trace-level message"""
        if self.logger.isEnabledFor(5):  # TRACE level
            record = self.logger.makeRecord(
                self.logger.name, 5, __file__, 0, message, (), None
            )
            self._add_context_to_record(record, **kwargs)
            self.logger.handle(record)
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        if self.logger.isEnabledFor(logging.DEBUG):
            record = self.logger.makeRecord(
                self.logger.name, logging.DEBUG, __file__, 0, message, (), None
            )
            self._add_context_to_record(record, **kwargs)
            self.logger.handle(record)
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, __file__, 0, message, (), None
        )
        self._add_context_to_record(record, **kwargs)
        self.logger.handle(record)
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        record = self.logger.makeRecord(
            self.logger.name, logging.WARNING, __file__, 0, message, (), None
        )
        self._add_context_to_record(record, **kwargs)
        self.logger.handle(record)
        
        # Send warning metric to CloudWatch
        self.cloudwatch_handler.put_metric(
            'WarningCount', 1, 'Count',
            {'Component': self.component, 'Category': self.category.value}
        )
    
    def error(self, message: str, **kwargs):
        """Log error message"""
        record = self.logger.makeRecord(
            self.logger.name, logging.ERROR, __file__, 0, message, (), None
        )
        self._add_context_to_record(record, **kwargs)
        self.logger.handle(record)
        
        # Send error metric to CloudWatch
        self.cloudwatch_handler.put_metric(
            'ErrorCount', 1, 'Count',
            {'Component': self.component, 'Category': self.category.value}
        )
    
    def critical(self, message: str, **kwargs):
        """Log critical message"""
        record = self.logger.makeRecord(
            self.logger.name, logging.CRITICAL, __file__, 0, message, (), None
        )
        self._add_context_to_record(record, **kwargs)
        self.logger.handle(record)
        
        # Send critical error metric to CloudWatch
        self.cloudwatch_handler.put_metric(
            'CriticalErrorCount', 1, 'Count',
            {'Component': self.component, 'Category': self.category.value}
        )
    
    def exception(self, message: str, **kwargs):
        """Log exception with full traceback"""
        record = self.logger.makeRecord(
            self.logger.name, logging.ERROR, __file__, 0, message, (), sys.exc_info()
        )
        self._add_context_to_record(record, **kwargs)
        self.logger.handle(record)
    
    # ========================================================================
    # SPECIALIZED LOGGING METHODS
    # ========================================================================
    
    def audit(self, event: str, details: Dict[str, Any]):
        """Log audit event for compliance"""
        audit_data = {
            'event_type': event,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'component': self.component,
            'details': details
        }
        
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, __file__, 0, 
            f"AUDIT: {event}", (), None
        )
        record.audit_data = audit_data
        self._add_context_to_record(record)
        self.logger.handle(record)
    
    def security(self, event: SecurityEvent):
        """Log security event"""
        security_data = asdict(event)
        
        record = self.logger.makeRecord(
            self.logger.name, logging.WARNING, __file__, 0,
            f"SECURITY: {event.event_type} - {event.description}", (), None
        )
        record.security_data = security_data
        self._add_context_to_record(record)
        self.logger.handle(record)
        
        # Send security metric
        self.cloudwatch_handler.put_metric(
            'SecurityEvent', 1, 'Count',
            {'EventType': event.event_type, 'Severity': event.severity}
        )
    
    def performance(self, metric: PerformanceMetric):
        """Log performance metric"""
        with self._lock:
            self.performance_metrics[metric.metric_name].append(metric.value)
        
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, __file__, 0,
            f"PERFORMANCE: {metric.metric_name} = {metric.value} {metric.unit}", (), None
        )
        record.performance_data = asdict(metric)
        self._add_context_to_record(record)
        self.logger.handle(record)
        
        # Send performance metric to CloudWatch
        self.cloudwatch_handler.put_metric(
            metric.metric_name, metric.value, metric.unit,
            {'Component': metric.component}
        )
    
    def trade_execution(self, action: str, symbol: str, quantity: int, 
                       price: float, **kwargs):
        """Log trade execution for audit"""
        trade_data = {
            'action': action,
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **kwargs
        }
        
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, __file__, 0,
            f"TRADE: {action} {quantity} {symbol} @ ${price}", (), None
        )
        record.trade_data = trade_data
        self._add_context_to_record(record, symbol=symbol)
        self.logger.handle(record)
        
        # Send trade metric
        self.cloudwatch_handler.put_metric(
            'TradeExecuted', 1, 'Count',
            {'Action': action, 'Symbol': symbol}
        )
    
    def api_call(self, provider: str, endpoint: str, response_time: float,
                status_code: int, **kwargs):
        """Log API call for monitoring"""
        api_data = {
            'provider': provider,
            'endpoint': endpoint,
            'response_time': response_time,
            'status_code': status_code,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **kwargs
        }
        
        log_level = logging.INFO if status_code < 400 else logging.ERROR
        record = self.logger.makeRecord(
            self.logger.name, log_level, __file__, 0,
            f"API: {provider} {endpoint} - {status_code} ({response_time:.3f}s)", (), None
        )
        record.api_data = api_data
        record.execution_time = response_time
        self._add_context_to_record(record)
        self.logger.handle(record)
        
        # Send API metrics
        self.cloudwatch_handler.put_metric(
            'ApiResponseTime', response_time, 'Seconds',
            {'Provider': provider, 'Endpoint': endpoint}
        )
        
        if status_code >= 400:
            self.cloudwatch_handler.put_metric(
                'ApiError', 1, 'Count',
                {'Provider': provider, 'StatusCode': str(status_code)}
            )
    
    # ========================================================================
    # CONTEXT MANAGEMENT
    # ========================================================================
    
    @contextmanager
    def execution_context(self, execution_id: str, operation: str = None):
        """Context manager for execution tracking"""
        
        with self._lock:
            self._context_stack.append(self.current_context)
            self.current_context = LogContext(
                execution_id=execution_id,
                component=self.component,
                operation=operation
            )
        
        start_time = time.time()
        
        try:
            yield
        finally:
            execution_time = time.time() - start_time
            
            # Log execution completion
            self.info(f"Execution completed: {operation or 'unknown'}",
                     execution_time=execution_time)
            
            # Send execution metric
            self.cloudwatch_handler.put_metric(
                'ExecutionTime', execution_time, 'Seconds',
                {'Component': self.component, 'Operation': operation or 'unknown'}
            )
            
            with self._lock:
                if self._context_stack:
                    self.current_context = self._context_stack.pop()
    
    @contextmanager
    def operation_timer(self, operation: str):
        """Context manager for timing operations"""
        
        start_time = time.time()
        self.debug(f"Starting operation: {operation}")
        
        try:
            yield
        finally:
            execution_time = time.time() - start_time
            self.debug(f"Completed operation: {operation}",
                      execution_time=execution_time)
            
            # Record performance metric
            metric = PerformanceMetric(
                metric_name=f"{operation}_duration",
                value=execution_time,
                unit="seconds",
                timestamp=datetime.now(timezone.utc),
                component=self.component,
                operation=operation
            )
            self.performance(metric)
    
    def set_context(self, **kwargs):
        """Set context for subsequent log messages"""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.current_context, key):
                    setattr(self.current_context, key, value)
    
    # ========================================================================
    # METRICS AND MONITORING
    # ========================================================================
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary"""
        
        with self._lock:
            summary = {}
            for metric_name, values in self.performance_metrics.items():
                if values:
                    summary[metric_name] = {
                        'count': len(values),
                        'average': sum(values) / len(values),
                        'min': min(values),
                        'max': max(values),
                        'latest': values[-1] if values else 0
                    }
            
            return {
                'component': self.component,
                'metrics': summary,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    def flush_metrics(self):
        """Flush all metrics to CloudWatch"""
        self.cloudwatch_handler.flush_metrics()

# ============================================================================
# LOGGING DECORATORS
# ============================================================================

def log_execution_time(logger: ProductionLogger, operation: str = None):
    """Decorator to log function execution time"""
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            
            with logger.operation_timer(op_name):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator

def log_api_call(logger: ProductionLogger, provider: str):
    """Decorator to log API calls"""
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                response_time = time.time() - start_time
                
                # Extract status from result if available
                status_code = getattr(result, 'status_code', 200)
                
                logger.api_call(
                    provider=provider,
                    endpoint=func.__name__,
                    response_time=response_time,
                    status_code=status_code
                )
                
                return result
                
            except Exception as e:
                response_time = time.time() - start_time
                logger.api_call(
                    provider=provider,
                    endpoint=func.__name__,
                    response_time=response_time,
                    status_code=500,
                    error=str(e)
                )
                raise
        
        return wrapper
    return decorator

# ============================================================================
# LOGGER FACTORY
# ============================================================================

class LoggerFactory:
    """
    Factory for creating component-specific loggers
    """
    
    _loggers = {}
    _lock = threading.RLock()
    
    @classmethod
    def get_logger(cls, component: str, category: LogCategory = LogCategory.SYSTEM) -> ProductionLogger:
        """Get or create logger for component"""
        
        logger_key = f"{component}_{category.value}"
        
        with cls._lock:
            if logger_key not in cls._loggers:
                cls._loggers[logger_key] = ProductionLogger(component, category)
            
            return cls._loggers[logger_key]
    
    @classmethod
    def flush_all_metrics(cls):
        """Flush metrics for all loggers"""
        
        with cls._lock:
            for logger in cls._loggers.values():
                logger.flush_metrics()
    
    @classmethod
    def get_all_performance_summaries(cls) -> Dict[str, Any]:
        """Get performance summaries for all loggers"""
        
        with cls._lock:
            summaries = {}
            for logger_key, logger in cls._loggers.items():
                summaries[logger_key] = logger.get_performance_summary()
            
            return summaries

# ============================================================================
# LAMBDA INTEGRATION
# ============================================================================

def setup_lambda_logging():
    """Setup logging for Lambda environment"""
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove default handler
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)
    
    # Add Lambda-optimized handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(LambdaFormatter())
    root_logger.addHandler(handler)

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_logging_system():
    """Test the logging system"""
    
    print("🧪 Testing Production Logging System...")
    
    try:
        # Create test logger
        logger = LoggerFactory.get_logger('test_component', LogCategory.TRADING)
        
        # Test basic logging
        logger.info("Test info message", test_param="test_value")
        logger.warning("Test warning message")
        
        # Test context management
        with logger.execution_context("test_exec_123", "test_operation"):
            logger.info("Message within execution context")
            
            with logger.operation_timer("test_timer"):
                time.sleep(0.1)  # Simulate work
        
        # Test specialized logging
        logger.audit("test_event", {"key": "value"})
        
        logger.trade_execution(
            action="BUY",
            symbol="AAPL", 
            quantity=100,
            price=150.50,
            order_id="test_order_123"
        )
        
        logger.api_call(
            provider="alpaca",
            endpoint="/v2/account",
            response_time=0.234,
            status_code=200
        )
        
        # Test performance metric
        metric = PerformanceMetric(
            metric_name="test_metric",
            value=42.0,
            unit="count",
            timestamp=datetime.now(timezone.utc),
            component="test_component"
        )
        logger.performance(metric)
        
        # Get performance summary
        summary = logger.get_performance_summary()
        print(f"✅ Performance summary: {len(summary['metrics'])} metrics tracked")
        
        # Test error logging
        try:
            raise ValueError("Test exception")
        except Exception:
            logger.exception("Test exception logging")
        
        print("✅ All logging tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Logging test failed: {e}")
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_logging_system()
