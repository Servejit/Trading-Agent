# Scheduled paper-trading setup

The scheduled runner uses GitHub Actions. It is **paper trading only**: it never sends broker orders or uses a brokerage account.

## One-time setup

### 1. Create a GitHub fine-grained token for the app
1. Open GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens.
2. Generate a token restricted to the `Servejit/Trading-Agent` repository.
3. Grant **Contents: Read and write**. Metadata read is granted automatically.
4. Copy the token once. Never commit it or send it in chat.

### 2. Add the app token as a Codespaces secret
1. Open GitHub Settings → Codespaces → Secrets.
2. Create `TRADING_AGENT_GITHUB_TOKEN` and paste the token value.
3. Allow access to the `Trading-Agent` repository.
4. Restart the Codespace so the secret becomes an environment variable.

### 3. Generate an encryption key
In the Codespaces terminal, run:

```bash
pip install -r requirements.txt
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the generated key. Keep it private. Use the exact same key in both locations below.

### 4. Add the encryption key in both locations
- **Codespaces secret:** GitHub Settings → Codespaces → Secrets → create `TRADING_AGENT_ENCRYPTION_KEY`; allow access to `Trading-Agent`.
- **Repository Actions secret:** open `Servejit/Trading-Agent` → Settings → Secrets and variables → Actions → New repository secret; name it `TRADING_AGENT_ENCRYPTION_KEY` and paste the same key.

Restart the Codespace after creating or changing Codespaces secrets.

### 5. Save a plan again
Open the Streamlit app, enter the stock symbol and quantity, choose the date and times, then press **Fetch previous close & save plan**. The app should report that the plan synced to GitHub. If it says local-only or sync failed, scheduled trading will not have your new plan.

### 6. Check the workflow
Open the repository's **Actions** tab and select **Scheduled Paper Trader**. GitHub Actions must be enabled. It runs on weekdays in the morning (UTC schedule converted by the script to India time); scheduled runs can be delayed or skipped.

## How the simulation behaves

- The app calculates the planned buy limit as the previous completed NSE daily close + 1.99%.
- Between the planned buy time and sell time, the runner checks Yahoo Finance's latest available intraday quote. It records a simulated buy only when a quote is available at or below the limit.
- At/after the planned sell time, it attempts a simulated sell only if a buy was recorded, using the same symbol and filled quantity.
- If the buy never fills before the sell time, no sell is attempted. If a sell quote is unavailable, the runner retries on later scheduled runs.
- The encrypted plan and result are stored in the repository; keep the encryption key secret. The app needs the key to read the result.
- Yahoo Finance data can be missing or delayed, and GitHub Actions is not an exact-time trading engine. The NSE cash market's regular session starts at 9:15 AM IST, so a usable quote may not exist at 9:00 AM.

No actual orders are sent. P&L is a gross simulation before fees, taxes, slippage, and other costs.
