// Browser capture for SincSports league and tournament schedules.
//
// SincSports answers plain HTTP clients with a Cloudflare challenge, but a
// same-origin fetch() from a page already open on soccer.sincsports.com
// passes. Run this function in that page with the Playwright MCP tool
// browser_evaluate, passing a `filename` under data/raw/ so the returned JSON
// lands on disk instead of in the transcript. The tool does not create
// folders, so make the target folder first. It only reads SincSports pages.
//
// Edit MODE (and FROM or TIDS) before running:
//
//   MODE = "leagues"    walks the Leagues list (events.aspx?sinc=Y&leagues=Y)
//                       from FROM and returns every league found. A search
//                       returns at most 30 leagues with no pager, so the From
//                       Date advances to the latest start date seen until a
//                       search adds nothing new, that date stops advancing,
//                       or 20 searches have run.
//   MODE = "divisions"  for each tid in TIDS, captures every boys division's
//                       games list (&mode=schedule) and every one of its
//                       pages (&gpage=N, 50 games each), in either layout.
//
// Rec, small-sided and adult play is never captured. The leagues search runs
// with Recreation and Small Sided unticked, which drops only leagues SincSports
// tags that way, so league and division names are also checked against
// EXCLUDED_PLAY (a league tagged Competitive can still run "Rec" divisions).
// Excluded leagues and divisions are listed in the output under `excluded`.
//
// The divisions bundle is the input to
//   python scripts/scrape_sincsports_tournament_schedule.py --from-bundle <path>
//
// Requests run one at a time with a random 0.6-1.5 s gap. Keep them sequential:
// overlapping requests to SincSports cancel each other.
async () => {
  const MODE = "leagues";
  const FROM = "08/01/2026";
  const TIDS = [];
  // 7v7 and 9v9 are the standard U9-U12 formats, so only 3v3-6v6 counts as small-sided.
  const EXCLUDED_PLAY = /\b(rec|recreation|recreational|small[\s-]*sided|adults?|[3-6]\s*v\s*[3-6])\b/i;

  const parser = new DOMParser();
  const pause = () => new Promise((resolve) => setTimeout(resolve, 600 + Math.random() * 900));
  const getDoc = async (url, init) => {
    const response = await fetch(url, init);
    const html = await response.text();
    await pause();
    if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
    return { html, doc: parser.parseFromString(html, "text/html") };
  };
  const tidOf = (href) => (href.match(/[?&]tid=([A-Za-z0-9]+)/) || [])[1];

  if (MODE === "leagues") {
    const LEAGUES_URL = "/events.aspx?sinc=Y&leagues=Y";
    const toFormDate = (d) =>
      `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}/${d.getFullYear()}`;
    const leagues = new Map();
    const excluded = new Map();
    let from = FROM;
    for (let search = 0; search < 20; search += 1) {
      const { doc: formDoc } = await getDoc(LEAGUES_URL);
      const aspForm = [...formDoc.forms].find((f) => f.querySelector('[name="__VIEWSTATE"]'));
      for (const control of ["ctl00$ContentPlaceHolder1$tbFrom", "ctl00$ContentPlaceHolder1$btnSearch"]) {
        if (!aspForm?.querySelector(`[name="${control}"]`)) throw new Error(`Leagues search form has no ${control}`);
      }
      const form = new FormData(aspForm);
      for (const box of aspForm.querySelectorAll('input[type="checkbox"]')) {
        const label = formDoc.querySelector(`label[for="${box.id}"]`)?.textContent || "";
        if (/recreation|small sided/i.test(label)) form.delete(box.name);
      }
      form.set("ctl00$ContentPlaceHolder1$tbFrom", from);
      form.set("ctl00$ContentPlaceHolder1$btnSearch", "Search");
      const body = new URLSearchParams();
      for (const [key, value] of form.entries()) if (typeof value === "string") body.append(key, value);
      const { doc } = await getDoc(LEAGUES_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      let added = 0;
      let latest = null;
      // Featured leagues render the same card with an F in every control id (lnkFEventName, lblFDate).
      for (const link of doc.querySelectorAll('a[id$="displayEvent_lnkEventName"], a[id$="displayEvent_lnkFEventName"]')) {
        const tid = tidOf(link.getAttribute("href") || "");
        const card = link.closest(".card");
        const text = (field) => {
          const el = card?.querySelector(`[id$="displayEvent_lbl${field}"], [id$="displayEvent_lblF${field}"]`);
          const html = (el?.innerHTML || "").replace(/<br\s*\/?>/gi, "; ");
          return parser.parseFromString(html, "text/html").body.textContent.replace(/\s+/g, " ").replace(/;\s*$/, "").trim();
        };
        const startDate = text("Date");
        const started = new Date(startDate);
        if (!Number.isNaN(started.getTime()) && (!latest || started > latest)) latest = started;
        if (!tid || leagues.has(tid) || excluded.has(tid)) continue;
        const league = { tid, name: link.textContent.trim(), start_date: startDate, location: text("Location"), ages_text: text("Ages") };
        added += 1;
        // Ages like "BOYS: U09 - U16; GIRLS: Adult" mix youth and adult play; divisions mode drops the adult part.
        const noYouth = EXCLUDED_PLAY.test(league.ages_text) && !/\bU\d{2}\b/.test(league.ages_text);
        if (EXCLUDED_PLAY.test(league.name) || noYouth) excluded.set(tid, league);
        else leagues.set(tid, league);
      }
      if (!added || !latest || toFormDate(latest) === from) break;
      from = toFormDate(latest);
    }
    return {
      captured_at: new Date().toISOString(),
      mode: MODE,
      from: FROM,
      leagues: [...leagues.values()],
      excluded: [...excluded.values()],
    };
  }

  if (MODE === "divisions") {
    const events = [];
    const divisions = [];
    const errors = [];
    const excluded = [];
    for (const tid of TIDS) {
      let rootDoc;
      try {
        ({ doc: rootDoc } = await getDoc(`/schedule.aspx?tid=${tid}`));
      } catch (error) {
        errors.push({ tid, div: "(event root)", page: 1, error: String(error) });
        continue;
      }
      const eventName = rootDoc.title.replace(/^Schedules?\s*-\s*/, "").trim();
      if (EXCLUDED_PLAY.test(eventName)) {
        excluded.push({ tid, div: null, label: eventName });
        continue;
      }
      events.push({ tid, name: eventName });
      // The sched2 picker links every division; an old-layout root links only the one it shows
      // and lists the rest as <option value="U12M01"> entries. Both carry the division's name.
      const labels = new Map();
      for (const option of rootDoc.querySelectorAll("select option")) {
        const code = option.value.toUpperCase();
        if (/^U\d{2}M/.test(code) && !labels.has(code)) labels.set(code, option.textContent.replace(/\s+/g, " ").trim());
      }
      // Old-layout pages also link team names with div= in the URL, so only picker cards name a division.
      for (const a of rootDoc.querySelectorAll("a.sched2-divcard[href*='div='], .sched2-divcard a[href*='div=']")) {
        const code = ((a.getAttribute("href") || "").match(/[?&]div=([A-Za-z0-9]+)/) || [])[1]?.toUpperCase();
        const name = (a.querySelector(".sched2-divcard-name") || a.closest(".sched2-divcard")?.querySelector(".sched2-divcard-name"))?.textContent;
        if (code && !labels.has(code)) labels.set(code, (name || a.textContent).replace(/\s+/g, " ").trim());
      }
      for (const a of rootDoc.querySelectorAll('a[href*="div="]')) {
        const code = ((a.getAttribute("href") || "").match(/[?&]div=([A-Za-z0-9]+)/) || [])[1]?.toUpperCase();
        if (code && !labels.has(code)) labels.set(code, "");
      }
      const codes = [];
      for (const [code, label] of [...labels.entries()].sort()) {
        if (!/^U(0[89]|1\d)M[A-Z0-9]*$/.test(code)) continue;
        if (EXCLUDED_PLAY.test(label)) excluded.push({ tid, div: code, label });
        else codes.push(code);
      }
      for (const div of codes) {
        const base = `/schedule.aspx?tid=${tid}&div=${div}&mode=schedule`;
        let pageCount = 1;
        for (let page = 1; page <= pageCount; page += 1) {
          try {
            const { html, doc } = await getDoc(page === 1 ? base : `${base}&gpage=${page}`);
            // Old-layout divisions page too (sched-pager). The pager links only nearby pages,
            // so its "N games" total at 50 per page sets the count as well.
            const pager = doc.querySelector(".sched-pager, .sched2-pager");
            const info = pager?.querySelector(".sched-pager-info, .sched2-pager-info")?.textContent || "";
            pageCount = Math.max(pageCount, Math.ceil(Number((info.match(/(\d+)\s+games?/i) || [])[1] || 0) / 50));
            for (const a of pager?.querySelectorAll("a[href]") || []) {
              pageCount = Math.max(pageCount, Number((a.getAttribute("href").match(/[?&]gpage=(\d+)/) || [])[1] || 1));
            }
            divisions.push({ tid, div, page, html });
          } catch (error) {
            errors.push({ tid, div, page, error: String(error) });
          }
        }
      }
    }
    return { captured_at: new Date().toISOString(), mode: MODE, events, divisions, errors, excluded };
  }

  throw new Error(`Unknown MODE ${MODE}`);
}
