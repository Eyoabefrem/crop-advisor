import "server-only";
import { supabase } from "./supabase";
import type { DashboardData } from "./types";

const WITH_TEXT = 40; // newest N interactions include (sanitised) text
const HIDE_TEXT = process.env.HIDE_CONVERSATIONS === "true";

// Public dashboard = no personal data: mask long numbers and @handles, shorten.
function sanitize(text: string | null, max: number): string {
  const clean = (text ?? "")
    .replace(/\d{6,}/g, "•••")
    .replace(/@\w+/g, "@•••")
    .replace(/\s+/g, " ")
    .trim();
  return clean.length > max ? clean.slice(0, max).trimEnd() + "…" : clean;
}

const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export async function getData(): Promise<DashboardData> {
  const [farmers, total, located, cropRows, rows] = await Promise.all([
    supabase.from("farmers").select("*", { count: "exact", head: true }),
    supabase.from("interactions").select("*", { count: "exact", head: true }),
    supabase.from("farmers").select("*", { count: "exact", head: true }).not("latitude", "is", null),
    supabase.from("farmers").select("crop").not("crop", "is", null).limit(5000),
    supabase
      .from("interactions")
      .select("interaction_type, user_message, ai_response, created_at")
      .order("created_at", { ascending: false })
      .limit(500),
  ]);

  for (const r of [farmers, total, located, cropRows, rows]) {
    if (r.error) throw new Error(r.error.message);
  }

  const cropCounts: Record<string, number> = {};
  for (const r of cropRows.data ?? []) {
    const c = String(r.crop).trim().toLowerCase();
    if (c) cropCounts[c] = (cropCounts[c] ?? 0) + 1;
  }
  const sorted = Object.entries(cropCounts).sort((a, b) => b[1] - a[1]);
  const crops = sorted.slice(0, 7).map(([crop, count]) => ({ crop: titleCase(crop), count }));
  const other = sorted.slice(7).reduce((n, [, c]) => n + c, 0);
  if (other > 0) crops.push({ crop: "Other", count: other });

  return {
    totalFarmers: farmers.count ?? 0,
    totalInteractions: total.count ?? 0,
    farmersWithLocation: located.count ?? 0,
    crops,
    textHidden: HIDE_TEXT,
    interactions: (rows.data ?? []).map((r, i) => ({
      type: r.interaction_type,
      at: r.created_at,
      ...(i < WITH_TEXT && !HIDE_TEXT
        ? { q: sanitize(r.user_message, 280), a: sanitize(r.ai_response, 700) }
        : {}),
    })),
  };
}