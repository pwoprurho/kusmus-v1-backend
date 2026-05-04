# kushub/skills/real_estate_roi.py
"""
KUSMUS Skill — Real Estate ROI Calculator
Calculates investment returns for Nigerian properties.
"""

def run(params):
    purchase_price = params.get('purchase_price', 0)
    location = params.get('location', 'Other')
    property_type = params.get('property_type', 'Apartment')
    monthly_rent = params.get('monthly_rent', 0)
    holding_period = params.get('holding_period_years', 5)
    renovation_cost = params.get('renovation_cost', 0)

    # Location-based appreciation rates (annual %)
    appreciation_rates = {
        'Lagos-Island': 15.0,
        'Lagos-Mainland': 12.0,
        'Abuja-CBD': 14.0,
        'Abuja-Suburb': 10.0,
        'Port-Harcourt': 9.0,
        'Ibadan': 8.0,
        'Other': 6.0
    }

    # Location-based premium multiplier
    location_premium = {
        'Lagos-Island': 1.25,
        'Lagos-Mainland': 1.10,
        'Abuja-CBD': 1.20,
        'Abuja-Suburb': 1.05,
        'Port-Harcourt': 1.08,
        'Ibadan': 1.02,
        'Other': 1.0
    }

    annual_appreciation = appreciation_rates.get(location, 6.0) / 100.0
    premium = location_premium.get(location, 1.0)

    total_investment = purchase_price + renovation_cost
    
    # Calculate future value based on appreciation
    future_value = total_investment * ((1 + annual_appreciation) ** holding_period)
    capital_gains = future_value - total_investment
    
    # Calculate rental income
    # Factoring in 5% annual rent increment in Nigeria
    total_rental_income = 0
    current_rent = monthly_rent * 12
    for _ in range(holding_period):
        total_rental_income += current_rent
        current_rent *= 1.05 # 5% increase per year

    net_profit = capital_gains + total_rental_income
    
    if total_investment <= 0:
        return {
            "success": False,
            "error": "Total investment must be greater than zero."
        }

    total_roi_percentage = (net_profit / total_investment) * 100
    annualized_roi = ((1 + (net_profit / total_investment)) ** (1 / holding_period) - 1) * 100

    return {
        "success": True,
        "summary": f"Investment in {location} {property_type} projected to yield {annualized_roi:.2f}% annually over {holding_period} years.",
        "metrics": {
            "total_investment": total_investment,
            "future_value": future_value,
            "capital_gains": capital_gains,
            "total_rental_income": total_rental_income,
            "net_profit": net_profit,
            "total_roi_percentage": total_roi_percentage,
            "annualized_roi": annualized_roi
        },
        "location_stats": {
            "appreciation_rate": annual_appreciation * 100,
            "location_premium": premium
        }
    }
