def calculate_quantity(capital, risk_pct, entry, stop, max_position_value):
    capital, entry, stop = float(capital), float(entry), float(stop)
    if capital <= 0 or entry <= 0 or float(max_position_value) <= 0:
        return 0
    risk_amount = capital * (float(risk_pct) / 100.0)
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return 0
    qty_by_risk = int(risk_amount / risk_per_share)
    qty_by_value = int(float(max_position_value) / entry)
    return max(0, min(qty_by_risk, qty_by_value))
