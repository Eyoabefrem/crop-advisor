import "server-only";
import { createClient } from "@supabase/supabase-js";

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SECRET_KEY;

if (!url || !key) {
  throw new Error(
    "Missing SUPABASE_URL or SUPABASE_SECRET_KEY in dashboard/.env.local"
  );
}

export const supabase = createClient(url, key, {
  auth: { persistSession: false, autoRefreshToken: false },
});