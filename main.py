import requests
import logging
from typing import List, Dict, Tuple
from datetime import datetime
import numpy as np
import json

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('token_analysis.log')
    ]
)

# API Configuration
API_KEY = "c2fb6b8c-cd34-41cb-ad47-b685fca28a91"
API_URL_BASE = "https://pro-api.coinmarketcap.com/v1"

class TokenAnalyzer:
    def __init__(self, api_key: str):
        """Initialize TokenAnalyzer with configuration parameters"""
        logging.debug("Initializing TokenAnalyzer...")
        
        self.api_key = api_key
        self.headers = {
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json"
        }
        
        # Market Cap Ranges for different risk levels
        self.risk_ranges = {
            "low": (100_000_000, 1_000_000_000),    # $100M-$1B
            "medium": (25_000_000, 100_000_000),    # $25M-$100M
            "high": (1_000_000, 25_000_000)         # $1M-$25M
        }
        
        # Minimum Daily Volume Requirements
        self.min_volume = {
            "low": 1_000_000,      # $1M daily
            "medium": 500_000,     # $500K daily
            "high": 100_000        # $100K daily
        }
        
        # Volume to Market Cap Ratio Limits
        self.volume_mcap_limits = {
            "low": (0.01, 0.20),    # 1-20%
            "medium": (0.02, 0.30),  # 2-30%
            "high": (0.05, 0.40)     # 5-40%
        }
        
        # Minimum Age Requirements (days)
        self.min_age = {
            "low": 180,     # 6 months
            "medium": 90,   # 3 months
            "high": 30      # 1 month
        }
        
        # Maximum Volatility Limits
        self.max_volatility = {
            "low": {
                "1h": 3.0,     # 3% max hourly change
                "24h": 8.0,    # 8% max daily change
                "7d": 15.0     # 15% max weekly change
            },
            "medium": {
                "1h": 5.0,
                "24h": 15.0,
                "7d": 30.0
            },
            "high": {
                "1h": 8.0,
                "24h": 25.0,
                "7d": 50.0
            }
        }
        
        # Quality Score Minimum Requirements
        self.min_quality_score = {
            "low": 70,      # Minimum score requirements
            "medium": 60,
            "high": 45
        }

    def get_all_tokens(self) -> List[Dict]:
        """Fetch token data from CMC with error handling and logging"""
        try:
            logging.info("Fetching token data from CoinMarketCap...")
            
            params = {
                "start": "1",
                "limit": 5000,
                "convert": "USD",
                "aux": "platform,tags,date_added,circulating_supply,total_supply,max_supply,cmc_rank,num_market_pairs"
            }
            
            response = requests.get(
                f"{API_URL_BASE}/cryptocurrency/listings/latest",
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()["data"]
            
            logging.info(f"Successfully fetched {len(data)} tokens")
            return data
            
        except Exception as e:
            logging.error(f"Error fetching tokens: {str(e)}")
            return []

    def calculate_quality_score(self, token: Dict, risk: str) -> float:
        """Calculate token quality score with detailed criteria"""
        try:
            score = 0
            usd_data = token["quote"]["USD"]
            
            # Market Cap Score (0-20)
            market_cap = usd_data["market_cap"]
            max_cap = self.risk_ranges[risk][1]
            score += min(20, (market_cap / max_cap) * 20)
            
            # Volume Score (0-20)
            volume_mcap_ratio = usd_data["volume_24h"] / market_cap
            ideal_ratio = sum(self.volume_mcap_limits[risk]) / 2
            volume_score = 20 * (1 - abs(volume_mcap_ratio - ideal_ratio)/ideal_ratio)
            score += max(0, volume_score)
            
            # Price Stability Score (0-20)
            changes = {
                "24h": abs(usd_data["percent_change_24h"]),
                "7d": abs(usd_data["percent_change_7d"])
            }
            stability_score = 20
            for period, change in changes.items():
                if change > self.max_volatility[risk][period]:
                    stability_score *= 0.5
            score += stability_score
            
            # Exchange Listings Score (0-20)
            min_pairs = {"low": 15, "medium": 8, "high": 3}
            pairs = token.get("num_market_pairs", 0)
            score += min(20, (pairs / min_pairs[risk]) * 20)
            
            # Age Score (0-20)
            listing_date = datetime.strptime(token["date_added"].split('T')[0], '%Y-%m-%d')
            age_days = (datetime.now() - listing_date).days
            min_age = self.min_age[risk]
            score += min(20, (age_days / min_age) * 20)
            
            logging.debug(f"Quality score for {token['symbol']}: {score}")
            return score
            
        except Exception as e:
            logging.error(f"Error calculating quality score: {str(e)}")
            return 0

    def initial_token_filter(self, token: Dict, risk: str) -> Tuple[bool, str]:
        """Initial quality filter with detailed feedback"""
        try:
            usd_data = token["quote"]["USD"]
            
            # Exclude Stablecoins
            if "stablecoin" in [tag.lower() for tag in token.get("tags", [])]:
                return False, "Token identified as a stablecoin."
            
            # Market Cap Check
            market_cap = usd_data["market_cap"]
            min_cap, max_cap = self.risk_ranges[risk]
            if not (min_cap <= market_cap <= max_cap):
                return False, f"Market cap ${market_cap:,.2f} outside range ${min_cap:,.2f}-${max_cap:,.2f}"

            # Volume Check
            volume_24h = usd_data["volume_24h"]
            if volume_24h < self.min_volume[risk]:
                return False, f"Volume ${volume_24h:,.2f} below minimum ${self.min_volume[risk]:,.2f}"

            # Age Check
            listing_date = datetime.strptime(token["date_added"].split('T')[0], '%Y-%m-%d')
            age_days = (datetime.now() - listing_date).days
            if age_days < self.min_age[risk]:
                return False, f"Age {age_days} days below minimum {self.min_age[risk]}"

            # Volatility Check
            for timeframe in ["1h", "24h", "7d"]:
                change = abs(usd_data.get(f"percent_change_{timeframe}", 0))
                if change > self.max_volatility[risk][timeframe]:
                    return False, f"{timeframe} change {change:.2f}% exceeds limit {self.max_volatility[risk][timeframe]}%"

            return True, "Passed initial filter"
            
        except Exception as e:
            return False, f"Error in filtering: {str(e)}"

    def get_investment_rating(self, token: Dict, risk: str) -> Dict:
        """Generate comprehensive investment analysis"""
        try:
            usd_data = token["quote"]["USD"]
            
            # Calculate metrics
            volume_mcap = usd_data["volume_24h"] / usd_data["market_cap"]
            listing_date = datetime.strptime(token["date_added"].split('T')[0], '%Y-%m-%d')
            age_days = (datetime.now() - listing_date).days
            
            strengths = []
            weaknesses = []
            opportunities = []
            risks = []
            
            # Analyze Market Position
            if token.get("cmc_rank", 1000) <= 300:
                strengths.append(f"Strong market position (Rank #{token['cmc_rank']})")
            
            if age_days > 365:
                strengths.append(f"Well-established ({age_days/365:.1f} years old)")
            
            # Volume Analysis
            if volume_mcap >= self.volume_mcap_limits[risk][0]:
                strengths.append(f"Healthy trading volume ({volume_mcap*100:.1f}% of market cap)")
            else:
                weaknesses.append("Lower than ideal trading volume")
            
            # Price Movement Analysis
            if usd_data["percent_change_7d"] > 0:
                opportunities.append(f"Positive 7-day trend (+{usd_data['percent_change_7d']:.1f}%)")
            else:
                risks.append(f"Negative 7-day trend ({usd_data['percent_change_7d']:.1f}%)")
            
            # Utility Analysis
            tags = [t.lower() for t in token.get("tags", [])]
            utility_tags = ["defi", "nft", "gaming", "layer-2", "governance"]
            token_utilities = [t for t in tags if t in utility_tags]
            
            if token_utilities:
                strengths.append(f"Clear utility: {', '.join(token_utilities)}")
            else:
                weaknesses.append("Limited clear utility cases")
            
            return {
                "strengths": strengths,
                "weaknesses": weaknesses,
                "opportunities": opportunities,
                "risks": risks
            }
            
        except Exception as e:
            logging.error(f"Error in investment analysis: {str(e)}")
            return {
                "strengths": [],
                "weaknesses": [],
                "opportunities": [],
                "risks": []
            }

    def analyze_tokens(self, tokens: List[Dict], risk: str) -> List[Dict]:
        """Analyze and filter tokens with detailed statistics"""
        analyzed_tokens = []
        rejected_counts = {
            "market_cap": 0,
            "volume": 0,
            "age": 0,
            "volatility": 0,
            "quality_score": 0,
            "other": 0
        }
        
        logging.info(f"\nAnalyzing {len(tokens)} tokens...")
        
        for token in tokens:
            try:
                # Initial filter
                passed, reason = self.initial_token_filter(token, risk)
                if not passed:
                    if "market cap" in reason.lower():
                        rejected_counts["market_cap"] += 1
                    elif "volume" in reason.lower():
                        rejected_counts["volume"] += 1
                    elif "age" in reason.lower():
                        rejected_counts["age"] += 1
                    elif "change" in reason.lower():
                        rejected_counts["volatility"] += 1
                    elif "stablecoin" in reason.lower():
                        rejected_counts["other"] += 1
                    else:
                        rejected_counts["other"] += 1
                    continue
                
                # Quality score check
                quality_score = self.calculate_quality_score(token, risk)
                if quality_score < self.min_quality_score[risk]:
                    rejected_counts["quality_score"] += 1
                    continue
                
                # Create analyzed token data
                analyzed_token = {
                    "name": token["name"],
                    "symbol": token["symbol"],
                    "market_cap": token["quote"]["USD"]["market_cap"],
                    "price": token["quote"]["USD"]["price"],
                    "volume_24h": token["quote"]["USD"]["volume_24h"],
                    "percent_change_24h": token["quote"]["USD"]["percent_change_24h"],
                    "percent_change_7d": token["quote"]["USD"]["percent_change_7d"],
                    "volume_to_mcap": token["quote"]["USD"]["volume_24h"] / token["quote"]["USD"]["market_cap"],
                    "quality_score": quality_score,
                    "cmc_rank": token.get("cmc_rank", "N/A"),
                    "date_added": token["date_added"].split("T")[0],
                    "tags": token.get("tags", []),
                    "analysis": self.get_investment_rating(token, risk)
                }
                
                analyzed_tokens.append(analyzed_token)
                
            except Exception as e:
                logging.error(f"Error analyzing token: {str(e)}")
                rejected_counts["other"] += 1
                continue
        
        # Print rejection statistics
        print("\nFiltering Statistics:")
        print(f"Total tokens analyzed: {len(tokens)}")
        print(f"Rejected due to market cap: {rejected_counts['market_cap']}")
        print(f"Rejected due to volume: {rejected_counts['volume']}")
        print(f"Rejected due to age: {rejected_counts['age']}")
        print(f"Rejected due to volatility: {rejected_counts['volatility']}")
        print(f"Rejected due to quality score: {rejected_counts['quality_score']}")
        print(f"Rejected due to other reasons: {rejected_counts['other']}")
        print(f"Tokens passing all criteria: {len(analyzed_tokens)}")
        
        return sorted(analyzed_tokens, key=lambda x: x["quality_score"], reverse=True)

def format_price(price: float) -> str:
    """Format price with scientific notation for very small numbers"""
    if price < 0.00001:  # For very small numbers
        # Convert to scientific notation and split into base and exponent
        sci = f"{price:e}".split('e')
        base = float(sci[0])
        exponent = int(sci[1])
        return f"${base:.2f}×10^{exponent}"
    else:
        return f"${price:.8f}"

def print_token_info(token: Dict):
    """Print detailed token analysis with improved price formatting"""
    print(f"\n{'='*60}")
    print(f"{token['name']} ({token['symbol']})")
    print(f"{'='*60}")
    
    print(f"💰 Market Cap: ${token['market_cap']:,.2f}")
    print(f"💲 Price: {format_price(token['price'])}")
    print(f"📊 24h Volume: ${token['volume_24h']:,.2f}")
    print(f"📈 24h Change: {token['percent_change_24h']:+.2f}%")
    print(f"📈 7d Change: {token['percent_change_7d']:+.2f}%")
    print(f"📊 Quality Score: {token['quality_score']:.2f}/100")
    print(f"🔄 Volume/MCap Ratio: {token['volume_to_mcap']:.4f}")
    print(f"🏆 CMC Rank: #{token['cmc_rank']}")
    print(f"📅 Listed: {token['date_added']}")
    
    if token['tags']:
        print(f"🏷️ Tags: {', '.join(token['tags'][:5])}")
    
    analysis = token["analysis"]
    print("\n📈 Investment Analysis:")
    
    if analysis["strengths"]:
        print("\n💪 Strengths:")
        for strength in analysis["strengths"]:
            print(f"  ✓ {strength}")
    
    if analysis["weaknesses"]:
        print("\n⚠️ Weaknesses:")
        for weakness in analysis["weaknesses"]:
            print(f"  • {weakness}")
    
    if analysis["opportunities"]:
        print("\n🎯 Opportunities:")
        for opportunity in analysis["opportunities"]:
            print(f"  ✓ {opportunity}")
    
    if analysis["risks"]:
        print("\n⚠️ Risks:")
        for risk in analysis["risks"]:
            print(f"  • {risk}")
def log_recommendations(tokens: List[Dict], chain: str, risk: str):
    """Log token recommendations with timestamp and details"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"token_recommendations_{timestamp}.txt"
        
        with open(filename, "w") as f:
            # Write header
            f.write(f"Token Analysis Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Blockchain: {chain}\n")
            f.write(f"Risk Level: {risk.capitalize()}\n")
            f.write("="*80 + "\n\n")
            
            # Write each token's details
            for idx, token in enumerate(tokens, 1):
                f.write(f"#{idx} {token['name']} ({token['symbol']})\n")
                f.write(f"Price: {format_price(token['price'])}\n")
                f.write(f"Market Cap: ${token['market_cap']:,.2f}\n")
                f.write(f"24h Volume: ${token['volume_24h']:,.2f}\n")
                f.write(f"24h Change: {token['percent_change_24h']:+.2f}%\n")
                f.write(f"7d Change: {token['percent_change_7d']:+.2f}%\n")
                f.write(f"Quality Score: {token['quality_score']:.2f}\n")
                f.write(f"CMC Rank: #{token['cmc_rank']}\n")
                f.write(f"Listed Date: {token['date_added']}\n")
                
                if token.get('tags'):
                    f.write(f"Tags: {', '.join(token['tags'][:5])}\n")
                
                # Write analysis
                analysis = token['analysis']
                if analysis['strengths']:
                    f.write("\nStrengths:\n")
                    for strength in analysis['strengths']:
                        f.write(f"✓ {strength}\n")
                        
                if analysis['weaknesses']:
                    f.write("\nWeaknesses:\n")
                    for weakness in analysis['weaknesses']:
                        f.write(f"• {weakness}\n")
                        
                if analysis['opportunities']:
                    f.write("\nOpportunities:\n")
                    for opportunity in analysis['opportunities']:
                        f.write(f"✓ {opportunity}\n")
                        
                if analysis['risks']:
                    f.write("\nRisks:\n")
                    for risk in analysis['risks']:
                        f.write(f"• {risk}\n")
                
                f.write("\n" + "-"*40 + "\n\n")
            
            # Write footer
            f.write("\nNote: This analysis is for informational purposes only. Always DYOR!\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        print(f"\n📝 Recommendations logged to: {filename}")
        
    except Exception as e:
        logging.error(f"Error logging recommendations: {str(e)}")
        print("❌ Failed to log recommendations.")

def is_stablecoin(token: Dict) -> bool:
    """Check if a token is a stablecoin"""
    try:
        # Check tags for stablecoin indicators
        tags = [t.lower() for t in token.get("tags", [])]
        stablecoin_tags = ["stablecoin", "stablecoins"]
        if any(tag in tags for tag in stablecoin_tags):
            return True
            
        # Check name and symbol for common stablecoin indicators
        name_lower = token["name"].lower()
        symbol_lower = token["symbol"].lower()
        stable_indicators = ["usd", "eur", "gbp", "usdt", "usdc", "dai", "busd", "tusd"]
        
        if any(indicator in name_lower for indicator in stable_indicators):
            return True
            
        if any(indicator in symbol_lower for indicator in stable_indicators):
            return True
            
        # Check if price is pegged (usually around $1)
        price = token["quote"]["USD"]["price"]
        if 0.95 <= price <= 1.05:  # Common stablecoin price range
            volatility_30d = abs(token["quote"]["USD"].get("percent_change_30d", 0))
            if volatility_30d < 5:  # Stablecoins typically have very low volatility
                return True
        
        return False
        
    except Exception as e:
        logging.error(f"Error checking stablecoin: {str(e)}")
        return False
def log_recommendations(tokens: List[Dict], chain: str, risk: str):
    """Log token recommendations with timestamp and details"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"token_recommendations_{timestamp}.txt"
        
        with open(filename, "w", encoding='utf-8') as f:  # Add UTF-8 encoding
            # Write header
            f.write(f"Token Analysis Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Blockchain: {chain}\n")
            f.write(f"Risk Level: {risk.capitalize()}\n")
            f.write("="*80 + "\n\n")
            
            # Write each token's details
            for idx, token in enumerate(tokens, 1):
                f.write(f"#{idx} {token['name']} ({token['symbol']})\n")
                f.write(f"Price: {format_price(token['price'])}\n")
                f.write(f"Market Cap: ${token['market_cap']:,.2f}\n")
                f.write(f"24h Volume: ${token['volume_24h']:,.2f}\n")
                f.write(f"24h Change: {token['percent_change_24h']:+.2f}%\n")
                f.write(f"7d Change: {token['percent_change_7d']:+.2f}%\n")
                f.write(f"Quality Score: {token['quality_score']:.2f}\n")
                f.write(f"CMC Rank: #{token['cmc_rank']}\n")
                f.write(f"Listed Date: {token['date_added']}\n")
                
                if token.get('tags'):
                    f.write(f"Tags: {', '.join(token['tags'][:5])}\n")
                
                # Write analysis using ASCII characters instead of special ones
                analysis = token['analysis']
                if analysis['strengths']:
                    f.write("\nStrengths:\n")
                    for strength in analysis['strengths']:
                        f.write(f"+ {strength}\n")
                        
                if analysis['weaknesses']:
                    f.write("\nWeaknesses:\n")
                    for weakness in analysis['weaknesses']:
                        f.write(f"- {weakness}\n")
                        
                if analysis['opportunities']:
                    f.write("\nOpportunities:\n")
                    for opportunity in analysis['opportunities']:
                        f.write(f"+ {opportunity}\n")
                        
                if analysis['risks']:
                    f.write("\nRisks:\n")
                    for risk in analysis['risks']:
                        f.write(f"- {risk}\n")
                
                f.write("\n" + "-"*40 + "\n\n")
            
            # Write footer
            f.write("\nNote: This analysis is for informational purposes only. Always DYOR!\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        print(f"\n📝 Recommendations logged to: {filename}")
        
    except Exception as e:
        logging.error(f"Error logging recommendations: {str(e)}")
        print("❌ Failed to log recommendations.")
           
def main():
    print("\n🚀 Enhanced Token Analysis Engine 4.0 🔍")
    
    chain_options = {"1": "Ethereum", "2": "Solana"}
    print("\n🌐 Select Blockchain:")
    for key, chain in chain_options.items():
        print(f"{key}. {chain}")
    
    while True:
        chain_choice = input("\nChoose blockchain (1-2): ").strip()
        if chain_choice in chain_options:
            chain = chain_options[chain_choice]
            break
        print("❌ Invalid choice. Please select 1 or 2.")
    
    risk_options = {"1": "low", "2": "medium", "3": "high"}
    print("\n⚖️ Risk Level:")
    print("1. Low Risk ($100M-$1B)")
    print("2. Medium Risk ($25M-$100M)")
    print("3. High Risk ($1M-$25M)")
    
    while True:
        risk_choice = input("\nSelect risk level (1-3): ").strip()
        if risk_choice in risk_options:
            risk = risk_options[risk_choice]
            break
        print("❌ Invalid choice. Please select 1, 2, or 3.")
    
    analyzer = TokenAnalyzer(API_KEY)
    print(f"\n🔍 Scanning {chain} ecosystem for {risk.capitalize()} Risk tokens...")
    
    all_tokens = analyzer.get_all_tokens()
    if not all_tokens:
        print("❌ Failed to fetch token data. Please try again.")
        return

    # Improved chain filtering
    filtered_tokens = []
    rejected_stablecoins = 0
    
    for token in all_tokens:
        try:
            # Skip stablecoins
            if is_stablecoin(token):
                rejected_stablecoins += 1
                continue
            
            # Check platform
            platform = token.get("platform", {})
            
            # For Ethereum tokens
            if chain.lower() == "ethereum":
                # Check if token is native ETH
                if token["symbol"].lower() == "eth":
                    filtered_tokens.append(token)
                    continue
                    
                # Check if token is on Ethereum
                if platform and (
                    platform.get("name", "").lower() == "ethereum" or
                    platform.get("symbol", "").lower() == "eth"
                ):
                    filtered_tokens.append(token)
                    continue
                
                # Check tags for ERC20, etc.
                tags = [t.lower() for t in token.get("tags", [])]
                eth_indicators = ["ethereum", "erc-20", "erc20", "eth"]
                if any(indicator in tags for indicator in eth_indicators):
                    filtered_tokens.append(token)
                    continue
            
            # For Solana tokens
            elif chain.lower() == "solana":
                # Check if token is native SOL
                if token["symbol"].lower() == "sol":
                    filtered_tokens.append(token)
                    continue
                    
                # Check if token is on Solana
                if platform and (
                    platform.get("name", "").lower() == "solana" or
                    platform.get("symbol", "").lower() == "sol"
                ):
                    filtered_tokens.append(token)
                    continue
                
                # Check tags for SPL tokens
                tags = [t.lower() for t in token.get("tags", [])]
                sol_indicators = ["solana", "spl", "sol"]
                if any(indicator in tags for indicator in sol_indicators):
                    filtered_tokens.append(token)
                    continue
                    
        except Exception as e:
            logging.error(f"Error filtering token: {str(e)}")
            continue

    if not filtered_tokens:
        print(f"❌ No tokens found for {chain}.")
        return
        
    print(f"Found {len(filtered_tokens)} tokens for {chain} (excluded {rejected_stablecoins} stablecoins), analyzing...")
    
    analyzed_tokens = analyzer.analyze_tokens(filtered_tokens, risk)
    
    if analyzed_tokens:
        print(f"\n✨ Found {len(analyzed_tokens)} quality tokens matching criteria.")
        print("\nTop tokens by quality score:")
        for idx, token in enumerate(analyzed_tokens[:10], 1):
            print(f"\n#{idx}")
            print_token_info(token)
            
        # Log recommendations
        log_recommendations(analyzed_tokens[:10], chain, risk)
    else:
        print("\n❌ No tokens found matching criteria. Try adjusting risk level.")

    print("\n💡 Note: Always conduct your own research before making investment decisions.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProgram terminated by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        print("\n❌ An error occurred. Please try again.")