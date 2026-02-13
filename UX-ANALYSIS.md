# Solana Narrative Radar — UX/UI Competitive Analysis

**Date:** 2026-02-13  
**Objective:** Benchmark against top crypto dashboards and identify actionable improvements.

---

## Part 1: Competitor Analysis

### DeFiLlama
- **Navigation:** Left sidebar with collapsible categories (DeFi, Yields, Stables, etc.). Sticky top bar with search.
- **Data presentation:** Dense tables with sortable columns, sparkline charts inline, protocol icons. Key metrics as large hero numbers at top.
- **Color scheme:** Dark (#1c1c2d background), accent blue/green for positive, red for negative. Minimal color palette.
- **Loading:** Skeleton loaders, progressive data loading.
- **Mobile:** Responsive tables that scroll horizontally, hamburger menu for sidebar.
- **Trust signals:** Data sources clearly labeled, "Last updated" timestamps, open-source badge, methodology docs linked.
- **What makes it professional:** Data density, consistent visual language, no unnecessary decoration.

### Dune Analytics
- **Navigation:** Top navbar with search, sidebar for query explorer. Tab-based dashboard navigation.
- **Data presentation:** Flexible grid of visualization widgets (charts, tables, counters). User-created dashboards.
- **Color scheme:** Dark theme (#0d0d12), accent purple/blue.
- **Loading:** Skeleton cards, individual widget loading states.
- **Mobile:** Stacked single-column layout.
- **Trust signals:** Query transparency (see the SQL), creator profiles, fork counts.
- **What makes it professional:** Widget-based layout, query transparency, community validation.

### Token Terminal
- **Navigation:** Clean top navbar, horizontal tabs for sections.
- **Data presentation:** Financial statement format (tables), large hero metrics, area charts. "Bloomberg for crypto" aesthetic.
- **Color scheme:** Dark, muted tones. Clean white text on dark backgrounds.
- **Loading:** Smooth skeleton states.
- **Mobile:** Simplified layout, key metrics prioritized.
- **Trust signals:** Standardized financial metrics, institutional language, clean typography.
- **What makes it professional:** Financial formatting, clean spacing, institutional feel.

### Artemis
- **Navigation:** Left sidebar with icons + labels, collapsible. Top breadcrumbs.
- **Data presentation:** Dashboard cards with KPIs, comparison charts, data tables.
- **Color scheme:** Dark with blue accents.
- **Loading:** Progressive loading with shimmer effects.
- **Mobile:** Responsive grid, sidebar becomes bottom nav.
- **Trust signals:** Data provider badges, methodology pages, update frequency shown.
- **What makes it professional:** Clean card layouts, consistent metrics formatting, comparison views.

### Nansen
- **Navigation:** Top navbar with dropdown menus, persistent search.
- **Data presentation:** Smart money labels, wallet flow visualizations, token tables with rich metadata.
- **Color scheme:** Dark theme, green/red for market sentiment.
- **Loading:** Skeleton loaders, progressive enhancement.
- **Mobile:** Native mobile app, responsive web.
- **Trust signals:** "Smart Money" labels, wallet labels, institutional branding.
- **What makes it professional:** Premium feel, clear value hierarchy, consistent iconography.

---

## Part 2: Gap Analysis — Top 10 Improvements

| Rank | Improvement | Impact | Effort | Priority |
|------|-------------|--------|--------|----------|
| 1 | **Sticky professional header with navigation** | High | Low | ✅ Quick win |
| 2 | **Hero metrics section** (large KPIs at top like DeFiLlama) | High | Low | ✅ Quick win |
| 3 | **Skeleton/shimmer loading states** | High | Low | ✅ Quick win |
| 4 | **Prominent trust signals** (data source badges, last updated, methodology) | High | Low | ✅ Quick win |
| 5 | **Better typography hierarchy** (Inter font, consistent sizing) | High | Low | ✅ Quick win |
| 6 | **Smooth card enter animations** | Medium | Low | ✅ Quick win |
| 7 | **Mobile bottom navigation** | Medium | Medium | ✅ Quick win |
| 8 | **Keyboard shortcuts** (j/k to navigate cards) | Low | Low | ✅ Quick win |
| 9 | **Sidebar navigation** (like DeFiLlama/Artemis) | High | High | Later |
| 10 | **Widget-based customizable layout** (like Dune) | High | High | Later |

---

## Part 3: Implemented Changes

### Quick wins implemented:
1. **Professional sticky header** with navigation links, search-like element, and branding
2. **Hero metrics bar** — large KPI numbers prominently displayed (DeFiLlama style)
3. **Skeleton loading states** with shimmer animation
4. **Trust signal badges** — data source icons, last updated prominently, methodology link
5. **Inter font** for professional typography
6. **Staggered card entrance animations** with fade-in-up
7. **Improved color palette** — more muted, professional tones
8. **Better spacing and visual hierarchy** — consistent 8px grid
9. **Smooth hover transitions** on all interactive elements
10. **Mobile-first responsive improvements** — better stacking, touch targets

---

## Part 4: Design Decisions

### Color Palette (inspired by Token Terminal / DeFiLlama)
- Background: `#0c0c14` (slightly warmer than pure dark)
- Surface: `#12121f` 
- Border: `#1e1e30`
- Text primary: `#e8e8f0`
- Text secondary: `#8888a0`
- Accent: `#9945FF` (Solana purple, kept for brand)
- Success: `#00d18c`
- Warning: `#f5a623`

### Typography
- Font: Inter (via Google Fonts) — the standard for crypto dashboards
- Hero metrics: 2rem bold
- Card titles: 1.25rem semibold
- Body: 0.9375rem regular
- Caption: 0.8125rem

### Key Patterns Adopted
- **Data density without clutter** (Token Terminal approach): tighter spacing, more info per viewport
- **Progressive disclosure** (DeFiLlama): collapsed sections, "show more" patterns
- **Trust through transparency** (Dune): visible data sources on every signal
- **Consistent iconography**: source badges on everything
