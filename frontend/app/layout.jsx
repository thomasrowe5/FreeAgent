import Script from "next/script";
import "../styles.css";

export const metadata = {
  title: "FreeAgent",
  description: "AI ops manager for freelancers",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <Script
          src="https://plausible.io/js/script.js"
          data-domain="freeagent.yourdomain.com"
          strategy="afterInteractive"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
