import { TrendingUp, Award, Activity, Calendar } from 'lucide-react';

/**
 * Stylized mock of the PDF report card. Not a real PDF render — this is a
 * marketing preview so visitors see roughly what the emailed PDF will contain.
 * Update alongside the real PDF design when it changes.
 */
export function ReportCardPreview() {
  return (
    <div className="relative">
      {/* Floating "preview" tag */}
      <div className="absolute -top-3 -right-3 z-10 rotate-3 bg-[#F4D03F] text-[#0B5345] text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full shadow-md font-display">
        Sample
      </div>

      {/* Paper-style card */}
      <div className="bg-white rounded-lg shadow-2xl border border-gray-200 overflow-hidden">
        {/* Header strip — forest green with team name */}
        <div className="bg-[#0B5345] text-white p-5">
          <p className="text-[10px] uppercase tracking-widest text-[#F4D03F] font-display font-semibold">
            Team Report Card
          </p>
          <h3 className="font-display text-2xl font-bold tracking-wide mt-1">Phoenix Rising FC 2014B</h3>
          <p className="text-white/80 text-sm">Phoenix Rising FC · AZ · U13 Boys</p>
        </div>

        {/* Ranks */}
        <div className="grid grid-cols-2 gap-4 p-5 border-b border-gray-200">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-display font-semibold">
              National Rank
            </p>
            <p className="font-display text-4xl font-bold text-[#0B5345]">#47</p>
            <p className="text-xs text-gray-500 mt-1">of 2,412 U13 Boys teams · Top 2%</p>
            <p className="text-xs text-green-700 font-bold mt-1">▲ Up 12 spots in the last 30 days</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-display font-semibold">
              Arizona Rank
            </p>
            <p className="font-display text-4xl font-bold text-[#0B5345]">#3</p>
            <p className="text-xs text-gray-500 mt-1">of 96 U13 Boys teams in Arizona</p>
          </div>
        </div>

        {/* PowerScore + record */}
        <div className="grid grid-cols-2 gap-4 p-5 border-b border-gray-200">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-display font-semibold">PowerScore</p>
            <p className="font-display text-4xl font-bold text-[#0B5345]">50.12</p>
            <p className="text-xs text-gray-500 mt-1">Same score shown on pitchrank.io</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-display font-semibold mb-1">
              Recent Record
            </p>
            <p className="font-mono text-2xl font-bold">14-2-3</p>
            <p className="text-xs text-gray-500">Last 19 ranked games · 82% win rate</p>
          </div>
        </div>

        {/* Last 5 games */}
        <div className="p-5">
          <p className="text-[10px] uppercase tracking-wider text-gray-500 font-display font-semibold mb-2">
            Last 5 games · most recent first
          </p>
          <table className="w-full text-xs">
            <tbody className="divide-y divide-gray-100">
              {[
                { date: 'Nov 9', opp: 'Tucson Soccer Academy 14B', score: '3-1', result: 'W' },
                { date: 'Nov 2', opp: 'AZ Arsenal SC ECNL', score: '2-2', result: 'D' },
                { date: 'Oct 26', opp: 'SC del Sol Premier', score: '4-0', result: 'W' },
                { date: 'Oct 19', opp: 'RSL-AZ North 14B', score: '1-2', result: 'L' },
                { date: 'Oct 12', opp: 'FC Tucson Youth 14B', score: '3-0', result: 'W' },
              ].map((g, i) => (
                <tr key={i} className="py-1.5">
                  <td className="py-1.5 text-gray-500 pr-2">{g.date}</td>
                  <td className="py-1.5 text-gray-700">{g.opp}</td>
                  <td className="py-1.5 font-mono text-right pr-2">{g.score}</td>
                  <td
                    className={`py-1.5 text-right font-bold ${
                      g.result === 'W' ? 'text-green-700' : g.result === 'L' ? 'text-red-700' : 'text-gray-500'
                    }`}
                  >
                    {g.result}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="bg-gray-50 px-5 py-3 flex items-center justify-between text-[10px] text-gray-500 border-t border-gray-200">
          <span className="font-display font-semibold uppercase tracking-wider">PitchRank.io</span>
          <span>Updated weekly</span>
        </div>
      </div>

      {/* What's inside legend */}
      <div className="mt-6 grid grid-cols-2 gap-3 text-sm">
        {[
          { icon: Award, label: 'National & state rank' },
          { icon: TrendingUp, label: '30-day rank change' },
          { icon: Activity, label: 'PowerScore & recent record' },
          { icon: Calendar, label: 'Last 5 games + opponents' },
        ].map(({ icon: Icon, label }) => (
          <div key={label} className="flex items-center gap-2 text-gray-700">
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#0B5345]/10 flex items-center justify-center">
              <Icon className="w-3.5 h-3.5 text-[#0B5345]" />
            </div>
            <span className="text-xs">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
