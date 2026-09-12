# Philly Godfather Pick Monitor

Checks the members-area picks table every 15 minutes and emails you when a
new row is posted. Runs entirely on GitHub Actions — no server needed.

## How it works

- `monitor.py` logs into the members area, reads the picks table, and
  fingerprints each row (`date + exact text`).
- Row history is stored in a **private GitHub Gist** (not this repo), so it
  stays private even though this repo itself is public.
- New rows trigger an email via Gmail.
- The script exits immediately — no login, no site request — between
  **12am and 6am Central**, so those hours cost nothing and put no load
  on the site.
- Runs on a schedule every 15 minutes via GitHub Actions
  (`.github/workflows/check.yml`). This repo is public specifically so
  Actions minutes are unlimited/free — none of your credentials or the
  pick history are exposed by that; they live in encrypted Secrets and
  the private Gist respectively.

### On pick splitting

Some rows use `/` between picks, some just use spaces, and a few (teasers,
ticket-number rows) aren't cleanly separable at all. The script only
splits on `/`. Anything without that delimiter is stored whole with
`needs_manual_split: true` rather than guessed at — so nothing silently
gets mis-graded later. You can see exactly which rows still need a human
look by checking that flag in the Gist's `last_seen.json`.

## One-time setup

### 1. Create the repo
Push this folder to a new **public** GitHub repo.

### 2. Create a private Gist for state storage
Go to https://gist.github.com/, create any placeholder file (e.g.
`last_seen.json` with content `[]`), and set visibility to **secret**
(not public). Save it, then copy the Gist ID from its URL:
`https://gist.github.com/<your-username>/<GIST_ID>`

### 3. Create a GitHub Personal Access Token (for Gist access only)
Go to https://github.com/settings/tokens → generate a new **fine-grained**
token scoped only to **Gists: Read and write**. Copy the token — you won't
see it again.

### 4. Create a Gmail App Password
If you don't already use 2-Step Verification on the Gmail account you want
to send from, turn it on first. Then go to
https://myaccount.google.com/apppasswords, create an app password, and
copy the 16-character code.

### 5. Add repo secrets
In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these:

| Secret            | Value                                      |
|--------------------|---------------------------------------------|
| `SITE_USERNAME`    | Your Philly Godfather members-area username |
| `SITE_PASSWORD`    | Your Philly Godfather members-area password |
| `GIST_ID`          | The Gist ID from step 2                     |
| `GIST_TOKEN`       | The PAT from step 3                         |
| `GMAIL_USER`       | The Gmail address you're sending from       |
| `GMAIL_APP_PASSWORD` | The 16-char app password from step 4      |
| `ALERT_TO`         | Where alerts should be sent (can be same as `GMAIL_USER`) |

### 6. Test it
Go to the **Actions** tab → "Check for new picks" → **Run workflow**
(manual trigger). Check the run log to confirm it logs in and parses rows
successfully. After that, it runs automatically every 15 minutes.

## Local testing (optional)

```bash
pip install -r requirements.txt
export SITE_USERNAME=... SITE_PASSWORD=... GIST_ID=... GIST_TOKEN=...
export GMAIL_USER=... GMAIL_APP_PASSWORD=... ALERT_TO=...
python monitor.py
```
