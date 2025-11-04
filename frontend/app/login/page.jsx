"use client";

import { useState } from "react";

import { supabase } from "@/lib/supabase";

export default function Login() {
  const [email, setEmail] = useState("");

  async function signIn() {
    await supabase.auth.signInWithOtp({ email });
    alert("Check your email");
  }

  return (
    <main style={{ padding: 24 }}>
      <h2>Login</h2>
      <input
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@example.com"
      />
      <button onClick={signIn}>Send Magic Link</button>
    </main>
  );
}
