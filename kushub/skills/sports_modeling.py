# kushub/skills/sports_modeling.py
"""
KUSMUS Skill — Sports Prediction Model
Statistical modeling for football match outcomes.
"""
import random

def run(params):
    home_team = params.get('home_team', 'Home')
    away_team = params.get('away_team', 'Away')
    league = params.get('league', 'Other')
    home_form = params.get('home_form', 'WWDLW')
    away_form = params.get('away_form', 'WDWLL')

    # Convert form to numerical score
    def calculate_form_score(form_str):
        mapping = {'W': 3, 'D': 1, 'L': 0}
        return sum(mapping.get(c, 0) for c in form_str[-5:])

    home_score = calculate_form_score(home_form)
    away_score = calculate_form_score(away_form)

    # Base win probabilities
    total_score = home_score + away_score + 1 # avoid division by zero
    
    # Factor in Home Advantage (usually +15%)
    home_prob = (home_score / total_score) * 0.70 + 0.15
    away_prob = (away_score / total_score) * 0.70
    draw_prob = 1.0 - (home_prob + away_prob)

    # Normalize
    total_prob = home_prob + away_prob + draw_prob
    home_prob /= total_prob
    away_prob /= total_prob
    draw_prob /= total_prob

    # Predicted Scoreline (Simulated)
    home_goals = random.choices([0, 1, 2, 3, 4], weights=[0.2, 0.4, 0.2, 0.1, 0.1])[0]
    away_goals = random.choices([0, 1, 2, 3], weights=[0.4, 0.3, 0.2, 0.1])[0]

    return {
        "success": True,
        "summary": f"In the {league} clash, {home_team} has a {home_prob*100:.1f}% win probability against {away_team}.",
        "predictions": {
            "win_probability": {
                "home": round(home_prob, 2),
                "draw": round(draw_prob, 2),
                "away": round(away_prob, 2)
            },
            "projected_score": f"{home_goals} - {away_goals}",
            "confidence_level": "Medium-High",
            "key_insight": f"{home_team}'s superior home form ({home_form}) is the deciding factor." if home_score > away_score else f"{away_team} is a dangerous away side with {away_form} form."
        }
    }
