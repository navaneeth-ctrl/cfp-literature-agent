# 📚 CFP Literature Agent

Automatically monitors **call-for-papers.sas.upenn.edu** for new
literature-related Calls for Papers and emails you a daily digest.

Runs for free on **GitHub Actions** — no server needed.

---

## What it monitors

All literature-focused categories on the CFP site:

| Category | Category |
|---|---|
| African-American | American |
| Children's Literature | Classical Studies |
| Cultural Studies & Historical Approaches | Ecocriticism & Environmental Studies |
| Eighteenth Century | Ethnicity & National Identity |
| Film & Television | Gender Studies & Sexuality |
| Interdisciplinary | International Conferences |
| Journals & Collections of Essays | Medieval |
| Modernist Studies | Online Conferences |
| Poetry | Popular Culture |
| Postcolonial | Renaissance |
| Romantic | Science & Culture |
| Theory | Translation Studies |
| Travel Writing | Twentieth Century & Beyond |
| Victorian | World Literatures & Indigenous Studies |

It also runs a keyword-filtered pass over **all recent posts** to catch anything
not yet assigned to a category.

---

## Setup (5 minutes)

### 1 — Fork / create the repository

Push this entire folder to a new **private** GitHub repository.

```
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/cfp-literature-agent.git
git push -u origin main
```

### 2 — Create a Gmail App Password

> Your real Gmail password will NOT work. You must use an App Password.

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** (required)
3. Go to **Security → App Passwords**
4. Choose app: **Mail** | device: **Other** → name it `cfp-agent`
5. Copy the 16-character password

### 3 — Add GitHub Secrets

In your repo go to **Settings → Secrets and variables → Actions → New repository secret**
and add these three secrets:

| Secret name | Value |
|---|---|
| `RECIPIENT_EMAIL` | Your email address (where you want alerts) |
| `SENDER_EMAIL` | The Gmail address that will send the emails |
| `SENDER_PASSWORD` | The 16-character App Password from step 2 |

### 4 — Enable Actions write permissions

In your repo go to **Settings → Actions → General → Workflow permissions**
and select **Read and write permissions** (so the bot can commit `seen_cfps.json`).

### 5 — Run it!

Go to **Actions → CFP Literature Agent → Run workflow** to trigger it manually
for the first time and verify your email arrives.

After that it runs **automatically every day at 08:00 UTC (1:30 PM IST)**.

---

## How it works

```
GitHub Actions (daily cron)
        │
        ▼
cfp_agent.py
  ├─ load seen_cfps.json          ← which CFPs were already emailed
  ├─ scrape each literature category (all pages)
  ├─ scrape "all" with keyword filter (catch-all)
  ├─ deduplicate by URL
  ├─ if new CFPs found → send HTML email digest via Gmail SMTP
  └─ update seen_cfps.json → commit back to repo
```

`seen_cfps.json` is committed back to the repo after each run, so the next
scheduled run knows exactly which posts have already been sent. You will never
receive a duplicate notification.

---

## Customisation

**Change the schedule** — edit the `cron` line in `.github/workflows/cfp_agent.yml`:
```yaml
- cron: "0 8 * * *"   # daily at 08:00 UTC
- cron: "0 8 * * 1"   # weekly on Mondays
```

**Add/remove categories** — edit the `LITERATURE_CATEGORIES` list in `cfp_agent.py`.

**Tune keyword filtering** — edit `LITERATURE_KEYWORDS` in `cfp_agent.py`.

---

## Files

```
cfp-literature-agent/
├── cfp_agent.py               # main script
├── requirements.txt           # Python dependencies
├── seen_cfps.json             # auto-updated state (committed by bot)
├── .github/
│   └── workflows/
│       └── cfp_agent.yml      # GitHub Actions schedule
└── README.md
```
