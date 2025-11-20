import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Watchlist",
  description: "Track your favorite youth soccer teams. View rankings, power scores, and performance metrics for all your saved teams in one place.",
  openGraph: {
    title: "My Watchlist | PitchRank",
    description: "Track your favorite youth soccer teams. View rankings, power scores, and performance metrics for all your saved teams in one place.",
  },
  twitter: {
    card: "summary",
    title: "My Watchlist | PitchRank",
    description: "Track your favorite youth soccer teams. View rankings, power scores, and performance metrics for all your saved teams in one place.",
  },
};

export default function WatchlistLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
