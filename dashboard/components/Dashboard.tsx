"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardData } from "../lib/types";

const BOT_URL = "https://t.me/geberefarmbot";
const TYPES = ["text", "voice", "photo"] as const;
const COLORS: Record<string, string> = { text: "#1F9D55", voice: "#F5C451", photo: "#F28B66" };
const TAGTEXT: Record<string, string> = { text: "#137A41", voice: "#8A6A0A", photo: "#C2562F" };
const LABEL: Record<string, string> = { text: "Text", voice: "Voice", photo: "Photo" };
const DAY = 864e5;

function useCount(target: number) {
  // Starts at the real value (so server-rendered HTML is correct) and only
  // animates when the value later changes, e.g. when a filter is switched.
  const [v, setV] = useState(target);
  const prev = useRef(target);
  useEffect(() => {
    const from = prev.current;
    prev.current = target;
    if (from === target || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setV(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / 700);
      setV(Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return v;
}

function Kpi({ label, value, suffix = "", note }: { label: string; value: number; suffix?: string; note: string }) {
  const n = useCount(value);
  return (
    <div className="card kpi">
      <h2>{label}</h2>
      <div className="num">{n}{suffix}</div>
      <p>{note}</p>
    </div>
  );
}

function ago(iso: string) {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}

export default function Dashboard({ data }: { data: DashboardData }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [days, setDays] = useState<7 | 14 | 30>(14);
  const [type, setType] = useState<"all" | (typeof TYPES)[number]>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const refresh = () => start(() => router.refresh());
  useEffect(() => {
    const id = setInterval(() => router.refresh(), 60000);
    return () => clearInterval(id);
  }, [router]);

  const inRange = useMemo(() => {
    const now = Date.now();
    return data.interactions.filter(
      (i) => (type === "all" || i.type === type) && now - new Date(i.at).getTime() <= days * DAY
    );
  }, [data.interactions, days, type]);

  const chart = useMemo(() => {
    const m = new Map<string, Record<string, string | number>>();
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(Date.now() - i * DAY).toISOString().slice(0, 10);
      m.set(d, { date: d, text: 0, voice: 0, photo: 0 });
    }
    for (const i of inRange) {
      const row = m.get(i.at.slice(0, 10));
      if (row && i.type in row) (row[i.type] as number)++;
    }
    return [...m.values()];
  }, [inRange, days]);

  const mix = useMemo(
    () => TYPES.map((t) => ({ t, n: data.interactions.filter((i) => i.type === t && Date.now() - new Date(i.at).getTime() <= days * DAY).length })),
    [data.interactions, days]
  );
  const mixTotal = mix.reduce((n, x) => n + x.n, 0) || 1;

  const feed = useMemo(() => {
    const q = query.trim().toLowerCase();
    return inRange
      .filter((i) => i.q !== undefined && (!q || `${i.q} ${i.a}`.toLowerCase().includes(q)))
      .slice(0, 12);
  }, [inRange, query]);

  const locPct = data.totalFarmers ? Math.round((data.farmersWithLocation / data.totalFarmers) * 100) : 0;
  const maxCrop = Math.max(1, ...data.crops.map((c) => c.count));

  return (
    <main className="wrap">
      <nav className="nav">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 21V11" /><path d="M12 11C12 7 9 4.5 4.5 4.5 4.5 9 7 11 12 11Z" /><path d="M12 14c0-3 2.4-5 7-5 0 3.6-2.2 5-7 5Z" />
            </svg>
          </span>
          <b>Gebere</b>
          <span className="am" lang="am">ገበሬ</span>
        </div>
        <div className="navr">
          <span className="live">Live</span>
          <button className="ghost" onClick={refresh} disabled={pending}>{pending ? "Refreshing…" : "Refresh"}</button>
        </div>
      </nav>

      <section className="hero">
        <p className="eyebrow">AI farming assistant on Telegram</p>
        <h1>An agronomist in <span>every pocket.</span></h1>
        <p className="lead">Farmers ask by voice, text or crop photo. Gebere replies with practical advice using their local 7-day weather. This is the live, anonymized view.</p>
        <a className="cta" href={BOT_URL} target="_blank" rel="noreferrer">Try it on Telegram →</a>
      </section>

      <div className="controls" role="group" aria-label="Dashboard filters">
        <div className="seg" role="group" aria-label="Time range">
          {([7, 14, 30] as const).map((d) => (
            <button key={d} className={days === d ? "on" : ""} aria-pressed={days === d} onClick={() => setDays(d)}>{d} days</button>
          ))}
        </div>
        <div className="chips" role="group" aria-label="Question type">
          {(["all", ...TYPES] as const).map((t) => (
            <button key={t} className={type === t ? "on" : ""} aria-pressed={type === t} onClick={() => { setType(t); setOpen(null); }}>
              {t !== "all" && <i style={{ background: COLORS[t] }} />}{t === "all" ? "All" : LABEL[t]}
            </button>
          ))}
        </div>
      </div>

      <section className="grid4">
        <Kpi label="Farmers" value={data.totalFarmers} note="registered on Telegram" />
        <Kpi label="Questions answered" value={inRange.length} note={`in the last ${days} days`} />
        <Kpi label="Location shared" value={locPct} suffix="%" note="get local weather advice" />
        <Kpi label="All-time interactions" value={data.totalInteractions} note="since launch" />
      </section>

      <section className="row2">
        <div className="card">
          <h2>Activity</h2>
          <div style={{ height: 250 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#E1ECDD" />
                <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fill: "#5E7567", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={16} />
                <YAxis allowDecimals={false} tick={{ fill: "#5E7567", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "rgba(31,157,85,.08)" }} contentStyle={{ borderRadius: 12, border: "1px solid #E1ECDD", boxShadow: "0 8px 24px rgba(18,48,30,.1)" }} />
                {TYPES.map((t) => (
                  <Bar key={t} dataKey={t} name={LABEL[t]} stackId="a" fill={COLORS[t]} radius={t === "photo" ? [6, 6, 0, 0] : 0} animationDuration={500} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h2>How farmers ask</h2>
          <div className="bars">
            {mix.map(({ t, n }) => (
              <button key={t} className="bar" onClick={() => setType(type === t ? "all" : t)} aria-label={`Filter by ${LABEL[t]}`}>
                <span className="bt"><span>{LABEL[t]}</span><span>{n} · {Math.round((n / mixTotal) * 100)}%</span></span>
                <span className="track"><i style={{ width: `${(n / mixTotal) * 100}%`, background: COLORS[t] }} /></span>
              </button>
            ))}
          </div>
          <p className="hint">Tap a bar to filter everything.</p>
        </div>
      </section>

      <section className="row2">
        <div className="card">
          <h2>Crops grown</h2>
          {data.crops.length === 0 ? <p className="empty">No crops yet.</p> : (
            <div className="bars">
              {data.crops.map((c) => (
                <div className="crop" key={c.crop}>
                  <span className="bt"><span>{c.crop}</span><span>{c.count}</span></span>
                  <span className="track"><i style={{ width: `${(c.count / maxCrop) * 100}%`, background: "#1F9D55" }} /></span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h2>Recent conversations</h2>
          {data.textHidden ? (
            <p className="empty">Conversation text is hidden on the public dashboard to protect farmers&apos; privacy. Counts and charts are live.</p>
          ) : (
            <input className="search" placeholder="Search questions and answers…" value={query} onChange={(e) => { setQuery(e.target.value); setOpen(null); }} aria-label="Search conversations" />
          )}
          {data.textHidden ? null : feed.length === 0 ? <p className="empty">{data.interactions.some((i) => i.q !== undefined) ? "No matches." : "Nothing to show yet."}</p> : (
            <div className="feed">
              {feed.map((r, i) => (
                <div className={`item ${open === i ? "open" : ""}`} key={r.at + i}>
                  <button onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
                    <span className="meta"><span className="tag" style={{ color: TAGTEXT[r.type] }}>{LABEL[r.type] ?? r.type}</span><span suppressHydrationWarning>{ago(r.at)}</span></span>
                    <span className="q">{r.q || "(no text)"}</span>
                  </button>
                  {open === i && <p className="a">{r.a}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <footer>Names, usernames, Telegram IDs and coordinates are never shown. Built with FastAPI, Whisper, Open-Meteo, Supabase and Next.js.</footer>
    </main>
  );
}
