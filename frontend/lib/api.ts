import { supabase } from "@/lib/supabase";

export const API = process.env.NEXT_PUBLIC_API_URL!;

async function buildHeaders(initHeaders?: HeadersInit) {
  const headers = new Headers(initHeaders ?? {});
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export async function getJSON(path: string, init?: RequestInit) {
  const headers = await buildHeaders(init?.headers);
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers,
    cache: init?.cache ?? "no-store",
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function postJSON(path: string, body: unknown) {
  const headers = await buildHeaders();
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}
