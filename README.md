# 📡 Solana Narrative Radar

AI-powered tool that detects emerging narratives in the Solana ecosystem by analyzing onchain, developer, and social signals. Generates actionable build ideas for each narrative.

## Architecture

```
[Data Collection Layer]
  ├── Onchain: Helius API, DeFiLlama
  ├── Developer: GitHub API
  └── Social: X/Twitter KOLs

         ↓

[Signal Scoring Engine]
  • Velocity (week-over-week acceleration)
  • Convergence (multiple sources → same theme)
  • Novelty (new vs continuation)
  • Authority (high-signal KOLs vs noise)

         ↓

[LLM Narrative Clustering]
  • Claude groups signals into coherent narratives
  • Confidence scoring (high/medium/low)
  • Explainability: why NOW?

         ↓

[Idea Generation]
  • 3-5 concrete product ideas per narrative
  • Target user, Solana protocols, build complexity

         ↓

[Dashboard / API]
  • Hosted web dashboard
  • Fortnightly refresh
  • Historical comparison
```

## Data Sources

| Source | Type | What We Track |
|--------|------|---------------|
| Helius API | Onchain | New program deployments, usage spikes |
| DeFiLlama | Onchain | TVL by category, protocol growth |
| GitHub API | Developer | New Solana repos, star velocity, commits |
| X/Twitter | Social | KOL tweets, engagement, topic frequency |
| Birdeye | Market | Token trends, volume anomalies |

## Signal Detection Methodology

Signals are scored on a 0-100 scale combining:
- **Velocity (30%)**: Week-over-week growth rate
- **Convergence (40%)**: Number of independent sources pointing to same theme
- **Novelty (20%)**: Is this genuinely new?
- **Authority (10%)**: Signal from high-reputation sources

Signals scoring >60 are fed to the LLM clustering pipeline.

## Tech Stack

- **Backend**: Python (FastAPI)
- **Frontend**: Next.js
- **LLM**: Claude API (narrative clustering + idea generation)
- **Database**: PostgreSQL
- **APIs**: Helius, GitHub, DeFiLlama, Birdeye, X/Twitter
- **Hosting**: Vercel (frontend) + DigitalOcean (backend)

## Running Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## License
MIT
