#!/usr/bin/env python3
"""
Simple test to verify Alpaca connection works
"""

import os
import sys

# Set up environment variables
os.environ['ALPACA_API_KEY'] = 'PKTGTBUDLQ3V9XFHTBHA'
os.environ['ALPACA_SECRET_KEY'] = 'PSOdtqJ5PQAk7Up76ZPSHd1km5NDC9f74YHX6bvK'
os.environ['ALPACA_BASE_URL'] = 'https://paper-api.alpaca.markets'
os.environ['ALPHA_VANTAGE_KEY'] = 'W81PG6O5UI6Q720I'
os.environ['NEWSAPI_KEY'] = '7cbc465672f44938a3c7f3ad20809d9e'
os.environ['SNS_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:826564544834:trading-system-alerts'
os.environ['SIGNALS_TABLE'] = 'trading-signals'
os.environ['PERFORMANCE_TABLE'] = 'trading-performance'
os.environ['PORTFOLIO_TABLE'] = 'trading-system-portfolio'
os.environ['ENVIRONMENT'] = 'development'
os.environ['TRADING_ENABLED'] = 'true'
os.environ['NOTIFICATION_EMAIL'] = 'rkong@armku.us'
os.environ['FINHUB_API_KEY'] = 'cp2mcd9r01qtd8fspcl0cp2mcd9r01qtd8fspclg'

# Add src to path
sys.path.insert(0, 'src')

def test_alpaca():
    try:
        from core.config_manager import ProductionConfigManager
        from core.state_manager import ProductionStateManager  
        from trading.alpaca_client import ProductionAlpacaClient
        
        print("✅ Imports successful")
        
        config = ProductionConfigManager()
        state = ProductionStateManager(config)
        client = ProductionAlpacaClient(config, state)
        
        print("✅ Objects created")
        
        if client.connect():
            print("✅ Connected to Alpaca")
            
            account = client.get_account()
            if account:
                print(f"✅ Account: ${account.portfolio_value:,.2f}")
                return True
            else:
                print("❌ Could not get account info")
                return False
        else:
            print("❌ Could not connect to Alpaca")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("Testing Alpaca connection...")
    success = test_alpaca()
    print("Success!" if success else "Failed!")
