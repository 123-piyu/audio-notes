import "./globals.css";
import Link from "next/link";

export const metadata = { title: "Audio Notes" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <header className="nav">
          <Link href="/"><strong>Audio Notes</strong></Link>
          <Link href="/architecture">Architecture</Link>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}