# Solana Narrative Radar — Agent API

AI-powered detection of emerging Solana narratives with actionable build ideas.

## Quick Start

```bash
# Get the best build idea right now
curl https://solana-narrative-radar-8vsib.ondigitalocean.app/api/agent/discover

# List all ideas
curl https://solana-narrative-radar-8vsib.ondigitalocean.app/api/agent/ideas

# Filter ideas
curl "https://solana-narrative-radar-8vsib.ondigitalocean.app/api/agent/ideas?complexity=DAYS&min_confidence=HIGH&direction=ACCELERATING"

# Get all narratives
curl https://solana-narrative-radar-8vsib.ondigitalocean.app/api/agent/narratives
```

## Endpoints

### GET `/api/agent/discover`
Returns the single best build idea right now with a `why_now` urgency explanation.

### GET `/api/agent/ideas`
All build ideas with full context. Query params:
- `complexity` — HOURS, DAYS, WEEKS, MONTHS
- `min_confidence` — LOW, MEDIUM, HIGH
- `direction` — EMERGING, ACCELERATING, STABILIZING
- `topic` — keyword filter (e.g. "defi", "nft")

### GET `/api/agent/ideas/{id}`
Single idea by ID with full detail and supporting signals.

### GET `/api/agent/narratives`
All detected narratives with signal counts, confidence, direction, and linked ideas.

## Agent Discovery

- OpenAPI spec: `https://solana-narrative-radar-8vsib.ondigitalocean.app/openapi.json`
- AI plugin manifest: `https://solana-narrative-radar-8vsib.ondigitalocean.app/.well-known/ai-plugin.json`

## Data Model

Each **idea** contains:
- `id`, `name`, `description` — what to build
- `narrative`, `narrative_confidence`, `narrative_direction` — parent trend
- `complexity` — estimated build effort
- `supporting_evidence` — signals backing this idea
- `freshness`, `generated_at` — how recent

Each **narrative** contains:
- `name`, `confidence`, `direction`, `explanation`
- `topics`, `signal_count`, `idea_count`
- `ideas` — linked build ideas

## Update Frequency

Data refreshes every 2 hours from GitHub, Twitter/X, DeFiLlama, and on-chain sources.
