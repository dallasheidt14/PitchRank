import { DataProviders } from '@/app/data-providers';

export default function TeamLayout({ children }: { children: React.ReactNode }) {
  return <DataProviders>{children}</DataProviders>;
}
