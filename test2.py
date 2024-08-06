from flask import Flask, jsonify, request
import yfinance as yf
import math

app = Flask(__name__)

CURRENT_TARGET_RATE = 5.25  # Current target Fed Funds Rate in %
RATE_CHANGE = 0.25  # Rate change increment in %
CURRENT_MONTH = 8  # Current month is August

# FOMC meeting months and their respective dates for the remaining year
FOMC_MEETING_DATES = {
    9: 17,  # September 17th
    11: 6,  # November 6th
    12: 13  # December 13th
}
# Non-meeting months for the remaining year
NON_MEETING_MONTHS = [8, 10]

def fetch_futures_contract_price(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period='1mo')
        if data.empty:
            return None
        current_price = data['Close'].iloc[-1]
        return current_price
    except Exception as e:
        print(f"Error fetching data for {ticker_symbol}: {e}")
        return None

def calculate_implied_rate(contract_price):
    return 100 - contract_price

def calculate_probabilities(start_rate, end_rate):
    expected_change = end_rate - start_rate
    num_changes = expected_change / RATE_CHANGE

    # Separate the number of changes into its whole and fractional parts
    whole_changes = math.floor(num_changes)
    fractional_change = abs(num_changes - whole_changes)

    if expected_change < 0:
        # Probabilities for rate cuts
        prob_whole_change = 1 - fractional_change
        prob_next_change = fractional_change
    else:
        # Probabilities for rate hikes
        prob_whole_change = fractional_change
        prob_next_change = 1 - fractional_change

    return whole_changes, prob_whole_change, prob_next_change

def adjust_for_meeting_day(current_rate, rate_change, meeting_day, days_in_month):
    avg_rate_hike = ((meeting_day * current_rate) + ((days_in_month - meeting_day) * (current_rate + rate_change))) / days_in_month
    avg_rate_cut = ((meeting_day * current_rate) + ((days_in_month - meeting_day) * (current_rate - rate_change))) / days_in_month
    return avg_rate_hike, avg_rate_cut

@app.route('/calculate', methods=['GET'])
def calculate():
    implied_rates = {}
    effr_end = {}
    effr_start = {}
    ticker_symbols = {
        8: 'ZQQ24.CBT', 9: 'ZQU24.CBT', 10: 'ZQV24.CBT',
        11: 'ZQX24.CBT', 12: 'ZQZ24.CBT'
    }

    output = []

    # Fetch contract prices and implied rates for all months
    for month in ticker_symbols.keys():
        ticker_symbol = ticker_symbols[month]
        contract_price = fetch_futures_contract_price(ticker_symbol)
        if contract_price is not None:
            implied_rates[month] = calculate_implied_rate(contract_price)
            output.append({
                "Month": month,
                "Ticker": ticker_symbol,
                "Contract Price": contract_price,
                "Implied Rate": implied_rates[month]
            })
        else:
            output.append({
                "Month": month,
                "Ticker": ticker_symbol,
                "Error": "Missing data"
            })

    # Calculate EFFR(End) for non-meeting months
    for i, month in enumerate(NON_MEETING_MONTHS):
        if month not in implied_rates:
            continue
        effr_end[month] = implied_rates[month]
        if i > 0:
            prev_month = NON_MEETING_MONTHS[i - 1]
            effr_start[month] = effr_end[prev_month]
        if i < len(NON_MEETING_MONTHS) - 1:
            next_month = NON_MEETING_MONTHS[i + 1]
            effr_start[next_month] = effr_end[month]
        effr_start_str = f"{effr_start.get(month, 'N/A'):.3f}" if month in effr_start else 'N/A'
        output.append({
            "Non-Meeting Month": month,
            "EFFR Start": effr_start_str,
            "EFFR End": effr_end[month]
        })

    # Adjust for FOMC meeting months
    for month, meeting_day in FOMC_MEETING_DATES.items():
        days_in_month = 30  # Assuming 30 days in each month for simplicity
        if month == 12:  # December has 31 days
            days_in_month = 31

        prev_month = month - 1
        if prev_month in effr_end:
            effr_start[month] = effr_end[prev_month]
        else:
            effr_start[month] = CURRENT_TARGET_RATE

        implied_rate = implied_rates.get(month)
        if implied_rate is None:
            continue

        n_days_before_meeting = meeting_day - 1
        n_days_after_meeting = days_in_month - n_days_before_meeting

        effr_end[month] = (implied_rate - (n_days_before_meeting / (n_days_before_meeting + n_days_after_meeting)) * effr_start[month]) / (n_days_after_meeting / (n_days_before_meeting + n_days_after_meeting))

        output.append({
            "Meeting Month": month,
            "Implied Rate": implied_rate,
            "EFFR Start": effr_start[month],
            "EFFR End": effr_end[month],
            "Days before meeting": n_days_before_meeting,
            "Days after meeting": n_days_after_meeting
        })

    # Calculate probabilities for FOMC meeting months
    for month in FOMC_MEETING_DATES.keys():
        if month not in effr_start or month not in effr_end:
            continue
        start_rate = effr_start[month]
        end_rate = effr_end[month]
        whole_changes, prob_whole_change, prob_next_change = calculate_probabilities(start_rate, end_rate)

        if end_rate < start_rate:
            output.append({
                "Probability Month": month,
                "Start Rate": start_rate,
                "End Rate": end_rate,
                "Whole Cuts": whole_changes,
                "Probability of whole cuts": prob_whole_change,
                "Probability of next cuts": prob_next_change
            })
        else:
            output.append({
                "Probability Month": month,
                "Start Rate": start_rate,
                "End Rate": end_rate,
                "Whole Hikes": whole_changes,
                "Probability of whole hikes": prob_next_change,
                "Probability of next hikes": prob_whole_change
            })

    return jsonify(output)

if __name__ == '__main__':
    app.run(debug=True)
