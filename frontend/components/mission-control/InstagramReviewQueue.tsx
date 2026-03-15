'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Instagram,
  Check,
  X,
  Loader2,
  ExternalLink,
  Search,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

interface ReviewItem {
  handle: string;
  club_name: string;
  confidence: number;
  team_count: number;
  profile_url: string | null;
}

const PAGE_SIZE = 50;

export function InstagramReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);

  const fetchItems = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/instagram-review');
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setItems(data.items ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const handleAction = useCallback(
    async (handle: string, action: 'approve' | 'reject') => {
      setPending((prev) => new Set(prev).add(handle));

      const snapshot = items;
      setItems((prev) => prev.filter((i) => i.handle !== handle));

      try {
        const res = await fetch('/api/instagram-review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ handle, action }),
        });
        if (!res.ok) {
          throw new Error('Update failed');
        }
      } catch {
        setItems(snapshot);
      } finally {
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(handle);
          return next;
        });
      }
    },
    [items],
  );

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter(
      (i) =>
        i.club_name.toLowerCase().includes(q) ||
        i.handle.toLowerCase().includes(q),
    );
  }, [items, search]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paged = useMemo(
    () => filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filtered, page],
  );

  useEffect(() => {
    setPage(0);
  }, [search]);

  if (loading) {
    return (
      <Card className="border-gray-700 bg-gray-900/60">
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          <span className="ml-2 text-gray-400">Loading review queue...</span>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-red-800 bg-gray-900/60">
        <CardContent className="py-8 text-center text-red-400">
          {error}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-gray-700 bg-gray-900/60">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Instagram className="h-5 w-5 text-pink-400" />
            <CardTitle className="text-lg text-white">
              Instagram Handle Review
            </CardTitle>
            <Badge variant="outline" className="text-gray-300 border-gray-600">
              {items.length} remaining
            </Badge>
          </div>
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" />
            <Input
              placeholder="Filter by club or handle..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-gray-800 border-gray-600 text-white placeholder:text-gray-500"
            />
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-0 pb-2">
        {filtered.length === 0 ? (
          <div className="py-12 text-center text-gray-500">
            {items.length === 0
              ? 'All caught up — nothing to review!'
              : 'No results match your filter.'}
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow className="border-gray-700 hover:bg-transparent">
                  <TableHead className="text-gray-400 pl-4">Club</TableHead>
                  <TableHead className="text-gray-400">Handle</TableHead>
                  <TableHead className="text-gray-400 text-right">Confidence</TableHead>
                  <TableHead className="text-gray-400 text-right">Teams</TableHead>
                  <TableHead className="text-gray-400 text-right pr-4">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paged.map((item) => {
                  const isPending = pending.has(item.handle);
                  return (
                    <TableRow
                      key={item.handle}
                      className="border-gray-800 hover:bg-gray-800/50"
                    >
                      <TableCell className="pl-4 font-medium text-white">
                        {item.club_name}
                      </TableCell>
                      <TableCell>
                        <a
                          href={`https://instagram.com/${item.handle}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-pink-400 hover:text-pink-300 transition-colors"
                        >
                          @{item.handle}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-gray-300">
                        {(item.confidence * 100).toFixed(0)}%
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-gray-300">
                        {item.team_count}
                      </TableCell>
                      <TableCell className="text-right pr-4">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={isPending}
                            className="h-7 px-2 text-green-400 hover:text-green-300 hover:bg-green-900/30"
                            onClick={() => handleAction(item.handle, 'approve')}
                          >
                            {isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Check className="h-4 w-4" />
                            )}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={isPending}
                            className="h-7 px-2 text-red-400 hover:text-red-300 hover:bg-red-900/30"
                            onClick={() => handleAction(item.handle, 'reject')}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 pt-3 pb-2 border-t border-gray-800">
                <span className="text-xs text-gray-500">
                  Showing {page * PAGE_SIZE + 1}–
                  {Math.min((page + 1) * PAGE_SIZE, filtered.length)} of{' '}
                  {filtered.length}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={page === 0}
                    className="h-7 px-2 text-gray-400 hover:text-white"
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="text-xs text-gray-400 px-2">
                    {page + 1}/{totalPages}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={page >= totalPages - 1}
                    className="h-7 px-2 text-gray-400 hover:text-white"
                    onClick={() => setPage((p) => p + 1)}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
