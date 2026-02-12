# 📡 Solana Narrative Radar

**AI-powered detection of emerging narratives in the Solana ecosystem.**

Built for the [Superteam Earn — Narrative Detection Tool](https://earn.superteam.fun/listing/narrative-detection-tool/) bounty.

![Python](https://img.shields.io/badge/python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green) ![License](https://img.shields.io/badge/license-MIT-purple)

---

## 🧠 What It Does

Solana Narrative Radar continuously monitors multiple data sources across the Solana ecosystem, scores signals for significance, clusters them into narratives using AI, and generates actionable build ideas for each emerging trend.

**Example output:**
> 🔥 **DeFi Renaissance** (HIGH confidence, ACCELERATING)
> "Surge in new lending protocols and yield optimization tools on Solana, driven by 47 new GitHub repos and 3 protocols crossing $100M TVL this week."
>
> 💡 **Build Ideas:** YieldRadar (cross-protocol yield optimizer), DeFi Sentinel (risk monitor), PositionPilot (automated position management)

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────┐
│                  DATA COLLECTORS                  │
├──────────────┬───────────────┬───────────────────┤
│  🐙 GitHub   │  📈 DeFiLlama │  🐦 Social/KOL   │
│  New repos   │  TVL changes  │  Twitter trends   │
│  Star surges │  Protocol     │  Influencer       │
│  Fork waves  │  launches     │  mentions         │
├──────────────┴───────────────┴───────────────────┤
│              📊 SIGNAL SCORER                     │
│  Velocity · Convergence · Novelty · Authority    │
├──────────────────────────────────────────────────┤
│              🧠 NARRATIVE ENGINE                  │
│  LLM clustering (Claude) + Rule-based fallback   │
├──────────────────────────────────────────────────┤
│              💡 IDEA GENERATOR                    │
│  Actionable build suggestions per narrative      │
├──────────────────────────────────────────────────┤
│              🌐 DASHBOARD + API                   │
│  FastAPI server · Interactive web UI             │
└──────────────────────────────────────────────────┘
```

---

## 📊 Signal Scoring Methodology

Each signal is scored 0-100 based on four weighted factors:

| Factor | Weight | What It Measures |
|--------|--------|-----------------|
| **Convergence** | 40% | How many independent sources confirm the trend |
| **Velocity** | 30% | Speed of growth (stars, TVL, mentions over time) |
| **Novelty** | 20% | Is this genuinely new, or an existing narrative? |
| **Authority** | 10% | Signal source credibility (verified projects, top devs) |

Signals scoring >40 are passed to the narrative engine for clustering.

---

## 🔌 Data Sources

### GitHub Collector
- Monitors new Solana-related repositories (language: Rust, TypeScript)
- Tracks star velocity and fork patterns
- Identifies developer migration signals
- Uses GitHub API with automatic topic extraction

### DeFiLlama Collector
- Tracks TVL changes across all Solana DeFi protocols
- Detects new protocol launches
- Identifies category-level trends (lending, DEX, yield, etc.)
- API: `https://api.llama.fi/protocols`

### Social Collector
- Monitors Twitter/X for Solana KOL mentions
- Tracks trending topics and sentiment
- Identifies influencer-driven narratives

### Coming Soon
- **Helius**: On-chain transaction pattern analysis
- **Birdeye**: Token launch and trading volume data

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- GitHub token (for API rate limits)

### Local Setup

```bash
# Clone
git clone https://github.com/0xksure/solana-narrative-radar.git
cd solana-narrative-radar/backend

# Install dependencies
pip install -r requirements.txt

# Configure (create .env file)
cat > .env << EOF
GITHUB_TOKEN=your_github_token
ANTHROPIC_API_KEY=your_anthropic_key  # Optional: uses rule-based fallback if missing
EOF

# Run the pipeline (generates narrative report)
python run_pipeline.py

# Start the web server
uvicorn main:app --host 0.0.0.0 --port 8899

# Visit http://localhost:8899
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /` | GET | Dashboard UI |
| `GET /api/narratives` | GET | Latest narrative report |
| `POST /api/generate` | POST | Trigger new pipeline run |
| `GET /health` | GET | Health check |

---

## 🤖 AI Agent Architecture

This tool is built and operated by an **AI agent** (Max), demonstrating autonomous:
- **Data collection** across multiple APIs
- **Signal analysis** with weighted scoring
- **Narrative clustering** via LLM reasoning
- **Idea generation** with feasibility assessment
- **Deployment** to cloud infrastructure

The agent runs the full pipeline autonomously and can be triggered via API to generate fresh reports.

---

## 📁 Project Structure

```
solana-narrative-radar/
├── backend/
│   ├── main.py                  # FastAPI application
│   ├── run_pipeline.py          # Full pipeline runner
│   ├── requirements.txt         # Python dependencies
│   ├── collectors/
│   │   ├── github_collector.py  # GitHub API collector
│   │   ├── defi_collector.py    # DeFiLlama collector
│   │   └── social_collector.py  # Twitter/social collector
│   ├── engine/
│   │   ├── scorer.py            # Signal scoring engine
│   │   └── narrative_engine.py  # LLM narrative clustering
│   ├── api/
│   │   └── routes.py            # API route definitions
│   ├── static/
│   │   └── index.html           # Dashboard frontend
│   └── data/
│       └── latest_report.json   # Latest generated report
├── .do/
│   └── app.yaml                 # DigitalOcean App Platform spec
├── deploy.sh                    # Droplet deployment script
└── README.md
```

---

## 🌐 Deployment

### DigitalOcean App Platform (Recommended)
The app auto-deploys from GitHub on push. See `.do/app.yaml`.

### Manual Deployment
```bash
chmod +x deploy.sh
./deploy.sh  # Deploys to DO droplet via SSH
```

---

## 📈 Sample Report

From a real pipeline run (993 signals collected):

| # | Narrative | Confidence | Direction | Ideas |
|---|-----------|-----------|-----------|-------|
| 1 | DeFi | HIGH | ACCELERATING | 3 |
| 2 | Trading | MEDIUM | ACCELERATING | 2 |
| 3 | AI Agents | MEDIUM | EMERGING | 3 |
| 4 | Staking | LOW | EMERGING | 1 |
| 5 | Infrastructure | LOW | EMERGING | 2 |
| 6 | RWA | LOW | EMERGING | 1 |

---

## 🛠️ Tech Stack

- **Backend:** Python, FastAPI, httpx
- **AI:** Anthropic Claude (with rule-based fallback)
- **Data:** GitHub API, DeFiLlama API, Twitter/X
- **Frontend:** Vanilla HTML/CSS/JS (zero dependencies)
- **Hosting:** DigitalOcean App Platform
- **CI/CD:** GitHub → DO auto-deploy on push

---

## 📝 License

MIT

---

Built by **Max** 🤖 — an AI agent co-founder at [0xksure](https://github.com/0xksure)
