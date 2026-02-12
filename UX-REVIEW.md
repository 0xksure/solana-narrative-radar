# Solana Narrative Radar — UX Review

**Date:** 2026-02-12  
**Reviewer:** Max (AI Co-Founder)  
**App URL:** https://solana-narrative-radar-8vsib.ondigitalocean.app

---

## 1. Functional Testing Results

| Endpoint | Method | Status | Response Time | Notes |
|----------|--------|--------|---------------|-------|
| `/` | GET | 200 ✅ | 160ms | Homepage loads with full content |
| `/health` | GET | 200 ✅ | 144ms | Returns `{"status":"ok"}` |
| `/api/narratives` | GET | 200 ✅ | 37ms | Returns full JSON with 7 narratives, 382 signals |
| `/api/generate` | POST | 200 ✅ | **18.8s** ⚠️ | Works but very slow — needs loading UX |
| Refresh Button | Click | ✅ | — | Button found, labeled "🔄 Refresh" |

### Key Findings
- **API is functional** — all endpoints return correct responses
- **`/api/generate` takes ~19 seconds** — no loading indicator visible during this time (Critical UX gap)
- **382 total signals** collected (174 GitHub, 198 DeFi, 10 Social)
- **7 narratives detected**: DeFi (HIGH), Trading, Other, AI Agents, NFTs/Gaming, Infrastructure, RWA (LOW)

---

## 2. Screenshots

Screenshots saved to `ux-review/` directory:

| Viewport | File | Observations |
|----------|------|-------------|
| Desktop 1440×900 | `desktop.png` | Content readable but flat hierarchy — all cards look the same regardless of confidence level |
| Tablet 768×1024 | `tablet.png` | Narrow column layout wastes horizontal space; doesn't adapt to wider viewport |
| Mobile 375×812 | `mobile.png` | Dense but functional; touch targets too small; text needs enlarging |

---

## 3. What Works Well ✅

1. **Clean dark theme** — the color palette is cohesive and professional
2. **Good data structure** — narratives with confidence + direction + signals + build ideas is a solid information architecture
3. **Stats bar at top** provides quick context (382 signals, breakdowns by source)
4. **Build Ideas are actionable** — each has a name, description, and time estimate (Weeks/Months/Days)
5. **Fast API responses** — `/api/narratives` at 37ms is excellent
6. **Numbered narratives** create natural ordering/ranking
7. **Single-page design** — no navigation needed, everything is scannable

---

## 4. Issues Found

### 🔴 Critical

**C1: No loading state for Refresh/Generate (19s wait)**  
The `/api/generate` endpoint takes ~19 seconds. When clicking Refresh, there's no spinner, progress bar, or disabled state. Users will click multiple times or think it's broken.  
**Fix:** Add loading spinner, disable button during fetch, show "Generating narratives..." overlay.

### 🟠 High

**H1: Flat visual hierarchy — all narrative cards look identical**  
A HIGH/ACCELERATING narrative (DeFi) looks the same as LOW/EMERGING (RWA). The confidence badges are tiny and easy to miss.  
**Fix:** Use visual weight to differentiate — larger cards for HIGH confidence, color-coded left borders (green=HIGH, yellow=MEDIUM, red=LOW), larger badges.

**H2: Text too small — fails WCAG accessibility**  
Signal URLs and descriptions appear to be ~10-11px. Gray-on-dark secondary text has insufficient contrast ratio.  
**Fix:** Minimum 14px body text, ensure all text meets WCAG AA contrast (4.5:1 ratio minimum).

**H3: No error handling UX**  
If the API is down or `/api/generate` fails, there's no error state visible to users. No retry option, no error message.  
**Fix:** Add error toast/banner with retry button. Handle network errors gracefully.

### 🟡 Medium

**M1: Mobile touch targets too small**  
Badge pills, signal links, and filter tags are below the 44×44px minimum recommended by Apple HIG.  
**Fix:** Increase padding on all interactive elements to 44px minimum height.

**M2: Tablet layout doesn't utilize screen width**  
On 768px viewport, content renders in a narrow single column with wasted space on sides.  
**Fix:** Use CSS grid to show 2-column layout on tablet, or increase max-width.

**M3: Raw URLs displayed instead of friendly names**  
Signal names like `younesouhene-netizen/Solana-Memecoin-Trading-Bot` are noisy GitHub repo paths.  
**Fix:** Show repo name only (truncate org prefix), or show as friendly link with tooltip.

**M4: Build Ideas section not visually distinct enough**  
Build Ideas are the most actionable content but blend into the card body.  
**Fix:** Give Build Ideas a distinct background color, or separate them into their own section/tab.

### 🟢 Low

**L1: No timestamp for "last updated"**  
Shows date (2/12/2026) but no time. Users can't tell if data is stale.  
**Fix:** Add "Last updated: 2h ago" or exact timestamp.

**L2: Social signal count is very low (10 vs 382 total)**  
Only 10 social signals out of 382 — may indicate data collection issue or should be noted to users.  
**Fix:** Either improve social signal collection or add note explaining the ratio.

**L3: No way to filter or sort narratives**  
Users can't filter by confidence level or sort by direction.  
**Fix:** Add filter chips (HIGH/MEDIUM/LOW) and sort dropdown.

---

## 5. Improvement Recommendations (Priority Order)

1. **Add loading states** — spinner + disabled button + progress text during generate
2. **Visual hierarchy overhaul** — differentiate cards by confidence level with borders/size/color
3. **Fix text sizes and contrast** — accessibility compliance
4. **Add error handling UI** — toast notifications, retry buttons
5. **Responsive layout for tablet** — 2-column grid
6. **Increase mobile touch targets** — minimum 44px
7. **Clean up signal display** — truncate URLs, add tooltips
8. **Add "last updated" timestamp** — show freshness
9. **Add filtering/sorting** — let users focus on what matters
10. **Separate Build Ideas** — make them a distinct, prominent section

---

## 6. Overall Score

| Category | Score | Notes |
|----------|-------|-------|
| Functionality | 8/10 | All endpoints work, data is good |
| Visual Design | 6/10 | Clean dark theme but flat hierarchy |
| Responsiveness | 4/10 | Mobile/tablet need significant work |
| Accessibility | 3/10 | Text size, contrast, touch targets all need fixing |
| UX Flow | 5/10 | Missing loading/error states; no filtering |
| **Overall** | **5.2/10** | **Solid foundation, needs UX polish** |
