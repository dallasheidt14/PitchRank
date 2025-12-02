This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## Analytics Events

PitchRank uses Google Analytics 4 (GA4) for tracking user interactions. All events follow GA4 best practices (snake_case naming, no spaces).

### Event Tracking Architecture

- **`lib/analytics.ts`**: Core GA4 helpers (`gtagEvent`, `gtagPageView`)
- **`lib/events.ts`**: Typed tracking functions for each event
- **`types/events.ts`**: TypeScript interfaces for event payloads

### Events Reference

#### Rankings Events

| Event Name | Description | Payload |
|------------|-------------|---------|
| `rankings_viewed` | User views rankings page | `region`, `age_group`, `gender`, `total_teams` |
| `team_row_clicked` | User clicks team row in rankings | `team_id_master`, `team_name`, `club_name`, `state`, `age`, `gender`, `rank_in_cohort_final`, `rank_in_state_final` |
| `sort_used` | User sorts rankings table | `column`, `direction`, `region`, `age_group`, `gender` |
| `filter_applied` | User applies filter | `region`, `age_group`, `gender` |

#### Search Events

| Event Name | Description | Payload |
|------------|-------------|---------|
| `search_used` | User performs a search | `query`, `results_count` |
| `search_result_clicked` | User clicks search result | `team_id_master`, `team_name`, `rank_in_cohort_final` |

#### Team Page Events

| Event Name | Description | Payload |
|------------|-------------|---------|
| `team_page_viewed` | User views a team page | `team_id_master`, `team_name`, `club_name`, `state`, `age`, `gender`, `rank_in_cohort_final`, `power_score_final` |
| `chart_viewed` | Chart component loads | `chart_type` (`momentum` or `trajectory`), `team_id_master` |

#### Compare/Predict Events

| Event Name | Description | Payload |
|------------|-------------|---------|
| `compare_opened` | First team selected | `team_id_master`, `team_name`, `rank_in_cohort_final` |
| `comparison_generated` | Both teams selected | `team_count`, `team_ids`, `team_names` |
| `prediction_viewed` | Prediction loads | `team_a_id`, `team_a_name`, `team_b_id`, `team_b_name`, `win_probability_a`, `win_probability_b`, `draw_probability`, `predicted_winner` |
| `teams_swapped` | User swaps teams | *(no payload)* |

#### Watchlist Events

| Event Name | Description | Payload |
|------------|-------------|---------|
| `watchlist_added` | User adds team to watchlist | `team_id_master`, `team_name`, `club_name`, `state`, `rank_in_cohort_final` |
| `watchlist_removed` | User removes team from watchlist | `team_id_master`, `team_name` |

#### Missing Game Events

| Event Name | Description | Payload |
|------------|-------------|---------|
| `missing_game_clicked` | User opens missing game dialog | `team_id_master`, `team_name` |
| `missing_game_submitted` | User submits missing game request | `team_id_master`, `team_name`, `game_date` |

### Usage Example

```typescript
import { trackTeamRowClicked } from '@/lib/events';

// Track a team row click
trackTeamRowClicked({
  team_id_master: team.team_id_master,
  team_name: team.team_name,
  rank_in_cohort_final: team.rank_in_cohort_final,
});
```

### Development Mode

In development mode (`NODE_ENV === 'development'`), events are logged to the console instead of being sent to GA4. This allows for debugging without polluting production analytics data.
