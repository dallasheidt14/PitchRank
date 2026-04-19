import { DataProviders } from '@/app/data-providers';

export default function CompareLayout({ children }: { children: React.ReactNode }) {
  return <DataProviders>{children}</DataProviders>;
}
