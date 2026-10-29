import Link from "next/link";
import { site } from "../site";
import "./globals.css";

export const metadata = {
  metadataBase: new URL(site.url),
  title: { default: site.name, template: `%s · ${site.name}` },
  description: site.description,
  openGraph: { title: site.name, description: site.description, type: "website" },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <div className="wrap">
          <header className="site-header">
            <Link className="brand" href="/">{site.name}</Link>
            <nav aria-label="Main">
              {site.nav.map((item) => (
                <Link key={item.href} href={item.href}>{item.label}</Link>
              ))}
            </nav>
          </header>
          <main id="main">{children}</main>
          <footer>© {new Date().getFullYear()} {site.name}</footer>
        </div>
      </body>
    </html>
  );
}
