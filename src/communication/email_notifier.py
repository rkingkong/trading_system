#!/usr/bin/env python3
"""
📧 PRODUCTION TRADING SYSTEM - EMAIL NOTIFICATION SYSTEM
src/communication/email_notifier.py

Enterprise-grade email notification system with AWS SNS integration,
comprehensive trading alerts, performance reports, and risk notifications.

Features:
- AWS SNS email notifications with HTML formatting
- Trading event notifications (executions, orders, positions)
- Risk alerts and limit breach notifications
- Daily/weekly/monthly performance reports
- System health and error notifications
- Template-based email formatting with branding
- Rate limiting and delivery tracking
- Email categorization and priority handling

Author: Production Trading System
Version: 1.0.0
Environment: AWS Lambda Python 3.9
"""

import json
import time
import threading
import smtplib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict, field
from enum import Enum
from decimal import Decimal
import uuid
from collections import defaultdict, deque
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import boto3
from botocore.exceptions import ClientError, BotoCoreError

# Import our core components
try:
    from ..core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from ..core.config_manager import ProductionConfigManager
    from ..core.state_manager import ProductionStateManager, SystemAlert, AlertSeverity
except ImportError:
    # Fallback for testing
    from core.logger import LoggerFactory, LogCategory, PerformanceMetric
    from core.config_manager import ProductionConfigManager
    from core.state_manager import ProductionStateManager, SystemAlert, AlertSeverity

# ============================================================================
# EMAIL NOTIFICATION TYPES AND ENUMS
# ============================================================================

class EmailType(Enum):
    """Email notification types"""
    TRADE_EXECUTION = "trade_execution"
    ORDER_STATUS = "order_status"
    POSITION_UPDATE = "position_update"
    RISK_ALERT = "risk_alert"
    SYSTEM_HEALTH = "system_health"
    PERFORMANCE_REPORT = "performance_report"
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_REPORT = "weekly_report"
    MONTHLY_REPORT = "monthly_report"
    ERROR_NOTIFICATION = "error_notification"
    EMERGENCY_ALERT = "emergency_alert"

class EmailPriority(Enum):
    """Email priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    EMERGENCY = 5

class DeliveryStatus(Enum):
    """Email delivery status"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"

@dataclass
class EmailTemplate:
    """Email template configuration"""
    template_id: str
    subject_template: str
    html_template: str
    text_template: str
    required_variables: List[str]
    email_type: EmailType
    priority: EmailPriority

@dataclass
class EmailNotification:
    """Email notification record"""
    notification_id: str
    email_type: EmailType
    priority: EmailPriority
    recipient: str
    subject: str
    html_content: str
    text_content: str
    metadata: Dict[str, Any]
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivery_status: DeliveryStatus = DeliveryStatus.PENDING
    sns_message_id: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0

@dataclass
class EmailMetrics:
    """Email system metrics"""
    total_sent: int
    total_delivered: int
    total_failed: int
    delivery_rate: float
    average_delivery_time: float
    emails_by_type: Dict[str, int]
    emails_by_priority: Dict[str, int]
    rate_limit_hits: int
    last_24h_count: int

# ============================================================================
# EMAIL TEMPLATES
# ============================================================================

EMAIL_TEMPLATES = {
    EmailType.TRADE_EXECUTION: EmailTemplate(
        template_id="trade_execution",
        subject_template="TRADING SYSTEM - {action} {symbol} - {timestamp}",
        html_template="""
        <html>
        <head><style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .header { background: #1f4e79; color: white; padding: 15px; border-radius: 5px; }
            .content { padding: 20px; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }
            .metrics { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0; }
            .success { color: #28a745; font-weight: bold; }
            .warning { color: #ffc107; font-weight: bold; }
            .error { color: #dc3545; font-weight: bold; }
            .footer { color: #666; font-size: 12px; margin-top: 20px; }
        </style></head>
        <body>
            <div class="header">
                <h2>🎯 Trade Execution Alert</h2>
                <p>Trading System - {execution_time}</p>
            </div>
            <div class="content">
                <h3 class="{status_class}">✅ {action} Order Executed</h3>
                <div class="metrics">
                    <p><strong>Symbol:</strong> {symbol}</p>
                    <p><strong>Action:</strong> {action}</p>
                    <p><strong>Quantity:</strong> {quantity:,} shares</p>
                    <p><strong>Price:</strong> ${price:.2f}</p>
                    <p><strong>Total Value:</strong> ${total_value:,.2f}</p>
                    <p><strong>Execution Time:</strong> {execution_time}</p>
                    <p><strong>Order ID:</strong> {order_id}</p>
                </div>
                {additional_info}
            </div>
            <div class="footer">
                <p>Trading System - Paper Trading Mode | Generated at {timestamp}</p>
            </div>
        </body>
        </html>
        """,
        text_template="""
TRADING SYSTEM - TRADE EXECUTION ALERT

{action} Order Executed: {symbol}
Quantity: {quantity:,} shares
Price: ${price:.2f}
Total Value: ${total_value:,.2f}
Execution Time: {execution_time}
Order ID: {order_id}

{additional_info}

Trading System - Paper Trading Mode
Generated at {timestamp}
        """,
        required_variables=["action", "symbol", "quantity", "price", "total_value", "execution_time", "order_id"],
        email_type=EmailType.TRADE_EXECUTION,
        priority=EmailPriority.HIGH
    ),
    
    EmailType.RISK_ALERT: EmailTemplate(
        template_id="risk_alert",
        subject_template="🚨 RISK ALERT - {risk_type} - {severity}",
        html_template="""
        <html>
        <head><style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .header { background: #dc3545; color: white; padding: 15px; border-radius: 5px; }
            .content { padding: 20px; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }
            .alert { background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 10px 0; }
            .critical { background: #f8d7da; border: 1px solid #f5c6cb; }
            .values { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0; }
            .footer { color: #666; font-size: 12px; margin-top: 20px; }
        </style></head>
        <body>
            <div class="header">
                <h2>🚨 RISK MANAGEMENT ALERT</h2>
                <p>Immediate Attention Required</p>
            </div>
            <div class="content">
                <div class="alert {alert_class}">
                    <h3>⚠️ {risk_type} Limit Breach</h3>
                    <p><strong>Severity:</strong> {severity}</p>
                    <p><strong>Description:</strong> {description}</p>
                </div>
                <div class="values">
                    <p><strong>Current Value:</strong> {current_value}</p>
                    <p><strong>Limit Value:</strong> {limit_value}</p>
                    <p><strong>Breach Amount:</strong> {breach_amount}</p>
                    <p><strong>Breach Percentage:</strong> {breach_percent:.2f}%</p>
                    {symbol_info}
                </div>
                <h4>🛡️ Action Taken</h4>
                <p><strong>Automated Response:</strong> {action_taken}</p>
                <p><strong>Timestamp:</strong> {timestamp}</p>
            </div>
            <div class="footer">
                <p>Trading System Risk Management | Alert ID: {alert_id}</p>
            </div>
        </body>
        </html>
        """,
        text_template="""
🚨 TRADING SYSTEM - RISK MANAGEMENT ALERT

RISK LIMIT BREACH DETECTED

Risk Type: {risk_type}
Severity: {severity}
Description: {description}

Current Value: {current_value}
Limit Value: {limit_value}
Breach Amount: {breach_amount}
Breach Percentage: {breach_percent:.2f}%
{symbol_info}

Action Taken: {action_taken}
Timestamp: {timestamp}
Alert ID: {alert_id}

Trading System Risk Management
        """,
        required_variables=["risk_type", "severity", "description", "current_value", "limit_value", "breach_amount", "breach_percent", "action_taken"],
        email_type=EmailType.RISK_ALERT,
        priority=EmailPriority.EMERGENCY
    ),
    
    EmailType.DAILY_SUMMARY: EmailTemplate(
        template_id="daily_summary",
        subject_template="📊 Daily Trading Summary - {date} - P&L: {pnl_summary}",
        html_template="""
        <html>
        <head><style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .header { background: #1f4e79; color: white; padding: 15px; border-radius: 5px; }
            .content { padding: 20px; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }
            .summary { display: flex; gap: 20px; margin: 20px 0; }
            .metric-box { background: #f8f9fa; padding: 15px; border-radius: 5px; flex: 1; text-align: center; }
            .positive { color: #28a745; font-weight: bold; }
            .negative { color: #dc3545; font-weight: bold; }
            .positions { margin: 20px 0; }
            .position { background: #fff; border: 1px solid #ddd; padding: 10px; margin: 5px 0; border-radius: 3px; }
            .footer { color: #666; font-size: 12px; margin-top: 20px; }
        </style></head>
        <body>
            <div class="header">
                <h2>📊 Daily Trading Summary</h2>
                <p>{date} - Portfolio Performance Report</p>
            </div>
            <div class="content">
                <div class="summary">
                    <div class="metric-box">
                        <h4>Portfolio Value</h4>
                        <p><strong>${portfolio_value:,.2f}</strong></p>
                    </div>
                    <div class="metric-box">
                        <h4>Daily P&L</h4>
                        <p class="{pnl_class}"><strong>{daily_pnl:+,.2f}</strong></p>
                        <p>({daily_pnl_percent:+.2f}%)</p>
                    </div>
                    <div class="metric-box">
                        <h4>Trades Executed</h4>
                        <p><strong>{trades_executed}</strong></p>
                    </div>
                </div>
                
                <h3>📈 Performance Metrics</h3>
                <div class="positions">
                    <p><strong>Total Return:</strong> <span class="{total_return_class}">{total_return:+.2f}%</span></p>
                    <p><strong>Cash Position:</strong> ${cash:,.2f} ({cash_percent:.1f}%)</p>
                    <p><strong>Active Positions:</strong> {position_count}</p>
                    <p><strong>Winning Positions:</strong> {winning_positions}</p>
                    <p><strong>Losing Positions:</strong> {losing_positions}</p>
                </div>
                
                <h3>🏆 Top Performers</h3>
                {top_performers}
                
                <h3>⚠️ Risk Status</h3>
                <p><strong>Risk Level:</strong> {risk_level}</p>
                <p><strong>Max Drawdown:</strong> {max_drawdown:.2f}%</p>
                <p><strong>Portfolio Concentration:</strong> {concentration:.1f}%</p>
            </div>
            <div class="footer">
                <p>Trading System Daily Report | Generated at {timestamp}</p>
            </div>
        </body>
        </html>
        """,
        text_template="""
📊 TRADING SYSTEM - DAILY SUMMARY

Date: {date}
Portfolio Value: ${portfolio_value:,.2f}
Daily P&L: {daily_pnl:+,.2f} ({daily_pnl_percent:+.2f}%)
Trades Executed: {trades_executed}

PERFORMANCE METRICS:
Total Return: {total_return:+.2f}%
Cash Position: ${cash:,.2f} ({cash_percent:.1f}%)
Active Positions: {position_count}
Winning Positions: {winning_positions}
Losing Positions: {losing_positions}

TOP PERFORMERS:
{top_performers_text}

RISK STATUS:
Risk Level: {risk_level}
Max Drawdown: {max_drawdown:.2f}%
Portfolio Concentration: {concentration:.1f}%

Trading System Daily Report
Generated at {timestamp}
        """,
        required_variables=["date", "portfolio_value", "daily_pnl", "daily_pnl_percent", "trades_executed"],
        email_type=EmailType.DAILY_SUMMARY,
        priority=EmailPriority.NORMAL
    )
}

# ============================================================================
# PRODUCTION EMAIL NOTIFIER
# ============================================================================

class ProductionEmailNotifier:
    """
    Enterprise-grade email notification system
    
    Features:
    - AWS SNS integration with HTML email support
    - Template-based email generation
    - Rate limiting and delivery tracking
    - Priority-based email routing
    - Comprehensive email metrics
    - Error handling and retry logic
    """
    
    def __init__(self, config_manager: ProductionConfigManager,
                 state_manager: ProductionStateManager):
        self.config_manager = config_manager
        self.state_manager = state_manager
        self.logger = LoggerFactory.get_logger('email_notifier', LogCategory.SYSTEM)
        
        # AWS SNS configuration
        aws_config = config_manager.get_config('aws')
        self.sns_topic_arn = aws_config['sns']['topic_arn']
        self.notification_email = config_manager.get_config('system')['notification_email']
        
        # Email system configuration
        system_config = config_manager.get_config('system')
        self.email_settings = system_config.get('email_notifications', {})
        
        # Initialize AWS SNS client
        try:
            self.sns_client = boto3.client('sns', region_name=aws_config['region'])
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize SNS client: {e}")
            self.sns_client = None
        
        # Email tracking
        self._email_lock = threading.RLock()
        self.email_queue = deque(maxlen=1000)
        self.email_history = deque(maxlen=5000)
        self.failed_emails = deque(maxlen=500)
        
        # Rate limiting
        self.rate_limits = {
            EmailPriority.EMERGENCY: {'per_hour': 100, 'per_day': 500},
            EmailPriority.URGENT: {'per_hour': 50, 'per_day': 200},
            EmailPriority.HIGH: {'per_hour': 25, 'per_day': 100},
            EmailPriority.NORMAL: {'per_hour': 10, 'per_day': 50},
            EmailPriority.LOW: {'per_hour': 5, 'per_day': 20}
        }
        
        self.sent_counts = defaultdict(lambda: defaultdict(int))
        
        # Email metrics
        self.email_metrics = EmailMetrics(
            total_sent=0,
            total_delivered=0,
            total_failed=0,
            delivery_rate=0.0,
            average_delivery_time=0.0,
            emails_by_type={},
            emails_by_priority={},
            rate_limit_hits=0,
            last_24h_count=0
        )
        
        # Templates
        self.templates = EMAIL_TEMPLATES
        
        # Register with state manager
        state_manager.register_component('email_notifier', self)
        
        self.logger.info("📧 Email Notifier initialized",
                        sns_topic=self.sns_topic_arn,
                        notification_email=self.notification_email,
                        templates_loaded=len(self.templates))
    
    # ========================================================================
    # EMAIL SENDING INTERFACE
    # ========================================================================
    
    def send_trade_execution_email(self, trade_data: Dict[str, Any]) -> str:
        """Send trade execution notification"""
        
        try:
            # Prepare template variables
            variables = {
                'action': trade_data['action'].upper(),
                'symbol': trade_data['symbol'],
                'quantity': int(trade_data['quantity']),
                'price': float(trade_data['price']),
                'total_value': float(trade_data['quantity']) * float(trade_data['price']),
                'execution_time': trade_data.get('execution_time', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')),
                'order_id': trade_data.get('order_id', 'N/A'),
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                'status_class': 'success' if trade_data.get('status') == 'filled' else 'warning',
                'additional_info': self._format_additional_trade_info(trade_data)
            }
            
            return self._send_templated_email(
                EmailType.TRADE_EXECUTION,
                variables,
                metadata=trade_data
            )
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send trade execution email: {e}")
            return ""
    
    def send_risk_alert_email(self, risk_violation: Dict[str, Any]) -> str:
        """Send risk alert notification"""
        
        try:
            # Determine alert class based on severity
            severity = risk_violation.get('severity', 'medium')
            alert_class = 'critical' if severity in ['high', 'critical'] else 'alert'
            
            # Prepare template variables
            variables = {
                'risk_type': risk_violation['violation_type'].replace('_', ' ').title(),
                'severity': severity.upper(),
                'description': risk_violation['description'],
                'current_value': risk_violation['current_value'],
                'limit_value': risk_violation['limit_value'],
                'breach_amount': risk_violation['breach_amount'],
                'breach_percent': risk_violation['breach_percent'],
                'action_taken': risk_violation['action_taken'].replace('_', ' ').title(),
                'timestamp': risk_violation.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')),
                'alert_id': risk_violation.get('violation_id', str(uuid.uuid4())),
                'alert_class': alert_class,
                'symbol_info': f"Symbol: {risk_violation['symbol']}" if risk_violation.get('symbol') else ""
            }
            
            return self._send_templated_email(
                EmailType.RISK_ALERT,
                variables,
                priority=EmailPriority.EMERGENCY,
                metadata=risk_violation
            )
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send risk alert email: {e}")
            return ""
    
    def send_daily_summary_email(self, portfolio_data: Dict[str, Any]) -> str:
        """Send daily portfolio summary"""
        
        try:
            # Calculate P&L classes
            daily_pnl = portfolio_data.get('daily_pnl', 0)
            total_return = portfolio_data.get('total_return', 0)
            pnl_class = 'positive' if daily_pnl >= 0 else 'negative'
            total_return_class = 'positive' if total_return >= 0 else 'negative'
            
            # Format top performers
            top_performers_html = self._format_top_performers_html(portfolio_data.get('top_performers', []))
            top_performers_text = self._format_top_performers_text(portfolio_data.get('top_performers', []))
            
            # Prepare template variables
            variables = {
                'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'portfolio_value': portfolio_data.get('portfolio_value', 0),
                'daily_pnl': daily_pnl,
                'daily_pnl_percent': portfolio_data.get('daily_pnl_percent', 0),
                'trades_executed': portfolio_data.get('trades_executed', 0),
                'total_return': total_return,
                'cash': portfolio_data.get('cash', 0),
                'cash_percent': portfolio_data.get('cash_percent', 0),
                'position_count': portfolio_data.get('position_count', 0),
                'winning_positions': portfolio_data.get('winning_positions', 0),
                'losing_positions': portfolio_data.get('losing_positions', 0),
                'risk_level': portfolio_data.get('risk_level', 'Unknown'),
                'max_drawdown': portfolio_data.get('max_drawdown', 0),
                'concentration': portfolio_data.get('concentration', 0),
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                'pnl_class': pnl_class,
                'total_return_class': total_return_class,
                'pnl_summary': f"{daily_pnl:+.2f}%",
                'top_performers': top_performers_html,
                'top_performers_text': top_performers_text
            }
            
            return self._send_templated_email(
                EmailType.DAILY_SUMMARY,
                variables,
                metadata=portfolio_data
            )
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send daily summary email: {e}")
            return ""
    
    def send_system_alert_email(self, alert: SystemAlert) -> str:
        """Send system alert notification"""
        
        try:
            # Map alert severity to email priority
            priority_map = {
                AlertSeverity.INFO: EmailPriority.LOW,
                AlertSeverity.WARNING: EmailPriority.NORMAL,
                AlertSeverity.CRITICAL: EmailPriority.HIGH,
                AlertSeverity.EMERGENCY: EmailPriority.EMERGENCY
            }
            
            priority = priority_map.get(alert.severity, EmailPriority.NORMAL)
            
            # Create email content
            subject = f"TRADING SYSTEM - {alert.severity.value.upper()} - {alert.component}"
            
            html_content = f"""
            <html>
            <head><style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #dc3545; color: white; padding: 15px; border-radius: 5px; }}
                .content {{ padding: 20px; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }}
                .alert {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            </style></head>
            <body>
                <div class="header">
                    <h2>🚨 System Alert</h2>
                    <p>Component: {alert.component}</p>
                </div>
                <div class="content">
                    <div class="alert">
                        <h3>{alert.severity.value.upper()}: {alert.message}</h3>
                        <p><strong>Alert ID:</strong> {alert.alert_id}</p>
                        <p><strong>Timestamp:</strong> {alert.timestamp.isoformat()}</p>
                        <p><strong>Component:</strong> {alert.component}</p>
                    </div>
                    <h4>Additional Information</h4>
                    <pre>{json.dumps(alert.metadata, indent=2)}</pre>
                </div>
            </body>
            </html>
            """
            
            text_content = f"""
TRADING SYSTEM - SYSTEM ALERT

Severity: {alert.severity.value.upper()}
Component: {alert.component}
Message: {alert.message}
Alert ID: {alert.alert_id}
Timestamp: {alert.timestamp.isoformat()}

Additional Information:
{json.dumps(alert.metadata, indent=2)}
            """
            
            return self._send_email(
                email_type=EmailType.SYSTEM_HEALTH,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                priority=priority,
                metadata=asdict(alert)
            )
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send system alert email: {e}")
            return ""
    
    # ========================================================================
    # TEMPLATED EMAIL PROCESSING
    # ========================================================================
    
    def _send_templated_email(self, email_type: EmailType, variables: Dict[str, Any],
                            priority: EmailPriority = None, metadata: Dict[str, Any] = None) -> str:
        """Send email using template"""
        
        try:
            template = self.templates.get(email_type)
            if not template:
                raise ValueError(f"Template not found for email type: {email_type}")
            
            # Validate required variables
            missing_vars = [var for var in template.required_variables if var not in variables]
            if missing_vars:
                raise ValueError(f"Missing required variables: {missing_vars}")
            
            # Use template priority if not specified
            if priority is None:
                priority = template.priority
            
            # Format subject
            subject = template.subject_template.format(**variables)
            
            # Format HTML content
            html_content = template.html_template.format(**variables)
            
            # Format text content
            text_content = template.text_template.format(**variables)
            
            return self._send_email(
                email_type=email_type,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                priority=priority,
                metadata=metadata or {}
            )
            
        except Exception as e:
            self.logger.error(f"❌ Failed to send templated email: {e}")
            raise
    
    def _send_email(self, email_type: EmailType, subject: str, html_content: str,
                   text_content: str, priority: EmailPriority = EmailPriority.NORMAL,
                   metadata: Dict[str, Any] = None) -> str:
        """Send email via AWS SNS"""
        
        notification_id = str(uuid.uuid4())
        
        try:
            with self._email_lock:
                # Check if email notifications are enabled
                if not self.email_settings.get('enabled', True):
                    self.logger.info("📧 Email notifications disabled, skipping")
                    return notification_id
                
                # Check rate limits
                if not self._check_rate_limit(priority):
                    self.logger.warning(f"⏱️ Rate limit exceeded for priority {priority.value}")
                    self.email_metrics.rate_limit_hits += 1
                    return notification_id
                
                # Create notification record
                notification = EmailNotification(
                    notification_id=notification_id,
                    email_type=email_type,
                    priority=priority,
                    recipient=self.notification_email,
                    subject=subject,
                    html_content=html_content,
                    text_content=text_content,
                    metadata=metadata or {},
                    created_at=datetime.now(timezone.utc)
                )
                
                # Add to queue
                self.email_queue.append(notification)
                
                # Send via SNS
                self._send_via_sns(notification)
                
                return notification_id
                
        except Exception as e:
            self.logger.error(f"❌ Failed to send email: {e}")
            return notification_id
    
    def _send_via_sns(self, notification: EmailNotification):
        """Send email via AWS SNS"""
        
        try:
            if not self.sns_client:
                raise Exception("SNS client not initialized")
            
            # Create SNS message
            sns_message = {
                'default': notification.text_content,
                'email': notification.html_content
            }
            
            # Send to SNS
            response = self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Subject=notification.subject,
                Message=json.dumps(sns_message),
                MessageStructure='json'
            )
            
            # Update notification
            notification.sent_at = datetime.now(timezone.utc)
            notification.delivery_status = DeliveryStatus.SENT
            notification.sns_message_id = response.get('MessageId')
            
            # Update metrics
            self._update_metrics(notification, success=True)
            
            # Move to history
            self.email_history.append(notification)
            
            self.logger.info(f"📧 Email sent successfully: {notification.email_type.value}",
                           notification_id=notification.notification_id,
                           subject=notification.subject,
                           sns_message_id=notification.sns_message_id)
            
        except Exception as e:
            notification.delivery_status = DeliveryStatus.FAILED
            notification.error_message = str(e)
            notification.retry_count += 1
            
            # Update metrics
            self._update_metrics(notification, success=False)
            
            # Add to failed queue
            self.failed_emails.append(notification)
            
            self.logger.error(f"❌ Failed to send email via SNS: {e}",
                            notification_id=notification.notification_id)
    
    # ========================================================================
    # RATE LIMITING AND METRICS
    # ========================================================================
    
    def _check_rate_limit(self, priority: EmailPriority) -> bool:
        """Check if email can be sent based on rate limits"""
        
        try:
            current_time = datetime.now(timezone.utc)
            current_hour = current_time.replace(minute=0, second=0, microsecond=0)
            current_day = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Get rate limits for priority
            limits = self.rate_limits.get(priority, {'per_hour': 10, 'per_day': 50})
            
            # Check hourly limit
            hourly_count = self.sent_counts[current_hour][priority]
            if hourly_count >= limits['per_hour']:
                return False
            
            # Check daily limit
            daily_count = self.sent_counts[current_day][priority]
            if daily_count >= limits['per_day']:
                return False
            
            # Update counts
            self.sent_counts[current_hour][priority] += 1
            self.sent_counts[current_day][priority] += 1
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Rate limit check failed: {e}")
            return True  # Allow on error
    
    def _update_metrics(self, notification: EmailNotification, success: bool):
        """Update email metrics"""
        
        try:
            if success:
                self.email_metrics.total_sent += 1
                self.email_metrics.total_delivered += 1
            else:
                self.email_metrics.total_failed += 1
            
            # Update by type
            email_type = notification.email_type.value
            if email_type not in self.email_metrics.emails_by_type:
                self.email_metrics.emails_by_type[email_type] = 0
            self.email_metrics.emails_by_type[email_type] += 1
            
            # Update by priority
            priority = notification.priority.value
            if priority not in self.email_metrics.emails_by_priority:
                self.email_metrics.emails_by_priority[priority] = 0
            self.email_metrics.emails_by_priority[priority] += 1
            
            # Calculate delivery rate
            total_attempts = self.email_metrics.total_sent + self.email_metrics.total_failed
            if total_attempts > 0:
                self.email_metrics.delivery_rate = (self.email_metrics.total_delivered / total_attempts) * 100
            
            # Log performance metric
            self.logger.performance(PerformanceMetric(
                metric_name="email_delivery_rate",
                value=self.email_metrics.delivery_rate,
                unit="percent",
                timestamp=datetime.now(timezone.utc),
                component="email_notifier"
            ))
            
        except Exception as e:
            self.logger.error(f"❌ Failed to update email metrics: {e}")
    
    # ========================================================================
    # EMAIL FORMATTING HELPERS
    # ========================================================================
    
    def _format_additional_trade_info(self, trade_data: Dict[str, Any]) -> str:
        """Format additional trade information"""
        
        info_parts = []
        
        if 'slippage' in trade_data:
            slippage = trade_data['slippage']
            info_parts.append(f"<p><strong>Slippage:</strong> {slippage:.4f}%</p>")
        
        if 'execution_strategy' in trade_data:
            strategy = trade_data['execution_strategy']
            info_parts.append(f"<p><strong>Strategy:</strong> {strategy}</p>")
        
        if 'confidence' in trade_data:
            confidence = trade_data['confidence']
            info_parts.append(f"<p><strong>AI Confidence:</strong> {confidence:.1f}%</p>")
        
        return "\n".join(info_parts) if info_parts else ""
    
    def _format_top_performers_html(self, performers: List[Dict[str, Any]]) -> str:
        """Format top performers for HTML email"""
        
        if not performers:
            return "<p>No position data available</p>"
        
        html_parts = []
        for performer in performers[:5]:  # Top 5
            symbol = performer.get('symbol', 'N/A')
            pnl_percent = performer.get('pnl_percent', 0)
            pnl = performer.get('pnl', 0)
            pnl_class = 'positive' if pnl >= 0 else 'negative'
            
            html_parts.append(f"""
            <div class="position">
                <strong>{symbol}:</strong> 
                <span class="{pnl_class}">{pnl_percent:+.2f}%</span> 
                (${pnl:+,.2f})
            </div>
            """)
        
        return "\n".join(html_parts)
    
    def _format_top_performers_text(self, performers: List[Dict[str, Any]]) -> str:
        """Format top performers for text email"""
        
        if not performers:
            return "No position data available"
        
        text_parts = []
        for performer in performers[:5]:  # Top 5
            symbol = performer.get('symbol', 'N/A')
            pnl_percent = performer.get('pnl_percent', 0)
            pnl = performer.get('pnl', 0)
            
            text_parts.append(f"{symbol}: {pnl_percent:+.2f}% (${pnl:+,.2f})")
        
        return "\n".join(text_parts)
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def get_email_metrics(self) -> Dict[str, Any]:
        """Get email system metrics"""
        
        return {
            'total_sent': self.email_metrics.total_sent,
            'total_delivered': self.email_metrics.total_delivered,
            'total_failed': self.email_metrics.total_failed,
            'delivery_rate_percent': round(self.email_metrics.delivery_rate, 2),
            'rate_limit_hits': self.email_metrics.rate_limit_hits,
            'emails_by_type': self.email_metrics.emails_by_type.copy(),
            'emails_by_priority': self.email_metrics.emails_by_priority.copy(),
            'queue_size': len(self.email_queue),
            'failed_queue_size': len(self.failed_emails),
            'history_size': len(self.email_history)
        }
    
    def get_recent_emails(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent email history"""
        
        recent_emails = []
        for notification in list(self.email_history)[-limit:]:
            recent_emails.append({
                'notification_id': notification.notification_id,
                'email_type': notification.email_type.value,
                'priority': notification.priority.value,
                'subject': notification.subject,
                'recipient': notification.recipient,
                'delivery_status': notification.delivery_status.value,
                'sent_at': notification.sent_at.isoformat() if notification.sent_at else None,
                'error_message': notification.error_message
            })
        
        return recent_emails
    
    def health_check(self) -> bool:
        """Perform email system health check"""
        
        try:
            # Check SNS client
            if not self.sns_client:
                self.logger.warning("⚠️ SNS client not initialized")
                return False
            
            # Check recent delivery rate
            if self.email_metrics.total_sent > 10 and self.email_metrics.delivery_rate < 80:
                self.logger.warning(f"⚠️ Low email delivery rate: {self.email_metrics.delivery_rate:.2f}%")
                return False
            
            # Check for excessive failures
            if len(self.failed_emails) > 50:
                self.logger.warning(f"⚠️ High failed email count: {len(self.failed_emails)}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Email system health check failed: {e}")
            return False
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get email system status"""
        
        return {
            'sns_client_initialized': self.sns_client is not None,
            'sns_topic_arn': self.sns_topic_arn,
            'notification_email': self.notification_email,
            'email_notifications_enabled': self.email_settings.get('enabled', True),
            'templates_loaded': len(self.templates),
            'metrics': self.get_email_metrics(),
            'healthy': self.health_check()
        }

# ============================================================================
# TESTING AND VALIDATION
# ============================================================================

def test_email_notifier():
    """Test the email notification system"""
    
    print("🧪 Testing Email Notifier...")
    
    try:
        # Mock dependencies for testing
        class MockConfigManager:
            def get_config(self, section):
                if section == 'aws':
                    return {
                        'region': 'us-east-1',
                        'sns': {
                            'topic_arn': 'arn:aws:sns:us-east-1:826564544834:trading-system-alerts'
                        }
                    }
                elif section == 'system':
                    return {
                        'notification_email': 'test@example.com',
                        'email_notifications': {'enabled': True}
                    }
                return {}
        
        class MockStateManager:
            def register_component(self, name, instance=None):
                pass
        
        config_manager = MockConfigManager()
        state_manager = MockStateManager()
        
        # Create email notifier (will fail SNS init but that's OK for testing)
        email_notifier = ProductionEmailNotifier(config_manager, state_manager)
        
        # Test template validation
        trade_data = {
            'action': 'BUY',
            'symbol': 'AAPL',
            'quantity': 100,
            'price': 150.50,
            'execution_time': '2025-06-09 10:30:00 UTC',
            'order_id': 'ORDER_123'
        }
        
        # Test template formatting (without actual sending)
        template = email_notifier.templates[EmailType.TRADE_EXECUTION]
        variables = {
            'action': trade_data['action'],
            'symbol': trade_data['symbol'],
            'quantity': trade_data['quantity'],
            'price': trade_data['price'],
            'total_value': trade_data['quantity'] * trade_data['price'],
            'execution_time': trade_data['execution_time'],
            'order_id': trade_data['order_id'],
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            'status_class': 'success',
            'additional_info': ''
        }
        
        subject = template.subject_template.format(**variables)
        print(f"✅ Template formatting: {subject}")
        
        # Test metrics
        metrics = email_notifier.get_email_metrics()
        print(f"✅ Email metrics: {metrics}")
        
        # Test system status
        status = email_notifier.get_system_status()
        print(f"✅ System status: {status['healthy']}")
        
        print("🎉 Email Notifier test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Email Notifier test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run tests if executed directly
    test_email_notifier()
